# PHP API mapping

All top-level PHP value names are exported from `golded_ftn`: `ControlLine`,
`FtnAddress`, `MessageControlLines`, `MessageProvenance`, `MessageSource`,
`OutgoingMessage`, `ParsedArea`, `ParsedMessage`, `ReaderOptions`, `WriterOptions`.
Fields use snake_case. `reply1stMsgno` becomes `reply1st_msgno`.
`ParserException` extends `RuntimeError`.

| PHP | Python |
| --- | --- |
| FtnAddress::fromString / tryFromString / toString | FtnAddress.from_string / try_from_string / str(address) |
| CharsetDetector::detect | detect_charset(bytes, fallback="CP850") |
| Text::toUtf8 | to_utf8(bytes, charset="CP850", errors="strict") |
| Text::parseBody | parse_body(str) |
| Text::readNullPaddedField | read_null_padded_field(bytes, offset, length) -> bytes |
| Text::syntheticId | synthetic_id(from_name, to_name, subject, date, body) |
| ControlLines::extractMsgid / parseMessage | extract_msgid(str) / parse_message(str) |
| MojibakeRepairer::repair | repair_mojibake(str, declared_charset=None, prefer_quoted_lines=True) |
| MojibakeRepairResult | MojibakeRepairResult |
| MessageBaseReader::read | MessageBaseReader.read |
| MessageWriter::write | MessageWriter.write |
| MessageSourceCatalog::sources | MessageSourceCatalog.sources |
| MessageSourceLocator::find | MessageSourceLocator.find |

Protocols accept `str | os.PathLike[str]` paths. Readers yield
`Iterable[ParsedMessage]`; writers take `Iterable[OutgoingMessage]` and return
an integer count. Catalogs yield `Iterable[MessageSource]`; locators return
`str | None`. Options remain optional with CP850 defaults.

Python differences are deliberate: immutable tuples and keyword-only dataclasses;
separate bytes/text boundaries; strict decoding; explicit error policies;
non-negative fixed-field offsets and lengths; ASCII address digits; UTF-8/UTF8
charset aliases; SHA-256 over the complete JSON array rather than PHP's MD5 over
a delimiter string and first 200 body bytes. `None` and an empty date differ.
Trailing nulls are retained in `ControlLine.raw` while parsing ignores them.

Mojibake uses the same encoding candidates, damage markers, plausible characters,
words and quote threshold as PHP. Python strict round trips exclude PHP iconv
IGNORE candidates that discard characters. RFC 2047 uses Python's email decoder;
malformed words remain unchanged when decoding fails. Platform-specific iconv
behaviour is not a compatibility promise.

Unlike PHP's legacy MSGID search, `extract_msgid` delegates to `parse_message`:
only unquoted line-start kludges are considered, names are case-insensitive,
first values win (including empty values), and interior nulls remain intact.
Trailing nulls are ignored in parsed values while `ControlLine.raw` keeps them.

Charset tokens end at whitespace, null or the next kludge-start character.
Fallback FTN aliases are resolved before codec validation. An invalid fallback
always raises `LookupError`, even when a usable declaration is present. Mojibake
candidate selection uses the same alias resolver; unknown declarations continue
to use the default candidate encodings.
