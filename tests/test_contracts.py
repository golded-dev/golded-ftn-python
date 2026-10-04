from collections.abc import Iterable
from os import PathLike, fspath
from pathlib import Path

from golded_ftn import (
    MessageBaseReader,
    MessageSource,
    MessageSourceCatalog,
    MessageSourceLocator,
    MessageWriter,
    OutgoingMessage,
    ParsedMessage,
    ReaderOptions,
    WriterOptions,
)


class Catalog:
    def sources(
        self, path: str | PathLike[str], options: ReaderOptions | None = None
    ) -> Iterable[MessageSource]:
        yield MessageSource(
            source_type="fake",
            path=fspath(Path(path) / "general"),
            code="GENERAL",
            name="General",
            sort_order=10,
            meta_key="fake:general",
        )


class Reader:
    def read(
        self, path: str | PathLike[str], options: ReaderOptions | None = None
    ) -> Iterable[ParsedMessage]:
        yield ParsedMessage(
            msgno=1,
            from_name="Sysop",
            to_name="All",
            subject="Hello",
            body_text="Message body",
            attributes_raw=0,
            external_id="fake:1",
            area_code="GENERAL",
            area_name="General",
        )


class Writer:
    def write(
        self,
        path: str | PathLike[str],
        messages: Iterable[OutgoingMessage],
        options: WriterOptions | None = None,
    ) -> int:
        return sum(1 for _ in messages)


class Locator:
    def find(self, path: str | PathLike[str]) -> str | None:
        return fspath(path) if fspath(path) else None


def test_consumers() -> None:
    catalog: MessageSourceCatalog = Catalog()
    reader: MessageBaseReader = Reader()
    writer: MessageWriter = Writer()
    locator: MessageSourceLocator = Locator()
    (source,) = catalog.sources(Path("/bbs/messages"))
    (message,) = reader.read(source.path)
    assert source.code == "GENERAL" and message.subject == "Hello"
    assert Path(source.path) == Path("/bbs/messages") / "general"
    assert (
        writer.write(
            Path("/bbs/out"),
            iter(
                [
                    OutgoingMessage(
                        from_name="Alice",
                        to_name="Bob",
                        subject="Ping",
                        body_text="Hello",
                    )
                ]
            ),
        )
        == 1
    )
    assert locator.find(Path("/bbs")) == fspath(Path("/bbs"))
    assert locator.find("") is None
