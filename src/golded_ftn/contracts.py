from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from os import PathLike
from typing import Protocol
from uuid import UUID

from .models import (
    CommitState,
    MessageIdentity,
    MessagePatch,
    MessageSource,
    OfflineRecoveryAssertion,
    OutgoingMessage,
    ParsedMessage,
    PhysicalBaseIdentity,
    PreparedMutation,
    ReaderOptions,
    RecoveryReference,
    RevisionToken,
    SessionMessage,
    WriteResult,
    WriterOptions,
)


class MessageBaseReader(Protocol):
    def read(
        self, path: str | PathLike[str], options: ReaderOptions | None = None
    ) -> Iterable[ParsedMessage]: ...


class MessageWriter(Protocol):
    def write(
        self,
        path: str | PathLike[str],
        messages: Iterable[OutgoingMessage],
        options: WriterOptions | None = None,
    ) -> int: ...


class MessageSourceCatalog(Protocol):
    def sources(
        self, path: str | PathLike[str], options: ReaderOptions | None = None
    ) -> Iterable[MessageSource]: ...


class MessageSourceLocator(Protocol):
    def find(self, path: str | PathLike[str]) -> str | None: ...


class MessageWriterSession(Protocol):
    def read(self, msgno: int) -> SessionMessage: ...
    def append(self, message: OutgoingMessage) -> WriteResult: ...
    def update(
        self,
        identity: MessageIdentity,
        patch: MessagePatch,
        expected_revision: RevisionToken,
    ) -> WriteResult: ...
    def delete(
        self, identity: MessageIdentity, expected_revision: RevisionToken
    ) -> MessageIdentity: ...


class MessageBaseWriter(Protocol):
    def create(self, path: str | PathLike[str]) -> None: ...
    def open(
        self, path: str | PathLike[str], options: WriterOptions | None = None
    ) -> AbstractContextManager[MessageWriterSession]: ...


class RecoverableWriterSession(Protocol):
    @property
    def session_id(self) -> UUID: ...

    @property
    def physical_base(self) -> PhysicalBaseIdentity: ...

    def read(self, msgno: int) -> SessionMessage: ...

    def initialize_recovery_root(self, *, has_ready_journal_rows: bool) -> None: ...

    def pending(self) -> tuple[RecoveryReference, ...]: ...

    def issue_offline_assertion(
        self, *, confirmed_offline: bool = True
    ) -> OfflineRecoveryAssertion: ...

    def recover(
        self,
        assertion: OfflineRecoveryAssertion,
        resolve: Callable[[UUID], CommitState],
    ) -> tuple[RecoveryReference, ...]: ...

    def prepare_append(
        self,
        transaction_id: UUID,
        message: OutgoingMessage,
    ) -> PreparedMutation: ...

    def prepare_update(
        self,
        transaction_id: UUID,
        identity: MessageIdentity,
        patch: MessagePatch,
        expected_revision: RevisionToken,
    ) -> PreparedMutation: ...

    def apply(self, mutation: PreparedMutation) -> WriteResult: ...

    def settle(
        self,
        mutation: PreparedMutation,
        state: CommitState,
    ) -> None: ...


class RecoverableMessageBaseWriter(Protocol):
    def recovery_session(
        self,
        path: str | PathLike[str],
        *,
        recovery_root: str | PathLike[str],
        options: WriterOptions | None = None,
    ) -> AbstractContextManager[RecoverableWriterSession]: ...
