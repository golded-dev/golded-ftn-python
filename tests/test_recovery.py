from __future__ import annotations

import json
import os
import pickle
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from golded_ftn import (
    CommitState,
    MessageIdentity,
    MessagePatch,
    OfflineRecoveryAssertion,
    OutgoingMessage,
    ParsedMessage,
    PhysicalBaseIdentity,
    PreparedMutation,
    RecoverableMessageBaseWriter,
    RecoverableWriterSession,
    RecoveryError,
    RecoveryOperationKind,
    RecoveryReference,
    RevisionToken,
    RollbackError,
    SessionMessage,
    WriteResult,
    WriterOptions,
)
from golded_ftn._recovery import (
    BASE_BINDING_FILENAME,
    BaseRecoverableSession,
    FileMutationPlan,
    RecoveryStore,
    _compute_manifest_digest,
    clear_hudson_scan_dir_registry,
    register_hudson_scan_dir,
    resolve_contained_path,
)
from golded_ftn._writer_io import IO, Transaction, raw_revision


def _make_base(
    tmp_path: Path, fmt: str = "jam"
) -> tuple[Path, Path, PhysicalBaseIdentity, int]:
    base_dir = tmp_path / "base"
    base_dir.mkdir(mode=0o755, exist_ok=True)
    recovery_root = tmp_path / "recovery"
    lock_file = base_dir / "base.lock"
    if not lock_file.exists():
        lock_file.write_bytes(b"LOCKHEADER")
    fd = os.open(lock_file, os.O_RDWR)
    st = os.fstat(fd)
    phys = PhysicalBaseIdentity(
        format=fmt,  # type: ignore[arg-type]
        canonical_key=os.path.realpath(lock_file),
        lock_inode=(st.st_dev, st.st_ino),
    )
    return base_dir, recovery_root, phys, fd


def test_rollback_error_sanitization(tmp_path: Path) -> None:
    secret_dir = tmp_path / "top_secret_dir_name"
    secret_dir.mkdir()
    target = secret_dir / "confidential.jhr"
    target.write_bytes(b"header")

    class FailingRollbackIO(IO):
        def write(self, fd: int, offset: int, data: bytes) -> None:
            raise OSError(f"disk failure at {target} with body 'TOP SECRET BODY'")

    fd = os.open(target, os.O_RDWR)
    try:
        with pytest.raises(RollbackError) as exc_info:
            with Transaction(FailingRollbackIO(), str(target), "update") as tx:
                tx.watch(fd)
                raise RuntimeError(f"failed writing 'PRIVATE MESSAGE' to {target}")
        err = exc_info.value
        assert str(err) == "Transaction rollback failed during update"
        assert "top_secret_dir_name" not in str(err)
        assert "top_secret_dir_name" not in repr(err)
        assert "PRIVATE MESSAGE" not in str(err)
        assert "PRIVATE MESSAGE" not in repr(err)
        assert "TOP SECRET BODY" not in str(err)
        assert "TOP SECRET BODY" not in repr(err)

        with pytest.raises(RollbackError) as empty_op_exc:
            with Transaction(FailingRollbackIO(), str(target), "") as tx:
                tx.watch(fd)
                raise RuntimeError("secret")
        assert str(empty_op_exc.value) == "Transaction rollback failed during rollback"
    finally:
        os.close(fd)


def test_privacy_of_repr_and_recovery_error() -> None:
    tx_id = uuid.uuid4()
    phys = PhysicalBaseIdentity(
        format="jam",
        canonical_key="/var/ftn/secret_path/area",
        lock_inode=(1, 2),
    )
    assert "secret_path" not in repr(phys)

    ref = RecoveryReference(
        schema_version=1,
        format="jam",
        physical_base=phys,
        transaction_id=tx_id,
        operation=RecoveryOperationKind.APPEND,
        artifact_id="/var/ftn/secret_artifact.ready.json",
    )
    assert "secret_path" not in repr(ref)
    assert "secret_artifact" not in repr(ref)

    err = RecoveryError(
        "leaked /var/ftn/secret_path and secret message body",
        code="unexpected_base_modification",
    )
    assert "secret_path" not in str(err)
    assert "secret_path" not in repr(err)
    assert "secret message body" not in str(err)
    assert "unexpected_base_modification" in str(err)
    assert err.code == "unexpected_base_modification"

    with pytest.raises(ValueError, match="confirmed_offline=True"):
        OfflineRecoveryAssertion(
            session_id=uuid.uuid4(),
            physical_base=phys,
            transaction_ids=[tx_id],  # type: ignore[arg-type]
            confirmed_offline=False,
        )


