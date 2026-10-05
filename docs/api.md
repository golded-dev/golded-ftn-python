# API reference for golded-ftn

This reference covers all 40 names exported by `golded_ftn` in the 1.2.0
working tree. Import public values and functions from `golded_ftn`. Core owns
values, protocols and pure text helpers. Concrete format packages own files,
serialization, record validation and writer sessions.

The distribution is `golded-ftn`, the import is `golded_ftn`, and Python 3.12+
is required. There are no runtime dependencies. See [PHP API mapping](php-api.md)
for migration differences and the shared [writer guide](../../golded-ftn-python-docs/docs/writers.md)
for concrete MSG, JAM, Squish and Hudson examples in the sibling checkout.

## Value conventions

All dataclass constructors are keyword-only. Values are frozen and slotted.
The tables below give every constructor field, its type and its default.
**Required** means the constructor has no default. Core annotations describe
the contract; they do not validate every value at runtime. Format writers check
encoded lengths, numeric ranges, representable fields and date restrictions.

Strings are Unicode. Source bytes stay separate. Dates are `datetime` values;
core does not infer timezones or convert timestamps. Unknown metadata is `None`.
An empty string, `0`, `()`, `None` and `UNSET` have different meanings.

`MessageControlLines` and `OutgoingMessage` convert their collection fields to
tuples during construction. Other models require callers to pass their declared
types; freezing a model does not recursively freeze incorrectly typed inputs.

## Addresses and controls

### `FtnAddress`

```text
FtnAddress(*, zone: int, net: int, node: int,
           point: int | None = None, domain: str | None = None)
FtnAddress.from_string(value: str) -> FtnAddress
FtnAddress.try_from_string(value: str) -> FtnAddress | None
str(address) -> str
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `zone` | `int` | Required | Network zone. |
| `net` | `int` | Required | Network number. |
| `node` | `int` | Required | Node number. |
| `point` | `int \| None` | `None` | Optional point, including explicit point `0`. |
| `domain` | `str \| None` | `None` | Optional domain, with original case retained. |

The parsers accept `zone:net/node`, optional `.point` and optional `@domain`,
with surrounding whitespace stripped. Numeric parts contain ASCII digits only.
Domains begin with an ASCII letter or digit and then allow letters, digits,
periods, underscores and hyphens. Parsing accepts arbitrary non-negative integer
sizes; it does not enforce a format's 16-bit address limits. Direct construction
does not enforce this grammar.

`from_string` raises `ValueError` for invalid syntax. `try_from_string` returns
`None`. `str` emits the full address and includes `.0` when point is explicitly
zero. It does not normalize domain case or remove an explicit point.

### `ControlLine`

```text
ControlLine(*, name: str, value: str, raw: str)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | `str` | Required | Kludge name; the parser uppercases it. |
| `value` | `str` | Required | Parsed value; the parser trims surrounding whitespace. |
| `raw` | `str` | Required | Original decoded line, without its line separator. |

`raw` includes any trailing nulls on the loaded line. It is decoded text, not
original source bytes. For newly supplied writer controls, use `raw=""`;
concrete serializers use structured names and values and validate them.

### `MessageControlLines`

