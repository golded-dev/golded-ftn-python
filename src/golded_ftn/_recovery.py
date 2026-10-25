"""Internal durable recovery manifest, snapshot, and restore primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any, NoReturn

from ._writer_io import IO
from .models import (
    CommitState,
    OfflineRecoveryAssertion,
    PhysicalBaseIdentity,
    PreparedMutation,
    RecoveryError,
    RecoveryOperationKind,
    RecoveryReference,
    WriteResult,
)

SCHEMA_VERSION = 1
BASE_BINDING_FILENAME = ".base-binding.json"
BASE_BINDING_TMP_FILENAME = ".base-binding.json.tmp"

_UUID_PAT = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
_PREPARING_RE = re.compile(rf"^{_UUID_PAT}\.preparing\.json$")
_PREPARING_TMP_RE = re.compile(rf"^{_UUID_PAT}\.preparing\.json\.tmp$")
_READY_RE = re.compile(rf"^{_UUID_PAT}\.ready\.json$")
_READY_TMP_RE = re.compile(rf"^{_UUID_PAT}\.ready\.json\.tmp$")
_SNAP_RE = re.compile(rf"^{_UUID_PAT}\.Snap\.([A-Za-z0-9_.-]+)$")
_SAFE_ROLE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_HUDSON_SCAN_DIR_LOCK = threading.Lock()
_HUDSON_SCAN_DIR_REGISTRY: dict[str, str] = {}


def register_hudson_scan_dir(canonical_key: str, scan_dir: str | PathLike[str]) -> str:
    """Bind a Hudson physical base canonical key to a single resolved scan_dir."""
    resolved = _resolve_registered_root(scan_dir)
    with _HUDSON_SCAN_DIR_LOCK:
        existing = _HUDSON_SCAN_DIR_REGISTRY.get(canonical_key)
        if existing is not None and existing != resolved:
            raise RecoveryError(code="conflicting_scan_dir")
        _HUDSON_SCAN_DIR_REGISTRY[canonical_key] = resolved
    return resolved


def clear_hudson_scan_dir_registry() -> None:
    """Clear the process-wide Hudson scan_dir registry (for isolated tests)."""
    with _HUDSON_SCAN_DIR_LOCK:
        _HUDSON_SCAN_DIR_REGISTRY.clear()


def canonical_key_sha256(canonical_key: str) -> str:
    return hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()


def _raise_closed(code: str, cause: BaseException | None = None) -> NoReturn:
    error = RecoveryError(code=code)
    if cause is not None:
        error._cause = cause
    raise error from None


def _normalize_rel_path(rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path:
        raise RecoveryError(code="unsafe_recovery_path")
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise RecoveryError(code="unsafe_recovery_path")
    normalized = rel.as_posix()
    if not normalized or normalized == ".":
        raise RecoveryError(code="unsafe_recovery_path")
    return normalized


def _require_uuidv4(transaction_id: object) -> uuid.UUID:
    if not isinstance(transaction_id, uuid.UUID) or transaction_id.version != 4:
        raise RecoveryError(code="unsafe_recovery_path")
    return transaction_id


def _paths_overlap(left: str, right: str) -> bool:
    try:
        common = os.path.commonpath([left, right])
    except ValueError:
        return False
    return common == left or common == right


def _fsync_dir(path: str | PathLike[str]) -> None:
    if sys.platform == "win32":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as err:
        _raise_closed("corrupt_recovery_manifest", err)


def _write_secure_file(
    path: Path,
    data: bytes,
    *,
    io: IO,
    error_code: str = "corrupt_recovery_manifest",
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            else:
                os.chmod(path, 0o600)
            io.write(fd, 0, data)
            io.truncate(fd, len(data))
            io.flush(fd)
        finally:
            os.close(fd)
    except RecoveryError:
        raise
    except OSError as err:
        _raise_closed(error_code, err)


def _intended_resolved_dir(raw_path: Path) -> str:
    try:
        if raw_path.exists() and not raw_path.is_symlink():
            return os.path.realpath(raw_path)
        parent_real = os.path.realpath(raw_path.parent)
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)
    return str(Path(parent_real) / raw_path.name)


def _ensure_secure_recovery_root(
    recovery_root: str | PathLike[str],
    base_roots: Mapping[str, str],
) -> Path:
    raw_path = Path(os.fspath(recovery_root))
    if ".." in raw_path.parts:
        raise RecoveryError(code="unsafe_recovery_path")
    parent = raw_path.parent
    if not parent.exists():
        raise RecoveryError(code="unsafe_recovery_path")
    try:
        if raw_path.is_symlink():
            raise RecoveryError(code="unsafe_recovery_path")
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)

    resolved_root = _intended_resolved_dir(raw_path)
    for reg_root in base_roots.values():
        if _paths_overlap(resolved_root, reg_root):
            raise RecoveryError(code="unsafe_recovery_path")

    if not raw_path.exists():
        try:
            os.mkdir(raw_path, 0o700)
        except OSError as err:
            _raise_closed("unsafe_recovery_path", err)
    try:
        os.chmod(raw_path, 0o700)
        st = os.lstat(raw_path)
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise RecoveryError(code="unsafe_recovery_path")

    try:
        resolved_root = os.path.realpath(raw_path)
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)
    for reg_root in base_roots.values():
        if _paths_overlap(resolved_root, reg_root):
            raise RecoveryError(code="unsafe_recovery_path")
    return Path(resolved_root)


def _resolve_registered_root(root_path: str | PathLike[str]) -> str:
    raw = Path(os.fspath(root_path))
    if ".." in raw.parts or not raw.exists():
        raise RecoveryError(code="unsafe_recovery_path")
    try:
        if raw.is_symlink():
            raise RecoveryError(code="unsafe_recovery_path")
        st = os.lstat(raw)
        resolved = os.path.realpath(raw)
    except RecoveryError:
        raise
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)
    if not stat.S_ISDIR(st.st_mode):
        raise RecoveryError(code="unsafe_recovery_path")
    return resolved


def resolve_contained_path(
    base_roots: Mapping[str, str],
    root_key: str,
    rel_path: str,
) -> Path:
    """Resolve rel_path inside base_roots[root_key], rejecting traversal or symlinks."""
    if root_key not in base_roots:
        raise RecoveryError(code="unsafe_recovery_path")
    reg_root = base_roots[root_key]
    if not rel_path or isinstance(rel_path, str) is False:
        raise RecoveryError(code="unsafe_recovery_path")
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts or len(rel.parts) == 0:
        raise RecoveryError(code="unsafe_recovery_path")
    candidate = Path(reg_root)
    for part in rel.parts:
        if part in {"", "."}:
            raise RecoveryError(code="unsafe_recovery_path")
        candidate = candidate / part
        try:
            st = os.lstat(candidate)
        except FileNotFoundError:
            continue
        except OSError as err:
            _raise_closed("unsafe_recovery_path", err)
        if stat.S_ISLNK(st.st_mode):
            raise RecoveryError(code="unsafe_recovery_path")

    try:
        parent_real = os.path.realpath(candidate.parent)
        common = os.path.commonpath([reg_root, parent_real])
    except ValueError as err:
        _raise_closed("unsafe_recovery_path", err)
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)
    if common != reg_root:
        raise RecoveryError(code="unsafe_recovery_path")

    try:
        resolved = os.path.realpath(candidate)
        common_target = os.path.commonpath([reg_root, resolved])
    except ValueError as err:
        _raise_closed("unsafe_recovery_path", err)
    except OSError as err:
        _raise_closed("unsafe_recovery_path", err)
    if common_target != reg_root or resolved == reg_root:
        raise RecoveryError(code="unsafe_recovery_path")
    return Path(resolved)


@dataclass(frozen=True, slots=True, kw_only=True)
class FileMutationPlan:
    role: str
    root_key: str = "base"
    rel_path: str
    fd: int | None = None
    require_inode_match: bool = True
    planned_write_ranges: tuple[tuple[int, int], ...] = ()
    post_min_len: int | None = None
    post_max_len: int | None = None
    own_created_inode: tuple[int, int] | None = None
    planned_new_bytes: bytes | None = field(default=None, repr=False)
    planned_temp_rel_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.role or not _SAFE_ROLE_RE.match(self.role):
            raise ValueError("Invalid file role identifier")
        normalized_ranges: list[tuple[int, int]] = []
        for start, end in self.planned_write_ranges:
            if start < 0 or end < start:
                raise ValueError("Invalid planned write range")
            normalized_ranges.append((int(start), int(end)))
        object.__setattr__(self, "planned_write_ranges", tuple(normalized_ranges))
        object.__setattr__(self, "rel_path", _normalize_rel_path(self.rel_path))
        object.__setattr__(
            self,
            "planned_temp_rel_paths",
            tuple(_normalize_rel_path(temp) for temp in self.planned_temp_rel_paths),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedFileRecord:
    role: str
    root_key: str
    rel_path: str
    existed: bool
    inode: tuple[int, int] | None
    require_inode_match: bool
    pre_len: int
    pre_sha256: str | None
    snapshot_filename: str | None
    post_min_len: int
    post_max_len: int
    planned_write_ranges: tuple[tuple[int, int], ...]
    own_created_inode: tuple[int, int] | None
    planned_new_len: int | None
    planned_new_sha256: str | None
    planned_temp_rel_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "root_key": self.root_key,
            "rel_path": self.rel_path,
            "existed": self.existed,
            "inode": list(self.inode) if self.inode is not None else None,
            "require_inode_match": self.require_inode_match,
            "pre_len": self.pre_len,
            "pre_sha256": self.pre_sha256,
            "snapshot_filename": self.snapshot_filename,
            "post_min_len": self.post_min_len,
            "post_max_len": self.post_max_len,
            "planned_write_ranges": [list(r) for r in self.planned_write_ranges],
            "own_created_inode": (
                list(self.own_created_inode)
                if self.own_created_inode is not None
                else None
            ),
            "planned_new_len": self.planned_new_len,
            "planned_new_sha256": self.planned_new_sha256,
            "planned_temp_rel_paths": list(self.planned_temp_rel_paths),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CapturedFileRecord:
        try:
            role = data["role"]
            root_key = data["root_key"]
            rel_path = data["rel_path"]
            existed = data["existed"]
            inode_raw = data["inode"]
            require_inode_match = data["require_inode_match"]
            pre_len = data["pre_len"]
            pre_sha256 = data["pre_sha256"]
            snapshot_filename = data["snapshot_filename"]
            post_min_len = data["post_min_len"]
            post_max_len = data["post_max_len"]
            ranges_raw = data["planned_write_ranges"]
            own_inode_raw = data["own_created_inode"]
            planned_new_len = data["planned_new_len"]
            planned_new_sha256 = data["planned_new_sha256"]
            temps_raw = data["planned_temp_rel_paths"]
        except (KeyError, TypeError) as err:
            _raise_closed("corrupt_recovery_manifest", err)

        if (
            not isinstance(role, str)
            or not _SAFE_ROLE_RE.match(role)
            or not isinstance(root_key, str)
            or not isinstance(rel_path, str)
            or not isinstance(existed, bool)
            or not isinstance(require_inode_match, bool)
            or not isinstance(pre_len, int)
            or pre_len < 0
            or not isinstance(post_min_len, int)
            or post_min_len < 0
            or not isinstance(post_max_len, int)
            or post_max_len < post_min_len
            or not isinstance(ranges_raw, list)
            or not isinstance(temps_raw, list)
        ):
            raise RecoveryError(code="corrupt_recovery_manifest")

        inode: tuple[int, int] | None = None
        if inode_raw is not None:
            if (
                not isinstance(inode_raw, list)
                or len(inode_raw) != 2
                or not all(isinstance(x, int) for x in inode_raw)
            ):
                raise RecoveryError(code="corrupt_recovery_manifest")
            inode = (inode_raw[0], inode_raw[1])

        own_created_inode: tuple[int, int] | None = None
        if own_inode_raw is not None:
            if (
                not isinstance(own_inode_raw, list)
                or len(own_inode_raw) != 2
                or not all(isinstance(x, int) for x in own_inode_raw)
            ):
                raise RecoveryError(code="corrupt_recovery_manifest")
            own_created_inode = (own_inode_raw[0], own_inode_raw[1])

        if existed:
            if (
                inode is None
                or not isinstance(pre_sha256, str)
                or not isinstance(snapshot_filename, str)
            ):
                raise RecoveryError(code="corrupt_recovery_manifest")
        else:
            if pre_len != 0 or pre_sha256 is not None:
                raise RecoveryError(code="corrupt_recovery_manifest")
            if snapshot_filename is not None and not isinstance(snapshot_filename, str):
                raise RecoveryError(code="corrupt_recovery_manifest")

        if planned_new_len is not None and (
            not isinstance(planned_new_len, int) or planned_new_len < 0
        ):
            raise RecoveryError(code="corrupt_recovery_manifest")
        if planned_new_sha256 is not None and not isinstance(planned_new_sha256, str):
            raise RecoveryError(code="corrupt_recovery_manifest")

        ranges: list[tuple[int, int]] = []
        for item in ranges_raw:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not isinstance(item[0], int)
                or not isinstance(item[1], int)
                or item[0] < 0
                or item[1] < item[0]
            ):
                raise RecoveryError(code="corrupt_recovery_manifest")
            ranges.append((item[0], item[1]))

        temps: list[str] = []
        for item in temps_raw:
            if not isinstance(item, str):
                raise RecoveryError(code="corrupt_recovery_manifest")
            temps.append(item)

        return cls(
            role=role,
            root_key=root_key,
            rel_path=rel_path,
            existed=existed,
            inode=inode,
            require_inode_match=require_inode_match,
            pre_len=pre_len,
            pre_sha256=pre_sha256,
            snapshot_filename=snapshot_filename,
            post_min_len=post_min_len,
            post_max_len=post_max_len,
            planned_write_ranges=tuple(ranges),
            own_created_inode=own_created_inode,
            planned_new_len=planned_new_len,
            planned_new_sha256=planned_new_sha256,
            planned_temp_rel_paths=tuple(temps),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadyManifest:
    schema_version: int
    transaction_id: uuid.UUID
    operation: RecoveryOperationKind
    format: str
    canonical_key_sha256: str
    lock_inode: tuple[int, int]
    files: tuple[CapturedFileRecord, ...]
    metadata: Mapping[str, Any]
    manifest_sha256: str

    @property
    def artifact_id(self) -> str:
        return f"{self.transaction_id}.ready.json"

    def to_reference(self, physical_base: PhysicalBaseIdentity) -> RecoveryReference:
        return RecoveryReference(
            schema_version=self.schema_version,
            format=physical_base.format,
            physical_base=physical_base,
            transaction_id=self.transaction_id,
            operation=self.operation,
            artifact_id=self.artifact_id,
        )


def _compute_manifest_digest(payload_without_digest: Mapping[str, Any]) -> str:
    canonical_bytes = json.dumps(
        payload_without_digest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


class RecoveryStore:
    """Durable manifest, snapshot, and restore engine for a physical message base."""

    def __init__(
        self,
        *,
        physical_base: PhysicalBaseIdentity,
        recovery_root: str | PathLike[str],
        base_root: str | PathLike[str],
        extra_roots: Mapping[str, str | PathLike[str]] | None = None,
        retained_fds: Mapping[tuple[str, str], int] | None = None,
        io: IO | None = None,
    ) -> None:
        self._physical_base = physical_base
        self._io = io if io is not None else IO()
        roots: dict[str, str] = {"base": _resolve_registered_root(base_root)}
        if extra_roots is not None:
            for key, val in extra_roots.items():
                if key == "base":
                    raise ValueError("extra_roots cannot override 'base'")
                roots[key] = _resolve_registered_root(val)
        self._base_roots = roots
        self._recovery_root = _ensure_secure_recovery_root(
            recovery_root, self._base_roots
        )
        self._retained_fds: dict[tuple[int, int], int] = {}
        self._retained_by_path: dict[tuple[str, str], int] = {}
        if retained_fds is not None:
            for (root_key, rel_path), fd in retained_fds.items():
                self.register_retained_fd(rel_path, fd, root_key=root_key)
        self._binding_verified = False
        self._verify_existing_binding_on_open()

    @property
    def physical_base(self) -> PhysicalBaseIdentity:
        return self._physical_base

    @property
    def recovery_root(self) -> Path:
        return self._recovery_root

    @property
    def base_roots(self) -> Mapping[str, str]:
        return self._base_roots

    def register_retained_fd(
        self, rel_path: str, fd: int, *, root_key: str = "base"
    ) -> None:
        rel_path = _normalize_rel_path(rel_path)
        resolve_contained_path(self._base_roots, root_key, rel_path)
        try:
            st = os.fstat(fd)
        except OSError as err:
            _raise_closed("unsafe_recovery_path", err)
        inode = (st.st_dev, st.st_ino)
        self._retained_fds[inode] = fd
        self._retained_by_path[(root_key, rel_path)] = fd

    def _lookup_retained_fd(
        self,
        *,
        root_key: str,
        rel_path: str,
        inode: tuple[int, int] | None,
    ) -> int | None:
        if inode is not None:
            fd = self._retained_fds.get(inode)
            if fd is not None:
                return fd
        return self._retained_by_path.get((root_key, _normalize_rel_path(rel_path)))

    def _ensure_not_lock_inode(self, inode: tuple[int, int]) -> None:
        if inode == self._physical_base.lock_inode:
            raise RecoveryError(code="unexpected_base_modification")

    def _binding_path(self) -> Path:
        return self._recovery_root / BASE_BINDING_FILENAME

    def _expected_binding_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "format": self._physical_base.format,
            "canonical_key_sha256": canonical_key_sha256(
                self._physical_base.canonical_key
            ),
        }

    def _verify_existing_binding_on_open(self) -> None:
        binding_path = self._binding_path()
        try:
            st = os.lstat(binding_path)
        except FileNotFoundError:
            self._binding_verified = False
            return
        except OSError as err:
            _raise_closed("mismatched_recovery_root", err)

        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise RecoveryError(code="mismatched_recovery_root")

        try:
            raw = binding_path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except Exception as err:
            _raise_closed("mismatched_recovery_root", err)

        expected = self._expected_binding_payload()
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != expected["schema_version"]
            or data.get("format") != expected["format"]
            or data.get("canonical_key_sha256") != expected["canonical_key_sha256"]
        ):
            raise RecoveryError(code="mismatched_recovery_root")
        self._binding_verified = True

    def require_binding(self) -> None:
        if not self._binding_path().exists():
            self._binding_verified = False
            raise RecoveryError(code="missing_recovery_binding")
        if not self._binding_verified:
            self._verify_existing_binding_on_open()

    def _has_transaction_artifacts(self) -> bool:
        try:
            entries = os.listdir(self._recovery_root)
        except OSError as err:
            _raise_closed("missing_recovery_binding", err)
        for name in entries:
            if name in {BASE_BINDING_FILENAME, BASE_BINDING_TMP_FILENAME}:
                continue
            if (
                _READY_RE.match(name)
                or _PREPARING_RE.match(name)
                or _READY_TMP_RE.match(name)
                or _PREPARING_TMP_RE.match(name)
                or _SNAP_RE.match(name)
            ):
                return True
        return False

    def initialize_recovery_root(self, *, has_ready_journal_rows: bool) -> None:
        if not isinstance(has_ready_journal_rows, bool):
            raise ValueError("has_ready_journal_rows must be a bool")
        binding_path = self._binding_path()
        if binding_path.exists():
            self._verify_existing_binding_on_open()
            return
        if has_ready_journal_rows or self._has_transaction_artifacts():
            raise RecoveryError(code="missing_recovery_binding")

        payload = json.dumps(
            self._expected_binding_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        tmp_path = self._recovery_root / BASE_BINDING_TMP_FILENAME
        try:
            _write_secure_file(
                tmp_path,
                payload,
                io=self._io,
                error_code="missing_recovery_binding",
            )
            os.replace(tmp_path, binding_path)
            _fsync_dir(self._recovery_root)
        except RecoveryError:
            raise
        except OSError as err:
            _raise_closed("missing_recovery_binding", err)
        self._binding_verified = True

    def prepare(
        self,
        transaction_id: uuid.UUID,
        operation: RecoveryOperationKind,
        files: Sequence[FileMutationPlan],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ReadyManifest:
        self.require_binding()
        transaction_id = _require_uuidv4(transaction_id)
        tx_str = str(transaction_id)
        roles_seen: set[str] = set()
        owned_artifacts: list[str] = [f"{tx_str}.ready.json.tmp"]
        for plan in files:
            if plan.role in roles_seen:
                raise ValueError("Duplicate file role in recovery plan")
            roles_seen.add(plan.role)
            resolve_contained_path(self._base_roots, plan.root_key, plan.rel_path)
            for temp_rel in plan.planned_temp_rel_paths:
                resolve_contained_path(self._base_roots, plan.root_key, temp_rel)
            owned_artifacts.append(f"{tx_str}.Snap.{plan.role}")

        preparing_tmp = self._recovery_root / f"{tx_str}.preparing.json.tmp"
        preparing_path = self._recovery_root / f"{tx_str}.preparing.json"
        preparing_payload = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": tx_str,
            "operation": str(operation),
            "format": self._physical_base.format,
            "canonical_key_sha256": canonical_key_sha256(
                self._physical_base.canonical_key
            ),
            "lock_inode": list(self._physical_base.lock_inode),
            "owned_artifacts": owned_artifacts,
        }
        try:
            _write_secure_file(
                preparing_tmp,
                json.dumps(
                    preparing_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8"),
                io=self._io,
            )
            os.replace(preparing_tmp, preparing_path)
            _fsync_dir(self._recovery_root)
        except RecoveryError:
            raise
        except OSError as err:
            _raise_closed("corrupt_recovery_manifest", err)

        captured_records: list[CapturedFileRecord] = []
        for plan in files:
            target_path = resolve_contained_path(
                self._base_roots, plan.root_key, plan.rel_path
            )
            if plan.fd is not None:
                self.register_retained_fd(
                    plan.rel_path, plan.fd, root_key=plan.root_key
                )

            path_inode: tuple[int, int] | None = None
            path_st: os.stat_result | None
            try:
                path_st = os.lstat(target_path)
            except FileNotFoundError:
                path_st = None
            except OSError as err:
                _raise_closed("unsafe_recovery_path", err)
            if path_st is not None:
                if stat.S_ISLNK(path_st.st_mode) or not stat.S_ISREG(path_st.st_mode):
                    raise RecoveryError(code="unsafe_recovery_path")
                path_inode = (path_st.st_dev, path_st.st_ino)

            fd = self._lookup_retained_fd(
                root_key=plan.root_key, rel_path=plan.rel_path, inode=path_inode
            )
            if fd is None:
                fd = plan.fd

            inode: tuple[int, int] | None
            if fd is not None:
                try:
                    st = os.fstat(fd)
                except OSError as err:
                    _raise_closed("corrupt_recovery_manifest", err)
                existed = True
                raw_bytes = self._io.read(fd, 0, st.st_size)
                if len(raw_bytes) != st.st_size:
                    raise RecoveryError(code="corrupt_recovery_manifest")
                inode = (st.st_dev, st.st_ino)
                self._retained_fds[inode] = fd
            elif path_st is None or path_inode is None:
                existed = False
                raw_bytes = b""
                inode = None
            else:
                inode = path_inode
                self._ensure_not_lock_inode(inode)
                open_flags = (
                    os.O_RDONLY
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    temp_fd = os.open(target_path, open_flags)
                    try:
                        fst = os.fstat(temp_fd)
                        if (fst.st_dev, fst.st_ino) != inode:
                            raise RecoveryError(code="unexpected_base_modification")
                        raw_bytes = self._io.read(temp_fd, 0, fst.st_size)
                        if len(raw_bytes) != fst.st_size:
                            raise RecoveryError(code="corrupt_recovery_manifest")
                    finally:
                        os.close(temp_fd)
                except RecoveryError:
                    raise
                except OSError as err:
                    _raise_closed("corrupt_recovery_manifest", err)
                existed = True

            if existed:
                snap_name = f"{tx_str}.Snap.{plan.role}"
                snap_path = self._recovery_root / snap_name
                _write_secure_file(snap_path, raw_bytes, io=self._io)
                pre_len = len(raw_bytes)
                pre_sha256: str | None = hashlib.sha256(raw_bytes).hexdigest()
                snapshot_filename: str | None = snap_name
                default_max = max(
                    [pre_len, *(end for _, end in plan.planned_write_ranges)]
                )
                post_min_len = (
                    plan.post_min_len if plan.post_min_len is not None else pre_len
                )
                post_max_len = (
                    plan.post_max_len if plan.post_max_len is not None else default_max
                )
                planned_new_len: int | None = None
                planned_new_sha256: str | None = None
            else:
                pre_len = 0
                pre_sha256 = None
                if plan.planned_new_bytes is not None:
                    snap_name = f"{tx_str}.Snap.{plan.role}"
                    snap_path = self._recovery_root / snap_name
                    _write_secure_file(snap_path, plan.planned_new_bytes, io=self._io)
                    snapshot_filename = snap_name
                    planned_new_len = len(plan.planned_new_bytes)
                    planned_new_sha256 = hashlib.sha256(
                        plan.planned_new_bytes
                    ).hexdigest()
                    post_min_len = (
                        plan.post_min_len if plan.post_min_len is not None else 0
                    )
                    post_max_len = (
                        plan.post_max_len
                        if plan.post_max_len is not None
                        else planned_new_len
                    )
                else:
                    snapshot_filename = None
                    planned_new_len = None
                    planned_new_sha256 = None
                    post_min_len = (
                        plan.post_min_len if plan.post_min_len is not None else 0
                    )
                    post_max_len = (
                        plan.post_max_len
                        if plan.post_max_len is not None
                        else max([0, *(end for _, end in plan.planned_write_ranges)])
                    )

            captured_records.append(
                CapturedFileRecord(
                    role=plan.role,
                    root_key=plan.root_key,
                    rel_path=plan.rel_path,
                    existed=existed,
                    inode=inode,
                    require_inode_match=plan.require_inode_match,
                    pre_len=pre_len,
                    pre_sha256=pre_sha256,
                    snapshot_filename=snapshot_filename,
                    post_min_len=post_min_len,
                    post_max_len=post_max_len,
                    planned_write_ranges=plan.planned_write_ranges,
                    own_created_inode=plan.own_created_inode,
                    planned_new_len=planned_new_len,
                    planned_new_sha256=planned_new_sha256,
                    planned_temp_rel_paths=plan.planned_temp_rel_paths,
                )
            )

        meta_dict = dict(metadata) if metadata is not None else {}
        body_without_digest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": tx_str,
            "operation": str(operation),
            "format": self._physical_base.format,
            "canonical_key_sha256": canonical_key_sha256(
                self._physical_base.canonical_key
            ),
            "lock_inode": list(self._physical_base.lock_inode),
            "files": [rec.to_dict() for rec in captured_records],
            "metadata": meta_dict,
        }
        digest = _compute_manifest_digest(body_without_digest)
        ready_payload = {**body_without_digest, "manifest_sha256": digest}
        ready_tmp = self._recovery_root / f"{tx_str}.ready.json.tmp"
        ready_path = self._recovery_root / f"{tx_str}.ready.json"
        try:
            _write_secure_file(
                ready_tmp,
                json.dumps(ready_payload, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                ),
                io=self._io,
            )
            os.replace(ready_tmp, ready_path)
            _fsync_dir(self._recovery_root)
            try:
                os.unlink(preparing_path)
            except FileNotFoundError:
                pass
            _fsync_dir(self._recovery_root)
        except RecoveryError:
            raise
        except OSError as err:
            _raise_closed("corrupt_recovery_manifest", err)

        return ReadyManifest(
            schema_version=SCHEMA_VERSION,
            transaction_id=transaction_id,
            operation=operation,
            format=self._physical_base.format,
            canonical_key_sha256=body_without_digest["canonical_key_sha256"],
            lock_inode=self._physical_base.lock_inode,
            files=tuple(captured_records),
            metadata=meta_dict,
            manifest_sha256=digest,
        )

    def update_own_created_inode(
        self,
        transaction_id: uuid.UUID,
        role: str,
        own_created_inode: tuple[int, int],
    ) -> ReadyManifest:
        """Record an own-created temp/target inode in an existing READY manifest."""
        self.require_binding()
        manifest = self.load_ready_manifest(transaction_id)
        updated_files: list[CapturedFileRecord] = []
        found = False
        for rec in manifest.files:
            if rec.role == role:
                found = True
                updated_files.append(
                    CapturedFileRecord(
                        role=rec.role,
                        root_key=rec.root_key,
                        rel_path=rec.rel_path,
                        existed=rec.existed,
                        inode=rec.inode,
                        require_inode_match=rec.require_inode_match,
                        pre_len=rec.pre_len,
                        pre_sha256=rec.pre_sha256,
                        snapshot_filename=rec.snapshot_filename,
                        post_min_len=rec.post_min_len,
                        post_max_len=rec.post_max_len,
                        planned_write_ranges=rec.planned_write_ranges,
                        own_created_inode=own_created_inode,
                        planned_new_len=rec.planned_new_len,
                        planned_new_sha256=rec.planned_new_sha256,
                        planned_temp_rel_paths=rec.planned_temp_rel_paths,
                    )
                )
            else:
                updated_files.append(rec)
        if not found:
            raise KeyError(f"Unknown role {role!r}")

        tx_str = str(transaction_id)
        body_without_digest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": tx_str,
            "operation": str(manifest.operation),
            "format": manifest.format,
            "canonical_key_sha256": manifest.canonical_key_sha256,
            "lock_inode": list(manifest.lock_inode),
            "files": [rec.to_dict() for rec in updated_files],
            "metadata": dict(manifest.metadata),
        }
        digest = _compute_manifest_digest(body_without_digest)
        ready_payload = {**body_without_digest, "manifest_sha256": digest}
        ready_tmp = self._recovery_root / f"{tx_str}.ready.json.tmp"
        ready_path = self._recovery_root / f"{tx_str}.ready.json"
        try:
            _write_secure_file(
                ready_tmp,
                json.dumps(ready_payload, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                ),
                io=self._io,
            )
            os.replace(ready_tmp, ready_path)
            _fsync_dir(self._recovery_root)
        except RecoveryError:
            raise
        except OSError as err:
            _raise_closed("corrupt_recovery_manifest", err)
        return ReadyManifest(
            schema_version=SCHEMA_VERSION,
            transaction_id=transaction_id,
            operation=manifest.operation,
            format=manifest.format,
            canonical_key_sha256=manifest.canonical_key_sha256,
            lock_inode=manifest.lock_inode,
            files=tuple(updated_files),
            metadata=dict(manifest.metadata),
            manifest_sha256=digest,
        )

    def _delete_transaction_artifacts(
        self,
        tx_str: str,
        *,
        snap_names: Sequence[str] = (),
    ) -> None:
        manifest_names = (
            f"{tx_str}.ready.json",
            f"{tx_str}.preparing.json",
            f"{tx_str}.ready.json.tmp",
            f"{tx_str}.preparing.json.tmp",
        )
        unlinked_manifest = False
        for name in manifest_names:
            path = self._recovery_root / name
            try:
                os.unlink(path)
                unlinked_manifest = True
            except FileNotFoundError:
                pass
            except OSError as err:
                _raise_closed("corrupt_recovery_manifest", err)
        if unlinked_manifest:
            _fsync_dir(self._recovery_root)

        snap_set = set(snap_names)
        try:
            listed = os.listdir(self._recovery_root)
        except OSError as err:
            _raise_closed("corrupt_recovery_manifest", err)
        for entry in listed:
            m = _SNAP_RE.match(entry)
            if m and m.group(1) == tx_str:
                snap_set.add(entry)

        unlinked_snap = False
        for name in sorted(snap_set):
            path = self._recovery_root / name
            try:
                os.unlink(path)
                unlinked_snap = True
            except FileNotFoundError:
                pass
            except OSError as err:
                _raise_closed("corrupt_recovery_manifest", err)
        if unlinked_snap:
            _fsync_dir(self._recovery_root)

    def load_ready_manifest(self, transaction_id: uuid.UUID) -> ReadyManifest:
        tx_str = str(transaction_id)
        ready_path = self._recovery_root / f"{tx_str}.ready.json"
        try:
            st = os.lstat(ready_path)
        except OSError as err:
            _raise_closed("corrupt_recovery_manifest", err)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise RecoveryError(code="corrupt_recovery_manifest")

        try:
            raw = ready_path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except Exception as err:
            _raise_closed("corrupt_recovery_manifest", err)

        if not isinstance(data, dict):
            raise RecoveryError(code="corrupt_recovery_manifest")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise RecoveryError(code="corrupt_recovery_manifest")
        if data.get("transaction_id") != tx_str:
            raise RecoveryError(code="corrupt_recovery_manifest")

        expected_key_hash = canonical_key_sha256(self._physical_base.canonical_key)
        if (
            data.get("format") != self._physical_base.format
            or data.get("canonical_key_sha256") != expected_key_hash
        ):
            raise RecoveryError(code="corrupt_recovery_manifest")

        lock_inode_raw = data.get("lock_inode")
        if (
            not isinstance(lock_inode_raw, list)
            or len(lock_inode_raw) != 2
            or not all(isinstance(x, int) for x in lock_inode_raw)
        ):
            raise RecoveryError(code="corrupt_recovery_manifest")

        lock_inode = (lock_inode_raw[0], lock_inode_raw[1])
        if lock_inode != self._physical_base.lock_inode:
            raise RecoveryError(code="corrupt_recovery_manifest")

        op_raw = data.get("operation")
        if not isinstance(op_raw, str):
            raise RecoveryError(code="corrupt_recovery_manifest")
        try:
            operation = RecoveryOperationKind(op_raw)
        except ValueError as err:
            _raise_closed("corrupt_recovery_manifest", err)

        files_raw = data.get("files")
        metadata_raw = data.get("metadata")
        manifest_sha256 = data.get("manifest_sha256")
        if (
            not isinstance(files_raw, list)
            or not isinstance(metadata_raw, dict)
            or not isinstance(manifest_sha256, str)
        ):
            raise RecoveryError(code="corrupt_recovery_manifest")

        body_without_digest = {
            "schema_version": data["schema_version"],
            "transaction_id": data["transaction_id"],
            "operation": data["operation"],
            "format": data["format"],
            "canonical_key_sha256": data["canonical_key_sha256"],
            "lock_inode": data["lock_inode"],
            "files": data["files"],
            "metadata": data["metadata"],
        }
        if _compute_manifest_digest(body_without_digest) != manifest_sha256:
            raise RecoveryError(code="corrupt_recovery_manifest")

        records: list[CapturedFileRecord] = []
        for item in files_raw:
            if not isinstance(item, dict):
                raise RecoveryError(code="corrupt_recovery_manifest")
            rec = CapturedFileRecord.from_dict(item)
            resolve_contained_path(self._base_roots, rec.root_key, rec.rel_path)
            for temp_rel in rec.planned_temp_rel_paths:
                resolve_contained_path(self._base_roots, rec.root_key, temp_rel)

            if rec.snapshot_filename is not None:
                expected_snap = f"{tx_str}.Snap.{rec.role}"
                if rec.snapshot_filename != expected_snap:
                    raise RecoveryError(code="corrupt_recovery_manifest")
                snap_path = self._recovery_root / rec.snapshot_filename
                try:
                    snap_st = os.lstat(snap_path)
                    if stat.S_ISLNK(snap_st.st_mode) or not stat.S_ISREG(
                        snap_st.st_mode
                    ):
                        raise RecoveryError(code="corrupt_recovery_manifest")
                    snap_bytes = snap_path.read_bytes()
                except RecoveryError:
                    raise
                except OSError as err:
                    _raise_closed("corrupt_recovery_manifest", err)
                snap_digest = hashlib.sha256(snap_bytes).hexdigest()
                if rec.existed:
                    if len(snap_bytes) != rec.pre_len or snap_digest != rec.pre_sha256:
                        raise RecoveryError(code="corrupt_recovery_manifest")
                else:
                    if (
                        rec.planned_new_len != len(snap_bytes)
                        or rec.planned_new_sha256 != snap_digest
                    ):
                        raise RecoveryError(code="corrupt_recovery_manifest")
            records.append(rec)

        return ReadyManifest(
            schema_version=SCHEMA_VERSION,
            transaction_id=transaction_id,
            operation=operation,
            format=self._physical_base.format,
            canonical_key_sha256=expected_key_hash,
            lock_inode=lock_inode,
            files=tuple(records),
            metadata=metadata_raw,
            manifest_sha256=manifest_sha256,
        )

    def pending_manifests(self) -> tuple[ReadyManifest, ...]:
        self.require_binding()
        try:
            entries = sorted(os.listdir(self._recovery_root))
        except OSError as err:
            _raise_closed("corrupt_recovery_manifest", err)
        ready_txs: set[str] = set()
        preparing_txs: set[str] = set()
        tmp_txs: set[str] = set()
        snaps_by_tx: dict[str, list[str]] = {}

        for name in entries:
            full = self._recovery_root / name
            try:
                st = os.lstat(full)
            except OSError as err:
                _raise_closed("corrupt_recovery_manifest", err)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise RecoveryError(code="corrupt_recovery_manifest")

            if name in {BASE_BINDING_FILENAME, BASE_BINDING_TMP_FILENAME}:
                continue
            if m := _READY_RE.match(name):
                ready_txs.add(m.group(1))
                continue
            if m := _PREPARING_RE.match(name):
                preparing_txs.add(m.group(1))
                continue
            if m := _READY_TMP_RE.match(name):
                tmp_txs.add(m.group(1))
                continue
            if m := _PREPARING_TMP_RE.match(name):
                tmp_txs.add(m.group(1))
                continue
            if m := _SNAP_RE.match(name):
                snaps_by_tx.setdefault(m.group(1), []).append(name)
                continue
            raise RecoveryError(code="corrupt_recovery_manifest")

        incomplete_txs = (preparing_txs | tmp_txs) - ready_txs
        for tx_str in sorted(incomplete_txs):
            self._delete_transaction_artifacts(
                tx_str, snap_names=snaps_by_tx.get(tx_str, ())
            )

        manifests: list[ReadyManifest] = []
        for tx_str in sorted(ready_txs):
            tx_uuid = uuid.UUID(tx_str)
            manifest = self.load_ready_manifest(tx_uuid)
            coexisting_ToDelete = (
                f"{tx_str}.preparing.json",
                f"{tx_str}.preparing.json.tmp",
                f"{tx_str}.ready.json.tmp",
            )
            unlinked = False
            for leftover in coexisting_ToDelete:
                leftover_path = self._recovery_root / leftover
                try:
                    os.unlink(leftover_path)
                    unlinked = True
                except FileNotFoundError:
                    pass
                except OSError as err:
                    _raise_closed("corrupt_recovery_manifest", err)
            if unlinked:
                _fsync_dir(self._recovery_root)

            expected_snaps = {
                rec.snapshot_filename
                for rec in manifest.files
                if rec.snapshot_filename is not None
            }
            actual_snaps = set(snaps_by_tx.get(tx_str, ()))
            extra_snaps = actual_snaps - expected_snaps
            if extra_snaps:
                for extra in sorted(extra_snaps):
                    try:
                        os.unlink(self._recovery_root / extra)
                    except FileNotFoundError:
                        pass
                    except OSError as err:
                        _raise_closed("corrupt_recovery_manifest", err)
                _fsync_dir(self._recovery_root)

            manifests.append(manifest)

        orphan_snap_txs = set(snaps_by_tx.keys()) - ready_txs - incomplete_txs
        unlinked_orphan = False
        for tx_str in sorted(orphan_snap_txs):
            for snap_name in sorted(snaps_by_tx[tx_str]):
                try:
                    os.unlink(self._recovery_root / snap_name)
                    unlinked_orphan = True
                except FileNotFoundError:
                    pass
                except OSError as err:
                    _raise_closed("corrupt_recovery_manifest", err)
        if unlinked_orphan:
            _fsync_dir(self._recovery_root)

        return tuple(manifests)

    def pending(self) -> tuple[RecoveryReference, ...]:
        return tuple(
            m.to_reference(self._physical_base) for m in self.pending_manifests()
        )

    def _cleanup_planned_temps(
        self, manifest: ReadyManifest, touched_dirs: set[Path]
    ) -> None:
        for rec in manifest.files:
            for temp_rel in rec.planned_temp_rel_paths:
                temp_path = resolve_contained_path(
                    self._base_roots, rec.root_key, temp_rel
                )
                try:
                    st = os.lstat(temp_path)
                except FileNotFoundError:
                    continue
                except OSError as err:
                    _raise_closed("unsafe_recovery_path", err)
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    raise RecoveryError(code="unsafe_recovery_path")
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    continue
                except OSError as err:
                    _raise_closed("unsafe_recovery_path", err)
                touched_dirs.add(temp_path.parent)

    def commit_manifest(self, transaction_id: uuid.UUID) -> None:
        self.require_binding()
        manifest = self.load_ready_manifest(transaction_id)
        touched_dirs: set[Path] = set()
        self._cleanup_planned_temps(manifest, touched_dirs)
        for d in sorted(touched_dirs):
            _fsync_dir(d)
        self._delete_transaction_artifacts(
            str(transaction_id),
            snap_names=[
                rec.snapshot_filename
                for rec in manifest.files
                if rec.snapshot_filename is not None
            ],
        )

    def restore_uncommitted(self, transaction_id: uuid.UUID) -> None:
        self.require_binding()
        manifest = self.load_ready_manifest(transaction_id)

        validated_existing: list[
            tuple[CapturedFileRecord, Path, bytes, tuple[int, int]]
        ] = []
        validated_absent_to_unlink: list[tuple[Path, tuple[int, int]]] = []

        for rec in manifest.files:
            target_path = resolve_contained_path(
                self._base_roots, rec.root_key, rec.rel_path
            )
            for temp_rel in rec.planned_temp_rel_paths:
                temp_path = resolve_contained_path(
                    self._base_roots, rec.root_key, temp_rel
                )
                try:
                    temp_st = os.lstat(temp_path)
                except FileNotFoundError:
                    continue
                except OSError as err:
                    _raise_closed("unsafe_recovery_path", err)
                if stat.S_ISLNK(temp_st.st_mode) or not stat.S_ISREG(temp_st.st_mode):
                    raise RecoveryError(code="unsafe_recovery_path")

            if rec.existed:
                if rec.snapshot_filename is None:
                    raise RecoveryError(code="corrupt_recovery_manifest")
                try:
                    snap_bytes = (
                        self._recovery_root / rec.snapshot_filename
                    ).read_bytes()
                    path_st = os.lstat(target_path)
                except FileNotFoundError:
                    raise RecoveryError(code="unexpected_base_modification") from None
                except OSError as err:
                    _raise_closed("unexpected_base_modification", err)
                if stat.S_ISLNK(path_st.st_mode) or not stat.S_ISREG(path_st.st_mode):
                    raise RecoveryError(code="unexpected_base_modification")

                path_inode = (path_st.st_dev, path_st.st_ino)
                retained_fd = self._lookup_retained_fd(
                    root_key=rec.root_key, rel_path=rec.rel_path, inode=path_inode
                )
                if retained_fd is not None:
                    try:
                        st = os.fstat(retained_fd)
                    except OSError as err:
                        _raise_closed("unexpected_base_modification", err)
                    if path_inode != (st.st_dev, st.st_ino):
                        raise RecoveryError(code="unexpected_base_modification")
                    current_bytes = self._io.read(retained_fd, 0, st.st_size)
                else:
                    self._ensure_not_lock_inode(path_inode)
                    open_flags = (
                        os.O_RDONLY
                        | getattr(os, "O_BINARY", 0)
                        | getattr(os, "O_NOFOLLOW", 0)
                    )
                    try:
                        rfd = os.open(target_path, open_flags)
                        try:
                            fst = os.fstat(rfd)
                            if (fst.st_dev, fst.st_ino) != path_inode:
                                raise RecoveryError(code="unexpected_base_modification")
                            current_bytes = self._io.read(rfd, 0, fst.st_size)
                        finally:
                            os.close(rfd)
                    except RecoveryError:
                        raise
                    except OSError as err:
                        _raise_closed("unexpected_base_modification", err)
                    st = path_st

                if rec.require_inode_match and rec.inode != (st.st_dev, st.st_ino):
                    raise RecoveryError(code="unexpected_base_modification")

                min_allowed = min(rec.pre_len, rec.post_min_len)
                max_allowed = max(rec.pre_len, rec.post_max_len)
                cur_len = len(current_bytes)
                if cur_len < min_allowed or cur_len > max_allowed:
                    raise RecoveryError(code="unexpected_base_modification")

                if not _outside_ranges_match(
                    pre_bytes=snap_bytes,
                    current_bytes=current_bytes,
                    ranges=rec.planned_write_ranges,
                ):
                    raise RecoveryError(code="unexpected_base_modification")

                validated_existing.append((rec, target_path, snap_bytes, path_inode))
            else:
                try:
                    st = os.lstat(target_path)
                except FileNotFoundError:
                    continue
                except OSError as err:
                    _raise_closed("foreign_target_occupied", err)
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    raise RecoveryError(code="foreign_target_occupied")

                actual_inode = (st.st_dev, st.st_ino)
                inode_matched = (
                    rec.own_created_inode is not None
                    and actual_inode == rec.own_created_inode
                )
                bytes_matched = False
                if rec.own_created_inode is None and rec.snapshot_filename is not None:
                    try:
                        planned_bytes = (
                            self._recovery_root / rec.snapshot_filename
                        ).read_bytes()
                    except OSError as err:
                        _raise_closed("corrupt_recovery_manifest", err)
                    cur_bytes = self._read_path_bytes(target_path, actual_inode)
                    if len(cur_bytes) > 0 and planned_bytes.startswith(cur_bytes):
                        bytes_matched = True

                if rec.own_created_inode is not None and not inode_matched:
                    raise RecoveryError(code="foreign_target_occupied")
                if not inode_matched and not bytes_matched:
                    raise RecoveryError(code="foreign_target_occupied")

                validated_absent_to_unlink.append((target_path, actual_inode))

        touched_dirs: set[Path] = set()
        for rec, target_path, snap_bytes, path_inode in validated_existing:
            retained_fd = self._lookup_retained_fd(
                root_key=rec.root_key, rel_path=rec.rel_path, inode=path_inode
            )
            if retained_fd is not None:
                self._io.write(retained_fd, 0, snap_bytes)
                self._io.truncate(retained_fd, rec.pre_len)
                self._io.flush(retained_fd)
            else:
                self._ensure_not_lock_inode(path_inode)
                open_flags = (
                    os.O_RDWR
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    wfd = os.open(target_path, open_flags)
                    try:
                        self._io.write(wfd, 0, snap_bytes)
                        self._io.truncate(wfd, rec.pre_len)
                        self._io.flush(wfd)
                    finally:
                        os.close(wfd)
                except RecoveryError:
                    raise
                except OSError as err:
                    _raise_closed("unexpected_base_modification", err)
            touched_dirs.add(target_path.parent)

        for target_path, expected_inode in validated_absent_to_unlink:
            try:
                st = os.lstat(target_path)
            except FileNotFoundError:
                continue
            except OSError as err:
                _raise_closed("foreign_target_occupied", err)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise RecoveryError(code="foreign_target_occupied")
            if (st.st_dev, st.st_ino) != expected_inode:
                raise RecoveryError(code="foreign_target_occupied")
            try:
                os.unlink(target_path)
            except FileNotFoundError:
                continue
            except OSError as err:
                _raise_closed("foreign_target_occupied", err)
            touched_dirs.add(target_path.parent)

        self._cleanup_planned_temps(manifest, touched_dirs)
        for d in sorted(touched_dirs):
            _fsync_dir(d)

        self._delete_transaction_artifacts(
            str(transaction_id),
            snap_names=[
                rec.snapshot_filename
                for rec in manifest.files
                if rec.snapshot_filename is not None
            ],
        )

    def _read_path_bytes(self, target_path: Path, inode: tuple[int, int]) -> bytes:
        retained_fd = self._retained_fds.get(inode)
        if retained_fd is not None:
            try:
                st = os.fstat(retained_fd)
            except OSError as err:
                _raise_closed("foreign_target_occupied", err)
            if (st.st_dev, st.st_ino) != inode:
                raise RecoveryError(code="foreign_target_occupied")
            return self._io.read(retained_fd, 0, st.st_size)
        self._ensure_not_lock_inode(inode)
        open_flags = (
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            rfd = os.open(target_path, open_flags)
            try:
                fst = os.fstat(rfd)
                if (fst.st_dev, fst.st_ino) != inode:
                    raise RecoveryError(code="foreign_target_occupied")
                return self._io.read(rfd, 0, fst.st_size)
            finally:
                os.close(rfd)
        except RecoveryError:
            raise
        except OSError as err:
            _raise_closed("foreign_target_occupied", err)


def _outside_ranges_match(
    *,
    pre_bytes: bytes,
    current_bytes: bytes,
    ranges: Sequence[tuple[int, int]],
) -> bool:
    """Verify every byte outside planned [start, end) ranges equals pre_bytes."""
    pre_len = len(pre_bytes)
    cur_len = len(current_bytes)
    compare_len = min(pre_len, cur_len)

    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    if cur_len > pre_len:
        ext_start = pre_len
        ext_end = cur_len
        covered = False
        for r_start, r_end in merged:
            if r_start <= ext_start and r_end >= ext_end:
                covered = True
                break
        if not covered:
            pos = ext_start
            for r_start, r_end in merged:
                if r_end <= pos:
                    continue
                if r_start > pos:
                    return False
                pos = max(pos, r_end)
                if pos >= ext_end:
                    break
            if pos < ext_end:
                return False

    cursor = 0
    for r_start, r_end in merged:
        if r_start > cursor:
            seg_end = min(r_start, compare_len)
            if (
                seg_end > cursor
                and current_bytes[cursor:seg_end] != pre_bytes[cursor:seg_end]
            ):
                return False
        cursor = max(cursor, r_end)
        if cursor >= compare_len:
            break

    if cursor < compare_len:
        if current_bytes[cursor:compare_len] != pre_bytes[cursor:compare_len]:
            return False

    return True


@dataclass
class _ActiveMutation:
    mutation: PreparedMutation
    manifest: ReadyManifest
    apply_fn: Callable[[], WriteResult]
    applied: bool = False


class BaseRecoverableSession:
    """Reusable session state machine for format RecoverableWriterSession."""

    def __init__(
        self, store: RecoveryStore, *, session_id: uuid.UUID | None = None
    ) -> None:
        self._store = store
        self._session_id = session_id if session_id is not None else uuid.uuid4()
        self._poisoned = False
        self._closed = False
        self._active_assertion: OfflineRecoveryAssertion | None = None
        self._active_mutation: _ActiveMutation | None = None

    @property
    def session_id(self) -> uuid.UUID:
        return self._session_id

    @property
    def physical_base(self) -> PhysicalBaseIdentity:
        return self._store.physical_base

    @property
    def store(self) -> RecoveryStore:
        return self._store

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def poison(self) -> None:
        self._poisoned = True

    def check_usable(self) -> None:
        if self._closed or self._poisoned:
            raise RecoveryError(code="poisoned_recovery_session")

    def close(self) -> None:
        if self._active_mutation is not None:
            self._poisoned = True
            self._active_mutation = None
        self._closed = True

    def initialize_recovery_root(self, *, has_ready_journal_rows: bool) -> None:
        self.check_usable()
        if self._active_mutation is not None:
            raise RecoveryError(code="invalid_prepared_mutation")
        self._store.initialize_recovery_root(
            has_ready_journal_rows=has_ready_journal_rows
        )

    def pending(self) -> tuple[RecoveryReference, ...]:
        self.check_usable()
        if self._active_mutation is not None:
            raise RecoveryError(code="invalid_prepared_mutation")
        return self._store.pending()

    def issue_offline_assertion(
        self, *, confirmed_offline: bool = True
    ) -> OfflineRecoveryAssertion:
        self.check_usable()
        if self._active_mutation is not None:
            raise RecoveryError(code="invalid_prepared_mutation")
        refs = self._store.pending()
        assertion = OfflineRecoveryAssertion(
            session_id=self._session_id,
            physical_base=self._store.physical_base,
            transaction_ids=tuple(ref.transaction_id for ref in refs),
            confirmed_offline=confirmed_offline,
        )
        self._active_assertion = assertion
        return assertion

    def recover(
        self,
        assertion: OfflineRecoveryAssertion,
        resolve: Callable[[uuid.UUID], CommitState],
    ) -> tuple[RecoveryReference, ...]:
        self.check_usable()
        if self._active_mutation is not None:
            raise RecoveryError(code="invalid_prepared_mutation")
        self._store.require_binding()
        if (
            not isinstance(assertion, OfflineRecoveryAssertion)
            or self._active_assertion is None
            or assertion != self._active_assertion
            or assertion.session_id != self._session_id
            or assertion.physical_base != self._store.physical_base
        ):
            self._active_assertion = None
            raise RecoveryError(code="invalid_offline_assertion")

        self._active_assertion = None
        pending_refs = self._store.pending()
        current_tx_ids = tuple(ref.transaction_id for ref in pending_refs)
        if assertion.transaction_ids != current_tx_ids:
            raise RecoveryError(code="invalid_offline_assertion")

        if not pending_refs:
            return ()

        resolved: list[tuple[RecoveryReference, CommitState]] = []
        for ref in pending_refs:
            try:
                state = resolve(ref.transaction_id)
            except Exception:
                self._poisoned = True
                raise RecoveryError(code="unknown_commit_state") from None
            if state not in {CommitState.COMMITTED, CommitState.UNCOMMITTED}:
                self._poisoned = True
                raise RecoveryError(code="unknown_commit_state")
            resolved.append((ref, state))

        recovered: list[RecoveryReference] = []
        for ref, state in resolved:
            if state == CommitState.COMMITTED:
                self._store.commit_manifest(ref.transaction_id)
                recovered.append(ref)
            else:
                try:
                    self._store.restore_uncommitted(ref.transaction_id)
                except BaseException:
                    self._poisoned = True
                    raise
                recovered.append(ref)

        return tuple(recovered)

    def register_prepared_mutation(
        self,
        transaction_id: uuid.UUID,
        operation: RecoveryOperationKind,
        files: Sequence[FileMutationPlan],
        apply_fn: Callable[[], WriteResult],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> PreparedMutation:
        self.check_usable()
        if self._active_mutation is not None:
            self._poisoned = True
            raise RecoveryError(code="invalid_prepared_mutation")
        if self._store.pending():
            raise RecoveryError(code="invalid_prepared_mutation")

        manifest = self._store.prepare(
            transaction_id, operation, files, metadata=metadata
        )
        mutation = PreparedMutation(
            reference=manifest.to_reference(self._store.physical_base),
            session_id=self._session_id,
        )
        self._active_mutation = _ActiveMutation(
            mutation=mutation,
            manifest=manifest,
            apply_fn=apply_fn,
            applied=False,
        )
        return mutation

    def apply(self, mutation: PreparedMutation) -> WriteResult:
        self.check_usable()
        if (
            self._active_mutation is None
            or self._active_mutation.applied
            or mutation != self._active_mutation.mutation
            or mutation.session_id != self._session_id
            or mutation.reference.physical_base != self._store.physical_base
        ):
            self._poisoned = True
            raise RecoveryError(code="invalid_prepared_mutation")

        result = self._active_mutation.apply_fn()
        self._active_mutation.applied = True
        return result

    def settle(self, mutation: PreparedMutation, state: CommitState) -> None:
        self.check_usable()
        if (
            self._active_mutation is None
            or mutation != self._active_mutation.mutation
            or mutation.session_id != self._session_id
            or mutation.reference.physical_base != self._store.physical_base
        ):
            self._poisoned = True
            raise RecoveryError(code="invalid_prepared_mutation")

        tx_id = mutation.reference.transaction_id
        if state == CommitState.UNKNOWN:
            self._poisoned = True
            raise RecoveryError(code="unknown_commit_state")
        if state == CommitState.COMMITTED:
            if not self._active_mutation.applied:
                raise RecoveryError(code="invalid_prepared_mutation")
            self._store.commit_manifest(tx_id)
            self._active_mutation = None
            return
        if state == CommitState.UNCOMMITTED:
            try:
                self._store.restore_uncommitted(tx_id)
            except BaseException:
                self._poisoned = True
                raise
            self._active_mutation = None
            return

        self._poisoned = True
        raise RecoveryError(code="unknown_commit_state")