def test_base_binding_explicit_lifecycle(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        # Opening NEVER creates .base-binding.json implicitly
        assert not (recovery_root / BASE_BINDING_FILENAME).exists()

        # Calling pending, prepare, or recover before initialization fails closed
        with pytest.raises(RecoveryError) as exc_info:
            store.pending()
        assert exc_info.value.code == "missing_recovery_binding"

        with pytest.raises(RecoveryError) as exc_info:
            store.prepare(uuid.uuid4(), RecoveryOperationKind.APPEND, [])
        assert exc_info.value.code == "missing_recovery_binding"

        # If SQLite has READY rows while binding is absent, fail closed
        with pytest.raises(RecoveryError) as exc_info:
            store.initialize_recovery_root(has_ready_journal_rows=True)
        assert exc_info.value.code == "missing_recovery_binding"
        assert not (recovery_root / BASE_BINDING_FILENAME).exists()

        # Initialize when has_ready_journal_rows=False creates .base-binding.json
        store.initialize_recovery_root(has_ready_journal_rows=False)
        binding_file = recovery_root / BASE_BINDING_FILENAME
        assert binding_file.exists()
        assert store.pending() == ()

        # Re-opening with matching physical_base succeeds
        store2 = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
        )
        assert store2.pending() == ()

        # Re-opening with mismatched format or key raises mismatched_recovery_root
        wrong_phys = PhysicalBaseIdentity(
            format="squish",
            canonical_key=phys.canonical_key,
            lock_inode=phys.lock_inode,
        )
        with pytest.raises(RecoveryError) as exc_info:
            RecoveryStore(
                physical_base=wrong_phys,
                recovery_root=recovery_root,
                base_root=base_dir,
            )
        assert exc_info.value.code == "mismatched_recovery_root"

        wrong_key_phys = PhysicalBaseIdentity(
            format="jam",
            canonical_key=phys.canonical_key + "/other",
            lock_inode=phys.lock_inode,
        )
        with pytest.raises(RecoveryError) as exc_info:
            RecoveryStore(
                physical_base=wrong_key_phys,
                recovery_root=recovery_root,
                base_root=base_dir,
            )
        assert exc_info.value.code == "mismatched_recovery_root"
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_permissions_independent_of_umask(tmp_path: Path) -> None:
    old_umask = os.umask(0o000)
    try:
        base_dir, recovery_root, phys, fd = _make_base(tmp_path)
        try:
            store = RecoveryStore(
                physical_base=phys,
                recovery_root=recovery_root,
                base_root=base_dir,
                retained_fds={("base", "base.lock"): fd},
            )
            root_mode = stat.S_IMODE(os.lstat(recovery_root).st_mode)
            assert root_mode == 0o700

            store.initialize_recovery_root(has_ready_journal_rows=False)
            binding_mode = stat.S_IMODE(
                os.lstat(recovery_root / BASE_BINDING_FILENAME).st_mode
            )
            assert binding_mode == 0o600

            tx_id = uuid.uuid4()
            store.prepare(
                tx_id,
                RecoveryOperationKind.UPDATE,
                [
                    FileMutationPlan(
                        role="header",
                        rel_path="base.lock",
                        fd=fd,
                        planned_write_ranges=((0, 10),),
                    )
                ],
            )
            for child in recovery_root.iterdir():
                assert stat.S_IMODE(os.lstat(child).st_mode) == 0o600
        finally:
            os.close(fd)
    finally:
        os.umask(old_umask)