```text
MessageControlLines(*, kludges=(), msgid=None, reply=None, charset=None,
                    seen_by=(), path=(), tearline=None, origin=None,
                    origin_address=None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `kludges` | `tuple[ControlLine, ...]` | `()` | Valid SOH kludges, including unknown names and repetitions, in input order. |
| `msgid` | `str \| None` | `None` | First parsed MSGID value, including an empty value. |
| `reply` | `str \| None` | `None` | First parsed REPLY value; this is external metadata. |
| `charset` | `str \| None` | `None` | First CHRS or CHARSET value, including its level suffix. |
| `seen_by` | `tuple[str, ...]` | `()` | Unexpanded SEEN-BY values. |
| `path` | `tuple[str, ...]` | `()` | Unexpanded plain PATH values. See parser limitation below. |
| `tearline` | `str \| None` | `None` | First unquoted line beginning `---`. |
| `origin` | `str \| None` | `None` | First recognized origin text, without the `Origin:` prefix. |
| `origin_address` | `FtnAddress \| None` | `None` | First valid parenthesized address at the end of a recognized origin line. |

`kludges`, `seen_by` and `path` are converted to tuples. Direct construction
does not reconcile convenience fields with the contents of `kludges`.

### `parse_message`

```text
parse_message(text: str) -> MessageControlLines
```

Splits CRLF, CR and LF without changing the supplied string. Parsing ignores
empty lines and quoted lines beginning with optional whitespace followed by `>`
or one to six ASCII letters/digits followed by `>`. It ignores trailing nulls
when interpreting a line but retains them in `ControlLine.raw`.

A kludge must start at column zero with SOH (`\x01`) and use
`NAME: value`. Names begin with an ASCII letter and then allow ASCII letters,
digits and hyphens. Names are uppercased; first MSGID, REPLY and charset values
win. Valid unknown kludges and repetitions remain in `kludges`. There is no
conflict validation here: a writer may reject conflicting declarations.

Plain `SEEN-BY:` and `PATH:` lines are case-sensitive and have their surrounding
value whitespace stripped. The current parser keeps SOH `\x01PATH:` in
`kludges` but does **not** add it to `path`. Space-separated SOH controls such as
`\x01INTL 2:1/2 2:1/3` are not parsed by this core helper; concrete readers may
extend its syntax. Routing strings are never expanded or deduplicated.

Origin recognition requires a leading whitespace character followed by
`* Origin:`. `origin` keeps the first recognized origin text; a later recognized
origin line can supply `origin_address` if earlier lines had no valid address.
Ordinary body lines are not returned separately by this function.

### `extract_msgid`

```text
extract_msgid(text: str) -> str | None
```

Returns `parse_message(text).msgid`. It uses exactly the same quoting and syntax
rules, including first-value precedence and an empty string as a valid result.
It does not generate an ID or validate uniqueness.

```python
from golded_ftn import FtnAddress, extract_msgid, parse_message

address = FtnAddress.from_string(" 2:236/77.0@fidonet ")
assert str(address) == "2:236/77.0@fidonet"
assert FtnAddress.try_from_string("not an address") is None
text = "> \x01MSGID: quoted\r\x01msgid: actual\r\x01X-CUSTOM: value\0"
controls = parse_message(text)
assert extract_msgid(text) == "actual"
assert controls.kludges[-1].name == "X-CUSTOM"
assert controls.kludges[-1].raw.endswith("\0")
assert parse_message("SEEN-BY: 1/2 3\nPATH: 1/4").path == ("1/4",)
```

## Decoding and text helpers

### `DecodeErrors`

```text
DecodeErrors = Literal["strict", "replace", "ignore"]
```

Type alias for `to_utf8`'s error policy. `strict` raises on malformed input;
`replace` inserts replacement characters; `ignore` discards undecodable bytes.
Neither lossy mode retains the original bytes for you.

### `detect_charset`

```text
detect_charset(raw_body: bytes, fallback: str = "CP850") -> str
```

Finds the first case-insensitive SOH `CHRS:` or `CHARSET:` declaration anywhere
in the byte string. The token ends at whitespace, null or another SOH. Detection
does not apply the text parser's quoted-line rules. A recognized FTN alias is
resolved; an absent or unknown declaration uses `fallback`. This is declaration
lookup, not statistical encoding detection, and it does not reject conflicting
later declarations.

The fallback is always resolved and validated through Python's codec registry,
even when the message has a recognized declaration. Invalid fallbacks raise
`LookupError`. Supported declaration aliases, matched case-insensitively:

| Aliases | Returned encoding |
| --- | --- |
| `CP850`, `IBM850`, `IBMPC`, `IBM` | `CP850` |
| `LATIN-1`, `LATIN1`, `8859-1`, `ISO-8859-1`, `ISO8859-1` | `ISO-8859-1` |
| `ASCII`, `USASCII` | `ASCII` |
| `CP866`, `IBM866` | `CP866` |
| `KOI8-R`, `KOI8R` | `KOI8-R` |
| `CP437`, `IBM437` | `CP437` |
| `CP1251` | `CP1251` |
| `CP1252` | `CP1252` |
| `CP1250` | `CP1250` |
| `LATIN-2`, `ISO-8859-2` | `ISO-8859-2` |
| `UTF-8`, `UTF8` | `UTF-8` |

Fallbacks additionally accept names understood by Python's codec registry.
The returned spelling is an alias target or the validated fallback spelling,
not necessarily the codec registry's canonical name.

### `to_utf8`

```text
to_utf8(value: bytes, charset: str = "CP850", *,
        errors: DecodeErrors = "strict") -> str
