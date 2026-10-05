from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from golded_ftn import (
    UNSET,
    ControlLine,
    LockTimeoutError,
    MessageIdentity,
    MessagePatch,
    RollbackError,
    WriterOptions,
)
from golded_ftn._writer_io import IO, Transaction, locks, raw_revision, strict_encode


def test_patch_distinguishes_omitted_and_clear() -> None:
    patch = MessagePatch(external_id=None)
    assert patch.external_id is None
    assert patch.subject is UNSET


def test_revision_covers_bytes_and_location() -> None:
    identity = MessageIdentity(format="jam", base="/base", msgno=1)
    revision = raw_revision(identity, (42,), b"header", b"text")
    assert revision != raw_revision(identity, (43,), b"header", b"text")
    assert revision != raw_revision(identity, (42,), b"header", b"changed")


def test_strict_encoding() -> None:
    with pytest.raises(UnicodeEncodeError):
        strict_encode("😀", WriterOptions())
    with pytest.raises(ValueError, match="conflicts"):
        strict_encode(
            "text",
            WriterOptions(),
            (ControlLine(name="CHRS", value="UTF-8 4", raw=""),),
        )
    assert strict_encode("æ", WriterOptions()) == b"\x91"


def test_transaction_restores_bytes_size_and_prior_operation(tmp_path: Path) -> None:
    path = tmp_path / "base"
    path.write_bytes(b"original")
    io = IO()
    fd = os.open(path, os.O_RDWR)
    try:
        with Transaction(io, str(path), "first") as transaction:
            transaction.watch(fd)
            io.write(fd, 0, b"committed")
        with pytest.raises(ValueError):
            with Transaction(io, str(path), "second") as transaction:
                transaction.watch(fd)
                io.write(fd, 0, b"broken and longer")
                raise ValueError("injected")
        assert io.read(fd, 0, 100) == b"committed"
    finally:
        os.close(fd)


def test_failed_rollback_reports_context(tmp_path: Path) -> None:
    class BrokenIO(IO):
        def write(self, fd: int, offset: int, data: bytes) -> None:
            raise OSError("injected rollback failure")

    path = tmp_path / "base"
    path.write_bytes(b"original")
    fd = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(RollbackError, match="append.*rollback failed"):
            with Transaction(BrokenIO(), str(path), "append") as transaction:
                transaction.watch(fd)
                raise ValueError("original failure")
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX record locks")
def test_same_process_lock_timeout_uses_controlled_holder(tmp_path: Path) -> None:
    path = tmp_path / "base"
    path.write_bytes(b"base")
    ready = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with locks.acquire(path):
            ready.set()
            assert release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    assert ready.wait(5)
    try:
        with pytest.raises(LockTimeoutError):
            with locks.acquire(path, timeout=0.02):
                pytest.fail("acquired occupied lock")
    finally:
        release.set()
        thread.join(5)
    with locks.acquire(path) as first:
        pass
    with locks.acquire(path) as second:
        assert first == second


def test_unlock_failure_releases_process_mutex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from golded_ftn import _writer_io

    manager = _writer_io.LockManager()
    path = tmp_path / "lock"
    path.touch()
    original = _writer_io._lock

    def failing_unlock(fd: int, offset: int, *, unlock: bool) -> None:
        original(fd, offset, unlock=unlock)
        if unlock:
            raise OSError("injected unlock failure")

    monkeypatch.setattr(_writer_io, "_lock", failing_unlock)
    with pytest.raises(OSError, match="injected unlock"):
        with manager.acquire(path, timeout=0):
            pass
    monkeypatch.setattr(_writer_io, "_lock", original)
    with manager.acquire(path, timeout=0):
        pass