def test_path_containment_and_symlink_rejection(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    outside_file = tmp_path / "outside.dat"
    outside_file.write_bytes(b"outside")
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        for unsafe_rel in ("../outside.dat", "/abs/path", "sub/../../outside.dat", ""):
            with pytest.raises(RecoveryError) as exc_info:
                resolve_contained_path(store.base_roots, "base", unsafe_rel)
            assert exc_info.value.code == "unsafe_recovery_path"

        with pytest.raises(RecoveryError) as exc_info:
            resolve_contained_path(store.base_roots, "unregistered_root", "file.dat")
        assert exc_info.value.code == "unsafe_recovery_path"

        if hasattr(os, "symlink"):
            symlink_path = base_dir / "link.dat"
            os.symlink(outside_file, symlink_path)
            with pytest.raises(RecoveryError) as exc_info:
                resolve_contained_path(store.base_roots, "base", "link.dat")
            assert exc_info.value.code == "unsafe_recovery_path"
    finally:
        os.close(fd)


def test_preparing_cleanup_coexistence_and_orphan_snaps(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        # 1. Incomplete PREPARING without .ready.json + partial Snap + .ready.json.tmp
        tx_incomplete = uuid.uuid4()
        (recovery_root / f"{tx_incomplete}.preparing.json").write_text(
            "{}", encoding="utf-8"
        )
        (recovery_root / f"{tx_incomplete}.ready.json.tmp").write_text(
            "{}", encoding="utf-8"
        )
        (recovery_root / f"{tx_incomplete}.Snap.header").write_bytes(b"LOCKHEADER")

        # 2. Coexisting .ready.json and .preparing.json (crash before unlink)
        tx_ready = uuid.uuid4()
        store.prepare(
            tx_ready,
            RecoveryOperationKind.APPEND,
            [
                FileMutationPlan(
                    role="header",
                    rel_path="base.lock",
                    fd=fd,
                    planned_write_ranges=((0, 10),),
                )
            ],
        )
        # Re-create leftover .preparing.json for tx_ready
        (recovery_root / f"{tx_ready}.preparing.json").write_text(
            "{}", encoding="utf-8"
        )

        # 3. Orphan .Snap.* file with neither .ready.json nor .preparing.json
        tx_orphan = uuid.uuid4()
        (recovery_root / f"{tx_orphan}.Snap.orphan").write_bytes(b"orphan")

        refs = store.pending()
        assert len(refs) == 1
        assert refs[0].transaction_id == tx_ready

        # Verify cleanup results
        remaining = {p.name for p in recovery_root.iterdir()}
        assert remaining == {
            BASE_BINDING_FILENAME,
            f"{tx_ready}.ready.json",
            f"{tx_ready}.Snap.header",
        }
    finally:
        os.close(fd)


def test_corrupt_or_unexpected_manifest_fails_closed(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        unexpected = recovery_root / "unexpected.txt"
        unexpected.write_text("rogue", encoding="utf-8")
        with pytest.raises(RecoveryError) as exc_info:
            store.pending()
        assert exc_info.value.code == "corrupt_recovery_manifest"
        unexpected.unlink()

        tx_id = uuid.uuid4()
        store.prepare(
            tx_id,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="header",
                    rel_path="base.lock",
                    fd=fd,
                    planned_write_ranges=((0, 10),),
                )
            ],
        )
        snap_path = recovery_root / f"{tx_id}.Snap.header"
        snap_path.write_bytes(b"CORRUPTED!")
        with pytest.raises(RecoveryError) as exc_info:
            store.pending()
        assert exc_info.value.code == "corrupt_recovery_manifest"
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "mutation_kind",
    ["pre_image", "full_post_image", "torn_write", "zero_filled_extension"],
)
def test_uncommitted_restore_variants(tmp_path: Path, mutation_kind: str) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    data_file = base_dir / "data.bin"
    pre_bytes = b"0123456789ABCDEF"
    data_file.write_bytes(pre_bytes)
    data_fd = os.open(data_file, os.O_RDWR)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={
                ("base", "base.lock"): fd,
                ("base", "data.bin"): data_fd,
            },
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        tx_id = uuid.uuid4()
        temp_file = base_dir / f"{tx_id}.tmp"
        temp_file.write_bytes(b"temp_data")

        # Planned write updates bytes [4, 8) and appends [16, 24)
        store.prepare(
            tx_id,
            RecoveryOperationKind.APPEND,
            [
                FileMutationPlan(
                    role="data",
                    rel_path="data.bin",
                    fd=data_fd,
                    planned_write_ranges=((4, 8), (16, 24)),
                    post_min_len=16,
                    post_max_len=24,
                    planned_temp_rel_paths=(f"{tx_id}.tmp",),
                )
            ],
        )

        if mutation_kind == "pre_image":
            pass
        elif mutation_kind == "full_post_image":
            os.pwrite(data_fd, b"XXXX", 4)
            os.pwrite(data_fd, b"NEWBYTES", 16)
        elif mutation_kind == "torn_write":
            os.pwrite(data_fd, b"XX", 4)
            os.pwrite(data_fd, b"NEW", 16)
        elif mutation_kind == "zero_filled_extension":
            os.pwrite(data_fd, b"\x00" * 8, 16)

        store.restore_uncommitted(tx_id)
        assert data_file.read_bytes() == pre_bytes
        assert not temp_file.exists()
        assert store.pending() == ()
    finally:
        os.close(data_fd)
        os.close(fd)