```

Removes trailing null bytes, then decodes with `charset` into Python Unicode.
Despite its name, the result is a `str`, not UTF-8 bytes. Interior nulls remain.
The charset is passed directly to Python's codec registry: resolve FTN aliases
with `detect_charset` first. Unknown codec names raise `LookupError`; malformed
bytes raise `UnicodeDecodeError` in strict mode. An unsupported error policy
raises `ValueError`.

### `parse_body`

```text
parse_body(text: str) -> str
```

Removes trailing null characters and normalizes CRLF and CR to LF. It preserves
interior nulls, controls, routing and ordinary text. It does not decode, extract
metadata or repair mojibake.

### `read_null_padded_field`

```text
read_null_padded_field(raw: bytes, offset: int, length: int) -> bytes
```

Takes the requested byte slice and returns its bytes before the first null.
Negative offset or length raises `ValueError`. A slice beyond the buffer is
short or empty; this helper does not enforce binary record bounds. Validate
record size before interpreting fixed fields.

### `synthetic_id`

```text
synthetic_id(from_name: str, to_name: str, subject: str,
             date: str | None, body: str) -> str
```

Returns `hash:sha256:` plus 64 lowercase hexadecimal digits. The digest covers
the exact UTF-8 encoding of JSON `[from_name, to_name, subject, date, body]`,
with `ensure_ascii=False` and separators `(",", ":")`. The complete body is
included. Names, text and date are not normalized. `None` and `""` dates differ.
Consumers choose their date string format.

This is a content-derived ID, separate from source record identity and revision.
It does not prove that two source records are the same. Concrete writers do not
automatically generate MSGID, and a synthetic ID must not be supplied as an
external MSGID.

```python
from golded_ftn import (
    detect_charset,
    parse_body,
    read_null_padded_field,
    synthetic_id,
    to_utf8,
)

raw = b"\x01CHRS: IBMPC 2\rBruger m\x9bde\0\0"
charset = detect_charset(raw)
assert charset == "CP850"
assert parse_body(to_utf8(raw, charset)).endswith("Bruger møde")
assert read_null_padded_field(b"xxAlice\0padding", 2, 13) == b"Alice"
assert read_null_padded_field(b"x", 8, 2) == b""
assert parse_body("a\0b\r\n\0") == "a\0b\n"
assert to_utf8(b"\xff", "UTF-8", errors="replace") == "\ufffd"
identity = synthetic_id("Alice", "Bob", "Ping", None, "body")
assert identity.startswith("hash:sha256:") and len(identity) == 76
assert identity != synthetic_id("Alice", "Bob", "Ping", "", "body")
```

## Optional text repair

### `MojibakeRepairResult`

```text
MojibakeRepairResult(*, text: str, changed: bool, confidence: float)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `text` | `str` | Required | Repaired text, with LF line endings. |
| `changed` | `bool` | Required | At least one line was repaired. |
| `confidence` | `float` | Required | Heuristic score for the returned repair. |

The score is not a probability. Returned scores lie between 0 and 1; direct
construction does not validate that range.

### `repair_mojibake`

```text
repair_mojibake(text: str, declared_charset: str | None = None,
               prefer_quoted_lines: bool = True) -> MojibakeRepairResult
```

Attempts RFC 2047 decoding and strict encoding round trips per line. It scores
damage markers, plausible European letters and a small word list. Default
visible encodings are CP850, CP437, CP865, ISO-8859-1 and Windows-1252; intended
encodings are UTF-8, ISO-8859-1, Windows-1252 and CP850. A valid first token of
`declared_charset`, including an FTN alias, adds a candidate. Unknown declarations
fall back to the default candidates.

`prefer_quoted_lines=True` lowers the score threshold for matching quote lines;
it does not mean only quoted lines are examined. Candidates that cannot encode
and decode strictly are discarded. Malformed RFC 2047 words remain unchanged
when decoding fails. Repair always returns a new result and never modifies
source data.

CRLF and CR are normalized to LF even when `changed` is false. `confidence` is
the mean of line scores, including zero scores for unchanged lines, capped at
1. This is an opt-in heuristic tuned to European-language fixtures, not a
general detector. Readers and writers do not invoke it automatically.

