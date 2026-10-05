from collections.abc import Iterable
from contextlib import AbstractContextManager
from os import PathLike
from typing import Protocol

from .models import (
    MessageIdentity,
    MessagePatch,
    MessageSource,
    OutgoingMessage,
    ParsedMessage,
    ReaderOptions,
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