def test_uncommitted_refuses_external_modification_outside_planned_ranges(
    tmp_path: Path,
) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    data_file = base_dir / "data.bin"
    pre_bytes = b"0123456789ABCDEF"
    data_file.write_bytes(pre_bytes)
    data_fd = os.open(data_file, os.O_RDWR)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={
                ("base", "base.lock"): fd,
                ("base", "data.bin"): data_fd,
            },
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        tx_id = uuid.uuid4()
        store.prepare(
            tx_id,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="data",
                    rel_path="data.bin",
                    fd=data_fd,
                    planned_write_ranges=((4, 8),),
                    post_min_len=16,
                    post_max_len=16,
                )
            ],
        )

        # Simulate external GoldED edit to byte 0 (outside [4, 8))
        modified = b"Z123XXXX89ABCDEF"
        os.pwrite(data_fd, modified, 0)

        with pytest.raises(RecoveryError) as exc_info:
            store.restore_uncommitted(tx_id)
        assert exc_info.value.code == "unexpected_base_modification"
        # Base file and artifacts MUST remain untouched on validation failure
        assert data_file.read_bytes() == modified
        assert len(store.pending()) == 1

        # Fix byte 0 back, now modify length beyond post_max_len
        os.pwrite(data_fd, pre_bytes, 0)
        os.pwrite(data_fd, b"EXTRA", 16)
        with pytest.raises(RecoveryError) as exc_info:
            store.restore_uncommitted(tx_id)
        assert exc_info.value.code == "unexpected_base_modification"
    finally:
        os.close(data_fd)
        os.close(fd)


def test_existed_false_foreign_target_occupied_and_own_created_unlink(
    tmp_path: Path,
) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path, fmt="msg")
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        tx_id = uuid.uuid4()
        planned_msg = b"OWN MESSAGE PAYLOAD"
        store.prepare(
            tx_id,
            RecoveryOperationKind.APPEND,
            [
                FileMutationPlan(
                    role="new_msg",
                    rel_path="2.msg",
                    require_inode_match=False,
                    planned_new_bytes=planned_msg,
                )
            ],
        )

        # Case 1: Foreign file occupies 2.msg with foreign bytes
        target_msg = base_dir / "2.msg"
        foreign_bytes = b"FOREIGN GOLDED MESSAGE"
        target_msg.write_bytes(foreign_bytes)

        with pytest.raises(RecoveryError) as exc_info:
            store.restore_uncommitted(tx_id)
        assert exc_info.value.code == "foreign_target_occupied"
        # Foreign file MUST NOT be unlinked
        assert target_msg.exists()
        assert target_msg.read_bytes() == foreign_bytes

        # Case 2: Recorded own_created_inode differs from foreign inode
        own_tmp = base_dir / f"{tx_id}.tmp"
        own_tmp.write_bytes(planned_msg)
        own_st = os.lstat(own_tmp)
        store.update_own_created_inode(tx_id, "new_msg", (own_st.st_dev, own_st.st_ino))
        target_msg.write_bytes(planned_msg)  # different inode from own_tmp!
        with pytest.raises(RecoveryError) as exc_info:
            store.restore_uncommitted(tx_id)
        assert exc_info.value.code == "foreign_target_occupied"
        assert target_msg.exists()

        # Case 3: Target is hardlinked/renamed from own_tmp (matching own_created_inode)
        target_msg.unlink()
        os.replace(own_tmp, target_msg)
        store.restore_uncommitted(tx_id)
        assert not target_msg.exists()
        assert store.pending() == ()
    finally:
        os.close(fd)