```python
from golded_ftn import repair_mojibake

result = repair_mojibake("Bruger m°de")
assert result.text == "Bruger møde" and result.changed
assert 0 < result.confidence <= 1
plain = repair_mojibake("a\r\nb")
assert plain.text == "a\nb" and not plain.changed
assert plain.confidence == 0
```

## Read values and options

### `MessageProvenance`

```text
MessageProvenance(*, source_type: str, source_path=None,
                  source_id=None, source_offset=None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `source_type` | `str` | Required | Source format or source kind. |
| `source_path` | `str \| None` | `None` | Actual source path when known. |
| `source_id` | `str \| None` | `None` | Format-specific record identity when known. |
| `source_offset` | `int \| None` | `None` | Physical byte offset when known. |

Provenance records where a value was read. It is separate from external MSGID
and does not itself provide a writer revision or permission to mutate a base.

### `MessageSource`

```text
MessageSource(*, source_type: str, path: str, code: str, name: str,
              sort_order: int = 0, meta_key: str | None = None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `source_type` | `str` | Required | Format selected by a concrete catalog. |
| `path` | `str` | Required | Catalog source path. |
| `code` | `str` | Required | Area code. |
| `name` | `str` | Required | Area display name. |
| `sort_order` | `int` | `0` | Catalog ordering value. |
| `meta_key` | `str \| None` | `None` | Optional consumer metadata key. |

Core does not discover paths or interpret `meta_key`.

### `ParsedArea`

```text
ParsedArea(*, code: str, name: str, source_type: str,
           sort_order: int = 0, meta_key: str | None = None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `code` | `str` | Required | Area code. |
| `name` | `str` | Required | Area display name. |
| `source_type` | `str` | Required | Source format or source kind. |
| `sort_order` | `int` | `0` | Area ordering value. |
| `meta_key` | `str \| None` | `None` | Optional consumer metadata key. |

Area metadata has no path field. Use `MessageSource` for a located source.

### `ParsedMessage`

```text
ParsedMessage(*, msgno: int, from_name: str, to_name: str, subject: str,
              body_text: str, attributes_raw: int, posted_at=None,
              external_id=None, from_address=None, to_address=None,
              reply_to_msgno=None, reply1st_msgno=None, reply_next_msgno=None,
              area_code=None, area_name=None, area_sort_order=None,
              area_meta_key=None, control_lines=None, provenance=None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `msgno` | `int` | Required | Format-specific message number or Squish UID. |
| `from_name` | `str` | Required | Decoded sender name. |
| `to_name` | `str` | Required | Decoded recipient name. |
| `subject` | `str` | Required | Decoded subject. |
| `body_text` | `str` | Required | Decoded body; concrete formats decide whether header controls are included. |
| `attributes_raw` | `int` | Required | Raw format-specific attribute bits. |
| `posted_at` | `datetime \| None` | `None` | Parsed posting time when known. |
| `external_id` | `str \| None` | `None` | Reader-supplied ID; a concrete reader may use a synthetic fallback. |
| `from_address` | `str \| None` | `None` | Parsed sender address as text. |
| `to_address` | `str \| None` | `None` | Parsed recipient address as text. |
| `reply_to_msgno` | `int \| None` | `None` | Format-specific parent message link. |
| `reply1st_msgno` | `int \| None` | `None` | Format-specific first reply link. |
| `reply_next_msgno` | `int \| None` | `None` | Format-specific next reply link. |
| `area_code` | `str \| None` | `None` | Area code when supplied by the reader. |
| `area_name` | `str \| None` | `None` | Area name when supplied by the reader. |
| `area_sort_order` | `int \| None` | `None` | Area ordering value when supplied. |
| `area_meta_key` | `str \| None` | `None` | Consumer metadata key when supplied. |
| `control_lines` | `MessageControlLines \| None` | `None` | Parsed controls and routing when supplied. |
| `provenance` | `MessageProvenance \| None` | `None` | Source location when supplied. |

This decoded view does not contain all raw headers, unknown binary metadata or
the complete Squish reply list. Writers update from raw records under their
lock; rebuilding an existing record from `ParsedMessage` can lose metadata.

### `ReaderIssue`

```text
ReaderIssue(*, source_type: str, source_path: str,
            action: Literal["recovered", "skipped", "stopped"],
            code: str, detail: str, source_id=None, source_offset=None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `source_type` | `str` | Required | Source format or source kind. |
| `source_path` | `str` | Required | Actual source file path. |
| `action` | `Literal["recovered", "skipped", "stopped"]` | Required | What the concrete reader did. |
| `code` | `str` | Required | Machine-readable issue code defined by the format reader. |
| `detail` | `str` | Required | Explanation without message contents. |
| `source_id` | `str \| None` | `None` | Record identity when known. |
| `source_offset` | `int \| None` | `None` | Physical byte offset when known. |

`recovered` describes an accepted deviation. `skipped` excludes a record.
`stopped` means traversal is incomplete. Several issues may describe one record;
an earlier recovery does not prevent a later skip. Core does not enforce issue
codes or sanitize a directly supplied `detail` string.

### `ReaderOptions`

```text
ReaderOptions(*, fallback_charset: str = "CP850", archive_mode: bool = False,
              on_issue: Callable[[ReaderIssue], None] | None = None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `fallback_charset` | `str` | `"CP850"` | Charset used when no recognized declaration is available. |
| `archive_mode` | `bool` | `False` | Explicitly permit a concrete reader's documented recoveries. |
| `on_issue` | `Callable[[ReaderIssue], None] \| None` | `None` | Callback receiving archive deviations. |

`archive_mode=True` without `on_issue` raises `ValueError` at construction.
The constructor does not validate the charset. Readers validate it when used.
Strict mode is the default. Supplying a callback alone does not enable recovery.
Filesystem and callback exceptions propagate; archive mode does not suppress
them. Each format defines its permitted recovery steps. Archive reads do not
authorize editing a damaged base.

```python
from golded_ftn import ReaderIssue, ReaderOptions

issues: list[ReaderIssue] = []
options = ReaderOptions(archive_mode=True, on_issue=issues.append)
assert options.fallback_charset == "CP850"
assert options.on_issue is not None
options.on_issue(
    ReaderIssue(
        source_type="msg",
        source_path="area/1.MSG",
        source_id="1",
        source_offset=190,
        action="skipped",
        code="example",
        detail="Record cannot be decoded.",
    )
)
assert issues[0].action == "skipped"
```

## Write values, patches and revisions

### `OutgoingMessage`

```text
OutgoingMessage(*, from_name: str, to_name: str, subject: str, body_text: str,
                external_id=None, from_address=None, to_address=None,
                posted_at=None, attributes_raw=None, control_lines=(),
                provenance=None, reply_to_msgno=None, reply1st_msgno=None,
                reply_next_msgno=None, reply_list=(), routing_seen_by=(),
                routing_path=())
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `from_name` | `str` | Required | Sender name. |
| `to_name` | `str` | Required | Recipient name. |
| `subject` | `str` | Required | Subject. |
| `body_text` | `str` | Required | Unicode message body. |
| `external_id` | `str \| None` | `None` | Explicit external MSGID, if supplied. |
| `from_address` | `FtnAddress \| None` | `None` | Structured sender address. |
| `to_address` | `FtnAddress \| None` | `None` | Structured recipient address. |
| `posted_at` | `datetime \| None` | `None` | Posting date; concrete writers enforce precision/range/timezone rules. |
| `attributes_raw` | `int \| None` | `None` | Raw format-specific attribute bits; concrete writers choose their default. |
| `control_lines` | `tuple[ControlLine, ...]` | `()` | Structured controls to serialize. |
| `provenance` | `MessageProvenance \| None` | `None` | Caller-supplied provenance; serialization support is format-specific. |
| `reply_to_msgno` | `int \| None` | `None` | Format-specific parent link. |
| `reply1st_msgno` | `int \| None` | `None` | Format-specific first reply link. |
| `reply_next_msgno` | `int \| None` | `None` | Format-specific next reply link. |
| `reply_list` | `tuple[int, ...]` | `()` | Complete reply UID list for a format that represents one. |
| `routing_seen_by` | `tuple[str, ...]` | `()` | Explicit unexpanded SEEN-BY values. |
| `routing_path` | `tuple[str, ...]` | `()` | Explicit unexpanded PATH values. |

Collection fields are converted to tuples. Core does not generate MSGID,
route messages, detect duplicates or validate that replies exist. Concrete
formats reject unrepresentable fields and contradictory metadata. Numeric
reply links are independent of external `MSGID` and `REPLY` controls.

### `WriterOptions`

```text
WriterOptions(*, target_charset: str = "CP850", lock_timeout: float = 5.0,
              concurrent: bool = False)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `target_charset` | `str` | `"CP850"` | Encoding for values that require serialization. |
| `lock_timeout` | `float` | `5.0` | Maximum lock wait in seconds, measured with a monotonic clock. |
| `concurrent` | `bool` | `False` | Request supported concurrent GoldED access. |

Negative, infinite or NaN `lock_timeout` raises `ValueError` at construction.
Zero requests an immediate lock attempt. The constructor does not validate the
codec; concrete writers do so during serialization. Encoding is strict, with
no silent truncation or replacement characters. Conflicting charset metadata
is rejected. Pure attribute changes preserve existing text bytes.

`concurrent=True` is a request, not permission or a safety guarantee. Current
MSG, JAM, Squish and Hudson writers reject it. GoldED must remain closed during
offline editing. Live support requires format, platform and build-specific
competing writer, reader and refresh tests. Windows starts with offline use.

### `Unset`

```text
Unset()
```

Marker type used in patch annotations. It has no fields and is not a dataclass.
Use the exported singleton `UNSET` rather than creating another `Unset()`;
concrete writers can use identity comparisons with that singleton.

### `UNSET`

```text
UNSET: Unset
```

The singleton default for every patch field. It means leave the stored field
untouched. It is different from `None`, which explicitly requests clearing.

### `MessagePatch`

```text
MessagePatch(*, from_name=UNSET, to_name=UNSET, subject=UNSET,
             body_text=UNSET, external_id=UNSET, from_address=UNSET,
             to_address=UNSET, posted_at=UNSET, attributes_raw=UNSET,
             control_lines=UNSET, provenance=UNSET, reply_to_msgno=UNSET,
             reply1st_msgno=UNSET, reply_next_msgno=UNSET, reply_list=UNSET,
             routing_seen_by=UNSET, routing_path=UNSET)
```

Every field defaults to `UNSET`. Each accepts `None` as a clear request; the
concrete writer rejects clearing fields it cannot represent. Required names
and body generally need a string, including `""` when allowed, rather than
`None`. Core does not validate or convert patch collections.

| Field | Type | Default |
| --- | --- | --- |
| `from_name` | `str \| None \| Unset` | `UNSET` |
| `to_name` | `str \| None \| Unset` | `UNSET` |
| `subject` | `str \| None \| Unset` | `UNSET` |
| `body_text` | `str \| None \| Unset` | `UNSET` |
| `external_id` | `str \| None \| Unset` | `UNSET` |
| `from_address` | `FtnAddress \| None \| Unset` | `UNSET` |
| `to_address` | `FtnAddress \| None \| Unset` | `UNSET` |
| `posted_at` | `datetime \| None \| Unset` | `UNSET` |
| `attributes_raw` | `int \| None \| Unset` | `UNSET` |
| `control_lines` | `tuple[ControlLine, ...] \| None \| Unset` | `UNSET` |
| `provenance` | `MessageProvenance \| None \| Unset` | `UNSET` |
| `reply_to_msgno` | `int \| None \| Unset` | `UNSET` |
| `reply1st_msgno` | `int \| None \| Unset` | `UNSET` |
| `reply_next_msgno` | `int \| None \| Unset` | `UNSET` |
| `reply_list` | `tuple[int, ...] \| None \| Unset` | `UNSET` |
| `routing_seen_by` | `tuple[str, ...] \| None \| Unset` | `UNSET` |
| `routing_path` | `tuple[str, ...] \| None \| Unset` | `UNSET` |

Names have the same meaning as in `OutgoingMessage`. An omitted field preserves
existing raw metadata, including reply structures the decoded model cannot
fully display. Explicit control/routing replacements follow the concrete
format's representation rules. Deleting a message does not rewrite other
messages' reply links, and message numbers are not renumbered.

### `MessageIdentity`

```text
MessageIdentity(*, format: str, base: str, msgno: int,
                board: int | None = None)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `format` | `str` | Required | Concrete format tag, such as `msg`, `jam`, `squish` or `hudson`. |
| `base` | `str` | Required | Base identity selected by the concrete writer. |
| `msgno` | `int` | Required | MSG file number, JAM message number, Squish UID or Hudson message number. |
| `board` | `int \| None` | `None` | Explicit Hudson board where applicable. |

Use identities returned by sessions. Core does not canonicalize base paths or
validate board/number ranges. External MSGID is not part of this identity.

### `RevisionToken`

```text
RevisionToken(*, identity: MessageIdentity, location: tuple[int, ...], digest: str)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `identity` | `MessageIdentity` | Required | Target record identity. |
| `location` | `tuple[int, ...]` | Required | Physical record placement defined by the concrete format. |
| `digest` | `str` | Required | SHA-256 hexadecimal digest of raw message header, metadata and text. |

A session issues this token from a consistent read and checks it again under
the operation lock. Global base counters are not message revisions. Changes to
other messages do not invalidate a token. Treat the entire token as opaque;
core does not validate a manually constructed digest or location. It is an
optimistic concurrency check, not authentication or a permanent message ID.

### `WriteResult`

```text
WriteResult(*, identity: MessageIdentity, revision: RevisionToken)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `identity` | `MessageIdentity` | Required | Identity of the appended or updated message. |
| `revision` | `RevisionToken` | Required | Revision after that operation. |

Use the returned revision for the next update/delete. An earlier revision can
be stale after content or attribute changes.

### `SessionMessage`

```text
SessionMessage(*, message: ParsedMessage, identity: MessageIdentity,
               revision: RevisionToken)
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `message` | `ParsedMessage` | Required | Decoded view from the consistent session read. |
| `identity` | `MessageIdentity` | Required | Identity of that record. |
| `revision` | `RevisionToken` | Required | Raw record revision read with the view. |

Core does not enforce that manually constructed triples refer to the same
record. Obtain them through the concrete session.

```python
from golded_ftn import UNSET, MessageIdentity, MessagePatch, OutgoingMessage

message = OutgoingMessage(
    from_name="Alice",
    to_name="Bob",
    subject="Ping",
    body_text="Hello",
    reply_to_msgno=7,
    routing_seen_by=("1/2 3",),
)
patch = MessagePatch(subject="Edited", external_id=None)
assert patch.subject == "Edited"
assert patch.external_id is None
assert patch.body_text is UNSET
record = MessageIdentity(format="hudson", base="area", board=2, msgno=7)
assert record.board == 2 and message.external_id is None
```

## Protocols and session lifecycle

These are structural typing protocols. A matching concrete object can satisfy
them without inheriting from the protocol. They contain method signatures,
not concrete behavior. They are not marked `runtime_checkable`; do not use them
with `isinstance` or instantiate them. Paths accept `str | os.PathLike[str]`.
Concrete APIs may expose extra format-specific arguments.

### `MessageBaseReader`

```text
read(self, path: str | PathLike[str],
     options: ReaderOptions | None = None) -> Iterable[ParsedMessage]
```

Read an area through a concrete reader. `None` selects default reader options.
The iterable may be lazy; errors can appear during iteration. A reader's plain
`ParsedMessage` does not include a session revision for editing.

### `MessageSourceCatalog`

```text
sources(self, path: str | PathLike[str],
        options: ReaderOptions | None = None) -> Iterable[MessageSource]
```

Discover configured message sources through a concrete catalog. Ordering and
path interpretation belong to that catalog. Core has no discovery implementation.

### `MessageSourceLocator`

```text
find(self, path: str | PathLike[str]) -> str | None
```

Find a source path through a concrete locator. `None` means no match. Search
rules and the meaning of the input path belong to the concrete locator.

### `MessageWriter`

```text
write(self, path: str | PathLike[str], messages: Iterable[OutgoingMessage],
      options: WriterOptions | None = None) -> int
```

Batch-writing convenience contract returning the number written. Core does not
provide a batch implementation or promise a transaction around the iterable.
The MSG convenience writer commits each successful message separately; check
other formats' APIs before assuming they implement this legacy method.

### `MessageBaseWriter`

```text
create(self, path: str | PathLike[str]) -> None
open(self, path: str | PathLike[str], options: WriterOptions | None = None)
    -> AbstractContextManager[MessageWriterSession]
```

`create` initializes an empty base and rejects existing base files. It does not
open a session. `open` opens an existing base, with default options when omitted.
Use the returned context manager to scope the session. Hudson's concrete `open`
requires an explicit board; whole-base creation remains independent of board.
Required initialization/lastread files are format-specific.

### `MessageWriterSession`

```text
read(self, msgno: int) -> SessionMessage
append(self, message: OutgoingMessage) -> WriteResult
update(self, identity: MessageIdentity, patch: MessagePatch,
       expected_revision: RevisionToken) -> WriteResult
delete(self, identity: MessageIdentity,
       expected_revision: RevisionToken) -> MessageIdentity
```

Each operation takes the format lock, reloads control data and holds the lock
through validation, writing and flush. `read` supplies a consistent decoded
view and revision. `append` allocates a format-specific identity; `update`
preserves identity and returns the new revision. `delete` returns the deleted
identity. A missing or changed update/delete target raises `ConflictError`.

One operation is the commit unit. Earlier successful operations survive a later
failure. Ordinary write failures trigger rollback under the lock. Failed rollback
makes the session unusable and reports `RollbackError`; reopening a session is
not proof that the base is healthy. Concrete writers reject damaged bases and
do not use archive recovery for editing.

Callers must not access base files directly while writer operations run. A
Python writer lock alone does not establish safe coexistence with GoldED.
Rollback has no guarantee for process termination or power loss, and there is
no automatic detection promise for every partial write.

The following functions consume protocols. The caller supplies concrete objects;
core has no file reader or writer to instantiate. MSG, JAM and Squish expose
the shown writer shape. Hudson needs a board-bound adapter for this generic
example, because its concrete `open` requires a board argument that the core
protocol does not express.

```python
from golded_ftn import (
    MessageBaseReader,
    MessageBaseWriter,
    MessagePatch,
    OutgoingMessage,
    ParsedMessage,
    WriteResult,
)


def collect_messages(reader: MessageBaseReader, path: str) -> tuple[ParsedMessage, ...]:
    return tuple(reader.read(path))


def append_edit_delete(writer: MessageBaseWriter, path: str) -> WriteResult:
    writer.create(path)
    with writer.open(path) as session:
        created = session.append(
            OutgoingMessage(
                from_name="Alice",
                to_name="Bob",
                subject="Ping",
                body_text="Hello",
            )
        )
        current = session.read(created.identity.msgno)
        edited = session.update(
            current.identity,
            MessagePatch(subject="Edited"),
            current.revision,
        )
        session.delete(edited.identity, edited.revision)
        return edited
```

## Exceptions

### `ParserException`

```text
class ParserException(RuntimeError)
```

Concrete readers and writer base-validation paths use this error for records
they cannot parse. Concrete APIs may chain the underlying error. Filesystem
failures and archive callback failures propagate separately; this is not a
catch-all for every read error.

### `WriterError`

```text
class WriterError(RuntimeError)
```

Common base class for the writer-specific errors below. Concrete sessions also
use it when closed or poisoned. Input validation and encoding failures can raise
`ValueError`, `LookupError` or `UnicodeEncodeError`; filesystem/I/O failures can
raise `OSError`. Catching only `WriterError` does not catch every failed write.

### `ConflictError`

```text
class ConflictError(WriterError)
```

The target is missing, belongs to another base/identity or no longer matches
the expected revision. Read the current target and decide how to reconcile the
change. Do not retry the same stale patch blindly. Concrete session reads also
use this error for a missing message.

### `LockTimeoutError`

```text
class LockTimeoutError(WriterError)
```

The operation could not obtain the base lock within `WriterOptions.lock_timeout`.
The operation has not begun mutating the base.

### `RollbackError`

```text
class RollbackError(WriterError)
```

An operation failed and restoring original bytes also failed. The exception
reports base, operation and rollback failure. The concrete session stops
accepting operations. The base may need inspection; automatic repair is outside
this API.

### `UnsupportedOperationError`

```text
class UnsupportedOperationError(WriterError)
```

A requested operation or concurrency mode is unavailable. Examples include
current `concurrent=True` requests and explicit Opus editing through the MSG
writer. Unrepresentable message fields may instead raise `ValueError`, as
documented by the concrete format.

## Boundaries

Core does not read or write MSG, JAM, Squish or Hudson files itself. It does not
implement BBS behavior, routing policy, duplicate checking, packet handling,
packing, repair of damaged bases or GoldED configuration. Internal modules such
as `golded_ftn._writer_io` are implementation details and are not public exports.

Current writer sessions are for offline editing. GoldED interoperability and
concurrent reader/refresh tests are deferred; source review or passing Python
tests do not establish those guarantees. Check the concrete package's format
notes and the shared writer guide before choosing a format or platform.
