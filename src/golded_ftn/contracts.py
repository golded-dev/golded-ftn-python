from collections.abc import Iterable
from os import PathLike
from typing import Protocol

from .models import (
    MessageSource,
    OutgoingMessage,
    ParsedMessage,
    ReaderOptions,
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