def test_session_lifecycle_assertions_unknown_poisoning_and_protocols(
    tmp_path: Path,
) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    data_file = base_dir / "base.jhr"
    data_file.write_bytes(b"INITIAL_JHR")
    jhr_fd = os.open(data_file, os.O_RDWR)

    class DummyRecoverableSession(BaseRecoverableSession):
        def read(self, msgno: int) -> SessionMessage:
            self.check_usable()
            ident = MessageIdentity(format="jam", base=str(base_dir), msgno=msgno)
            rev = raw_revision(ident, (0,), data_file.read_bytes())
            msg = ParsedMessage(
                msgno=msgno,
                from_name="A",
                to_name="B",
                subject="S",
                body_text="Body",
                attributes_raw=0,
            )
            return SessionMessage(message=msg, identity=ident, revision=rev)

        def prepare_append(
            self, transaction_id: uuid.UUID, message: OutgoingMessage
        ) -> PreparedMutation:
            new_bytes = b"INITIAL_JHR_APPENDED"

            def _apply() -> WriteResult:
                os.pwrite(jhr_fd, new_bytes, 0)
                os.fsync(jhr_fd)
                ident = MessageIdentity(format="jam", base=str(base_dir), msgno=1)
                return WriteResult(
                    identity=ident,
                    revision=raw_revision(ident, (0,), new_bytes),
                )

            return self.register_prepared_mutation(
                transaction_id,
                RecoveryOperationKind.APPEND,
                [
                    FileMutationPlan(
                        role="jhr",
                        rel_path="base.jhr",
                        fd=jhr_fd,
                        planned_write_ranges=((11, len(new_bytes)),),
                        post_min_len=11,
                        post_max_len=len(new_bytes),
                    )
                ],
                _apply,
            )

        def prepare_update(
            self,
            transaction_id: uuid.UUID,
            identity: MessageIdentity,
            patch: MessagePatch,
            expected_revision: RevisionToken,
        ) -> PreparedMutation:
            return self.prepare_append(
                transaction_id,
                OutgoingMessage(from_name="A", to_name="B", subject="U", body_text="B"),
            )

    class DummyWriter:
        @contextmanager
        def recovery_session(
            self,
            path: str | os.PathLike[str],
            *,
            recovery_root: str | os.PathLike[str],
            options: WriterOptions | None = None,
        ) -> Iterator[RecoverableWriterSession]:
            store = RecoveryStore(
                physical_base=phys,
                recovery_root=recovery_root,
                base_root=path,
                retained_fds={
                    ("base", "base.lock"): fd,
                    ("base", "base.jhr"): jhr_fd,
                },
            )
            sess = DummyRecoverableSession(store)
            try:
                yield sess
            finally:
                sess.close()

    writer: RecoverableMessageBaseWriter = DummyWriter()
    try:
        with writer.recovery_session(base_dir, recovery_root=recovery_root) as session:
            session.initialize_recovery_root(has_ready_journal_rows=False)

            # Empty pending assertion works once and rejects replay
            empty_assertion = session.issue_offline_assertion()
            assert (
                session.recover(empty_assertion, lambda _: CommitState.COMMITTED) == ()
            )
            with pytest.raises(RecoveryError) as exc_info:
                session.recover(empty_assertion, lambda _: CommitState.COMMITTED)
            assert exc_info.value.code == "invalid_offline_assertion"

            # Prepare + Apply + Settle UNCOMMITTED in live session restores pre-image
            tx1 = uuid.uuid4()
            mut1 = session.prepare_append(
                tx1,
                OutgoingMessage(
                    from_name="A", to_name="B", subject="S", body_text="Body"
                ),
            )
            session.apply(mut1)
            assert data_file.read_bytes() == b"INITIAL_JHR_APPENDED"
            session.settle(mut1, CommitState.UNCOMMITTED)
            assert data_file.read_bytes() == b"INITIAL_JHR"
            assert session.pending() == ()

            # Prepare + Apply + Settle COMMITTED keeps post-image and removes artifacts
            tx2 = uuid.uuid4()
            mut2 = session.prepare_append(
                tx2,
                OutgoingMessage(
                    from_name="A", to_name="B", subject="S", body_text="Body"
                ),
            )
            session.apply(mut2)
            session.settle(mut2, CommitState.COMMITTED)
            assert data_file.read_bytes() == b"INITIAL_JHR_APPENDED"
            assert session.pending() == ()

        # Reset file and simulate leaving recovery_session with unsettled mutation
        os.pwrite(jhr_fd, b"INITIAL_JHR", 0)
        os.ftruncate(jhr_fd, len(b"INITIAL_JHR"))
        tx3 = uuid.uuid4()
        with writer.recovery_session(base_dir, recovery_root=recovery_root) as session:
            mut3 = session.prepare_append(
                tx3,
                OutgoingMessage(
                    from_name="A", to_name="B", subject="S", body_text="Body"
                ),
            )
            session.apply(mut3)
            # Exit context without settling!

        # Artifacts remain on disk; new session sees pending tx3
        with writer.recovery_session(base_dir, recovery_root=recovery_root) as session:
            assert len(session.pending()) == 1
            assertion = session.issue_offline_assertion()

            # Wrong session_id assertion fails
            bad_assertion = OfflineRecoveryAssertion(
                session_id=uuid.uuid4(),
                physical_base=phys,
                transaction_ids=assertion.transaction_ids,
            )
            with pytest.raises(RecoveryError) as exc_info:
                session.recover(bad_assertion, lambda _: CommitState.UNCOMMITTED)
            assert exc_info.value.code == "invalid_offline_assertion"

            # Resolve to UNKNOWN -> poisons session and preserves artifacts
            assertion2 = session.issue_offline_assertion()
            with pytest.raises(RecoveryError) as exc_info:
                session.recover(assertion2, lambda _: CommitState.UNKNOWN)
            assert exc_info.value.code == "unknown_commit_state"

            # Session is now poisoned
            with pytest.raises(RecoveryError) as exc_info:
                session.pending()
            assert exc_info.value.code == "poisoned_recovery_session"

        # Artifacts are STILL preserved on disk; recover with UNCOMMITTED
        with writer.recovery_session(base_dir, recovery_root=recovery_root) as session:
            assert len(session.pending()) == 1
            assertion3 = session.issue_offline_assertion()
            recovered = session.recover(assertion3, lambda _: CommitState.UNCOMMITTED)
            assert len(recovered) == 1
            assert recovered[0].transaction_id == tx3
            assert data_file.read_bytes() == b"INITIAL_JHR"
            assert session.pending() == ()
    finally:
        os.close(jhr_fd)
        os.close(fd)


