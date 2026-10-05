"""Internal mutation primitives shared by concrete format packages."""

from __future__ import annotations

import codecs
import errno
import hashlib
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from os import PathLike
from types import TracebackType
from typing import Literal

from .charset import _resolve_charset
from .models import (
    ControlLine,
    LockTimeoutError,
    MessageIdentity,
    RevisionToken,
    RollbackError,
    WriterOptions,
)


@dataclass
class _Entry:
    fd: int
    mutex: threading.Lock = field(default_factory=threading.Lock)


class LockManager:
    """Retain one descriptor per inode; never close it during another operation.

    Descriptors intentionally live until process exit: closing *any* descriptor for
    an inode drops that process's POSIX record locks. Callers must use the yielded
    descriptor for every access to the lock file, and must not open it separately.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries: dict[tuple[int, int], _Entry] = {}
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=self._after_fork)

    def _after_fork(self) -> None:
        for entry in self._entries.values():
            os.close(entry.fd)
        self._entries = {}
        self._guard = threading.Lock()

    def ensure_file(self, path: str | PathLike[str]) -> None:
        """Bootstrap a sidecar before any thread can obtain its record lock."""
        with self._guard:
            try:
                fd = os.open(
                    path,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            except FileExistsError:
                return
            os.close(fd)

    @contextmanager
    def acquire(
        self, path: str | PathLike[str], offset: int = 0, timeout: float = 5.0
    ) -> Iterator[int]:

        deadline = time.monotonic() + timeout
        with self._guard:
            stat = os.stat(path)
            key = stat.st_dev, stat.st_ino
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry(os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0)))
                self._entries[key] = entry
        if not entry.mutex.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise LockTimeoutError(f"Timed out locking {os.fspath(path)}")
        locked = False
        try:
            while True:
                try:
                    _lock(entry.fd, offset, unlock=False)
                    locked = True
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LockTimeoutError(
                            f"Timed out locking {os.fspath(path)}"
                        ) from None
                    time.sleep(min(0.01, remaining))
            yield entry.fd
        finally:
            try:
                if locked:
                    _lock(entry.fd, offset, unlock=True)
            finally:
                entry.mutex.release()


def _lock(fd: int, offset: int, *, unlock: bool) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, offset, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if not unlock and error.errno in {13, 36}:
                raise BlockingIOError(errno.EACCES, "Occupied record lock") from error
            raise
    else:
        import fcntl

        mode = fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.lockf(fd, mode, 1, offset)


locks = LockManager()


class IO:
    """Override methods in tests to inject failures at mutation boundaries."""

    def read(self, fd: int, offset: int, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            if sys.platform == "win32":
                os.lseek(fd, offset, os.SEEK_SET)
                chunk = os.read(fd, remaining)
            else:
                chunk = os.pread(fd, remaining, offset)
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def write(self, fd: int, offset: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            if sys.platform == "win32":
                os.lseek(fd, offset, os.SEEK_SET)
                written = os.write(fd, view)
            else:
                written = os.pwrite(fd, view, offset)
            if written <= 0:
                raise OSError("write made no progress")
            offset += written
            view = view[written:]

    def truncate(self, fd: int, size: int) -> None:
        os.ftruncate(fd, size)

    def flush(self, fd: int) -> None:
        os.fsync(fd)


class Transaction:
    """Restore watched files in place if one operation fails.

    Full-file snapshots deliberately favor straightforward correctness over speed.
    The caller holds the base lock throughout this context and must poison its
    session when RollbackError escapes. This does not promise crash recovery.
    """

    def __init__(self, io: IO, base: str, operation: str) -> None:
        self.io, self.base, self.operation = io, base, operation
        self._original: dict[int, bytes] = {}

    def watch(self, fd: int) -> None:
        if fd not in self._original:
            size = os.fstat(fd).st_size
            raw = self.io.read(fd, 0, size)
            if len(raw) != size:
                raise OSError("Short snapshot read")
            self._original[fd] = raw

    def __enter__(self) -> Transaction:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exc is None:
            try:
                for fd in self._original:
                    self.io.flush(fd)
            except BaseException as failure:
                self._rollback(failure)
                raise
        else:
            self._rollback(exc)
        return False

    def _rollback(self, original: BaseException) -> None:
        try:
            for fd, raw in self._original.items():
                self.io.write(fd, 0, raw)
                self.io.truncate(fd, len(raw))
                self.io.flush(fd)
        except BaseException as failure:
            raise RollbackError(
                f"{self.base}: {self.operation} failed ({original}); "
                f"rollback failed ({failure})"
            ) from failure


def strict_encode(
    text: str, options: WriterOptions, controls: tuple[ControlLine, ...] = ()
) -> bytes:
    charset = codecs.lookup(_resolve_charset(options.target_charset)).name
    for control in controls:
        if control.name.upper() in {"CHRS", "CHARSET"}:
            declared = control.value.split()[0] if control.value.split() else ""
            if codecs.lookup(_resolve_charset(declared)).name != charset:
                raise ValueError("Charset declaration conflicts with WriterOptions")
    return text.encode(charset, errors="strict")


def raw_revision(
    identity: MessageIdentity, location: tuple[int, ...], *chunks: bytes
) -> RevisionToken:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return RevisionToken(
        identity=identity, location=location, digest=digest.hexdigest()
    )