def test_hudson_scan_dir_registry(tmp_path: Path) -> None:
    clear_hudson_scan_dir_registry()
    scan_a = tmp_path / "scan_a"
    scan_b = tmp_path / "scan_b"
    scan_a.mkdir()
    scan_b.mkdir()
    key = "/var/hudson/msginfo.bbs"
    try:
        resolved = register_hudson_scan_dir(key, scan_a)
        assert resolved == os.path.realpath(scan_a)
        assert register_hudson_scan_dir(key, scan_a) == resolved
        with pytest.raises(RecoveryError) as exc_info:
            register_hudson_scan_dir(key, scan_b)
        assert exc_info.value.code == "conflicting_scan_dir"
    finally:
        clear_hudson_scan_dir_registry()


def test_artifact_deletion_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)
        tx_id = uuid.uuid4()
        store.prepare(
            tx_id,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="lock",
                    rel_path="base.lock",
                    fd=fd,
                    planned_write_ranges=((0, 10),),
                )
            ],
        )

        events: list[str] = []
        orig_unlink = os.unlink

        def tracked_unlink(path: str | os.PathLike[str]) -> None:
            events.append(f"unlink:{Path(path).name}")
            orig_unlink(path)

        import golded_ftn._recovery as rec_mod

        orig_fsync_dir = rec_mod._fsync_dir

        def tracked_fsync_dir(path: str | os.PathLike[str]) -> None:
            events.append(f"fsync:{Path(path).name}")
            orig_fsync_dir(path)

        monkeypatch.setattr(os, "unlink", tracked_unlink)
        monkeypatch.setattr(rec_mod, "_fsync_dir", tracked_fsync_dir)

        store.commit_manifest(tx_id)
        ready_unlink_idx = events.index(f"unlink:{tx_id}.ready.json")
        snap_unlink_idx = events.index(f"unlink:{tx_id}.Snap.lock")
        assert ready_unlink_idx < snap_unlink_idx
        # Ensure directory fsync occurred between ready.json unlink and Snap unlink
        between = events[ready_unlink_idx + 1 : snap_unlink_idx]
        assert f"fsync:{recovery_root.name}" in between
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "foreign_bytes",
    [b"", b"\x00" * 18, b"OWN MESSAGE\x00\x00\x00\x00\x00\x00\x00"],
)
def test_existed_false_empty_or_zero_filled_is_foreign(
    tmp_path: Path, foreign_bytes: bytes
) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path, fmt="msg")
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)

        tx_id = uuid.uuid4()
        planned_msg = b"OWN MESSAGE PAYLOAD"
        store.prepare(
            tx_id,
            RecoveryOperationKind.APPEND,
            [
                FileMutationPlan(
                    role="new_msg",
                    rel_path="2.msg",
                    require_inode_match=False,
                    planned_new_bytes=planned_msg,
                )
            ],
        )

        target_msg = base_dir / "2.msg"
        target_msg.write_bytes(foreign_bytes)
        with pytest.raises(RecoveryError) as exc_info:
            store.restore_uncommitted(tx_id)
        assert exc_info.value.code == "foreign_target_occupied"
        assert target_msg.exists()
        assert target_msg.read_bytes() == foreign_bytes
        assert len(store.pending()) == 1
    finally:
        os.close(fd)


def test_failed_apply_rejects_committed_settle(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)
        session = BaseRecoverableSession(store)

        def boom() -> WriteResult:
            raise RuntimeError("apply failed")

        tx_id = uuid.uuid4()
        mutation = session.register_prepared_mutation(
            tx_id,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="header",
                    rel_path="base.lock",
                    fd=fd,
                    planned_write_ranges=((0, 10),),
                )
            ],
            boom,
        )
        with pytest.raises(RuntimeError, match="apply failed"):
            session.apply(mutation)
        with pytest.raises(RecoveryError) as exc_info:
            session.settle(mutation, CommitState.COMMITTED)
        assert exc_info.value.code == "invalid_prepared_mutation"
        assert not session.poisoned
        session.settle(mutation, CommitState.UNCOMMITTED)
        assert session.pending() == ()
    finally:
        os.close(fd)


def test_recover_resolves_all_before_acting(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    file_a = base_dir / "a.bin"
    file_b = base_dir / "b.bin"
    file_a.write_bytes(b"AAAA")
    file_b.write_bytes(b"BBBB")
    fd_a = os.open(file_a, os.O_RDWR)
    fd_b = os.open(file_b, os.O_RDWR)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={
                ("base", "base.lock"): fd,
                ("base", "a.bin"): fd_a,
                ("base", "b.bin"): fd_b,
            },
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)
        tx1 = uuid.uuid4()
        tx2 = uuid.uuid4()
        store.prepare(
            tx1,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="a",
                    rel_path="a.bin",
                    fd=fd_a,
                    planned_write_ranges=((0, 4),),
                )
            ],
        )
        store.prepare(
            tx2,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="b",
                    rel_path="b.bin",
                    fd=fd_b,
                    planned_write_ranges=((0, 4),),
                )
            ],
        )
        os.pwrite(fd_a, b"XXXX", 0)
        os.pwrite(fd_b, b"YYYY", 0)

        session = BaseRecoverableSession(store)
        assertion = session.issue_offline_assertion()
        resolved: list[uuid.UUID] = []

        def resolve(tx_id: uuid.UUID) -> CommitState:
            resolved.append(tx_id)
            if len(resolved) == 1:
                return CommitState.COMMITTED
            return CommitState.UNKNOWN

        with pytest.raises(RecoveryError) as exc_info:
            session.recover(assertion, resolve)
        assert exc_info.value.code == "unknown_commit_state"
        assert session.poisoned
        assert set(resolved) == {tx1, tx2}
        remaining = {p.name for p in recovery_root.iterdir()}
        assert f"{tx1}.ready.json" in remaining
        assert f"{tx2}.ready.json" in remaining
        assert file_a.read_bytes() == b"XXXX"
        assert file_b.read_bytes() == b"YYYY"

        store2 = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={
                ("base", "base.lock"): fd,
                ("base", "a.bin"): fd_a,
                ("base", "b.bin"): fd_b,
            },
        )
        session2 = BaseRecoverableSession(store2)
        assertion2 = session2.issue_offline_assertion()

        def exploding_resolve(_tx_id: uuid.UUID) -> CommitState:
            raise RuntimeError("sqlite connection failed")

        with pytest.raises(RecoveryError) as exc_info:
            session2.recover(assertion2, exploding_resolve)
        assert exc_info.value.code == "unknown_commit_state"
        assert session2.poisoned
        remaining = {p.name for p in recovery_root.iterdir()}
        assert f"{tx1}.ready.json" in remaining
        assert f"{tx2}.ready.json" in remaining
    finally:
        os.close(fd_a)
        os.close(fd_b)
        os.close(fd)


def test_manifest_lock_inode_mismatch(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)
        tx_id = uuid.uuid4()
        store.prepare(
            tx_id,
            RecoveryOperationKind.UPDATE,
            [
                FileMutationPlan(
                    role="header",
                    rel_path="base.lock",
                    fd=fd,
                    planned_write_ranges=((0, 10),),
                )
            ],
        )
        ready_path = recovery_root / f"{tx_id}.ready.json"
        data = json.loads(ready_path.read_text(encoding="utf-8"))
        data["lock_inode"] = [phys.lock_inode[0] + 1, phys.lock_inode[1] + 1]
        body = {key: value for key, value in data.items() if key != "manifest_sha256"}
        data["manifest_sha256"] = _compute_manifest_digest(body)
        ready_path.write_text(
            json.dumps(data, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with pytest.raises(RecoveryError) as exc_info:
            store.load_ready_manifest(tx_id)
        assert exc_info.value.code == "corrupt_recovery_manifest"
    finally:
        os.close(fd)


def test_prepare_rejects_non_uuidv4(tmp_path: Path) -> None:
    base_dir, recovery_root, phys, fd = _make_base(tmp_path)
    try:
        store = RecoveryStore(
            physical_base=phys,
            recovery_root=recovery_root,
            base_root=base_dir,
            retained_fds={("base", "base.lock"): fd},
        )
        store.initialize_recovery_root(has_ready_journal_rows=False)
        with pytest.raises(RecoveryError) as exc_info:
            store.prepare(
                uuid.uuid1(),
                RecoveryOperationKind.APPEND,
                [],
            )
        assert exc_info.value.code == "unsafe_recovery_path"
        with pytest.raises(RecoveryError) as exc_info:
            store.prepare(
                "../x",  # type: ignore[arg-type]
                RecoveryOperationKind.APPEND,
                [],
            )
        assert exc_info.value.code == "unsafe_recovery_path"
        assert not any(recovery_root.glob("..*"))
        assert list(recovery_root.iterdir()) == [recovery_root / BASE_BINDING_FILENAME]
    finally:
        os.close(fd)


def test_nested_recovery_root_inside_base_is_rejected(tmp_path: Path) -> None:
    base_dir, _recovery_root, phys, fd = _make_base(tmp_path)
    nested = base_dir / "nested-recovery"
    try:
        with pytest.raises(RecoveryError) as exc_info:
            RecoveryStore(
                physical_base=phys,
                recovery_root=nested,
                base_root=base_dir,
            )
        assert exc_info.value.code == "unsafe_recovery_path"
        assert not nested.exists()
    finally:
        os.close(fd)


def test_recovery_error_pickle_round_trip() -> None:
    err = RecoveryError(code="foreign_target_occupied")
    restored = pickle.loads(pickle.dumps(err))
    assert isinstance(restored, RecoveryError)
    assert restored.code == "foreign_target_occupied"
    assert str(restored) == str(err)
