# golded-ftn

Repository: [`golded-ftn-python`](https://github.com/golded-dev/golded-ftn-python).
The distribution remains `golded-ftn`; imports use `golded_ftn`.
The source is public on GitHub. [Version 1.2.2 is available on PyPI](https://pypi.org/project/golded-ftn/1.2.2/).

Install with Python 3.12 or newer:

```sh
python -m pip install golded-ftn==1.2.2
```

Shared FTN message values, reader/writer protocols and text helpers for Python
3.12+. No runtime dependencies. No concrete format readers, writers, database
access or Nornir integration.

For development, clone the repository, then build and install a local wheel:

```sh
git clone https://github.com/golded-dev/golded-ftn-python.git
cd golded-ftn-python
uv sync --locked
uv build
python -m pip install dist/golded_ftn-1.2.2-py3-none-any.whl
```

```python
from golded_ftn import FtnAddress, detect_charset, parse_body, parse_message, to_utf8

address = FtnAddress.from_string("2:236/77.1@fidonet")
assert str(address) == "2:236/77.1@fidonet"
raw = b"\x01CHRS: IBMPC 2\r\nBruger m\x9bde\x00"
text = parse_body(to_utf8(raw, detect_charset(raw)))
assert text.endswith("Bruger møde")
assert parse_message(text).charset == "IBMPC 2"
```

```python
from golded_ftn import OutgoingMessage, repair_mojibake, synthetic_id

message = OutgoingMessage(
    from_name="Alice", to_name="Bob", subject="Ping", body_text="Hello"
)
identity = synthetic_id(
    message.from_name, message.to_name, message.subject, None, message.body_text
)
assert identity.startswith("hash:sha256:")
result = repair_mojibake("Bruger m°de")
assert result.text == "Bruger møde"
assert result.changed
```

Decoding is strict by default. Pass `errors="replace"` or `errors="ignore"`
explicitly when lossy decoding is intended. An unknown declared charset uses the
configured fallback. FTN aliases also work as fallback names. An invalid fallback
always raises `LookupError`, even when the message declares a known charset.

Historical Cyrillic declarations are supported in both `CHRS` and `CHARSET`:

| Names | Decoded as |
| --- | --- |
| `CP-866`, `+7FIDO`, `+7_FIDO`, `FIDO7`, `FIDO_7`, `RUS` | CP866 |
| `KOI`, `KOI8`, `GOST`, `CP20866` | KOI8-R |
| `WIN`, `WIN-1251`, `WINDOWS-1251`, `CP-1251` | CP1251 |
| `KOI8-U`, `KOI8U`, `KOU`, `KOI-U`, `CP21866` | KOI8-U |
| `CP1125`, `UKR` | CP1125 |

These aliases follow [GoldED+'s configuration](https://github.com/golded-plus/golded-plus/blob/1a251c6375081453a410bb8d647be120b8902de3/cfgs/config/advanced.cfg#L1498).
Names are case-insensitive and also work as configured fallbacks. The first FTN
charset declaration wins; RFC `Content-Type` is not used for body detection.
The default and `IBMPC` remain CP850.

`repair_mojibake` stays opt-in; its confidence is a heuristic score. Keep the
original bytes/text separately. Repair preserves box-drawing frames and block
art, literal degree signs and already-correct Danish/German words. Isolated
`┼`/`▀` inside words can still be damaged letters; strict UTF-8 recovery can also
repair graphics-looking bytes such as `m├©de`. These are contextual heuristics,
not a guarantee that every graphic or corrupted line is recognized.

Candidates cannot add C0 controls (except tab), DEL, C1 controls or replacement
characters. A MIME word labelled ASCII may fall back to Latin-1; invalid UTF-8
and unknown declarations do not get that fallback. Recognizable uuencode data
lines and complete PGP armour regions are excluded from repair. Pass the whole
text to preserve PGP context; separate per-line calls cannot retain that state.
Line endings still normalize to LF, including protected regions, so repaired
output is not a byte-preserving copy or a signature-verification input.

Values are frozen, slotted and keyword-only. Collections are tuples. Date fields
use `datetime`; the package never guesses a timezone. Unknown metadata stays
`None`. Parsed address fields remain strings; outgoing addresses use `FtnAddress`.

Control parsing retains valid unknown kludges, repeated fields and raw routing
strings. Both `parse_message` and `extract_msgid` ignore quoted examples, accept
case-insensitive kludge names and use the first MSGID. Interior nulls are preserved;
trailing nulls are removed from parsed values. `ControlLine.raw` is a text line without its
line separator, including trailing nulls; it is never original source bytes.

Repair is opt-in and returns a new value. Its confidence is a heuristic score,
not a probability. It is tuned to the PHP package's European-language fixtures,
not a general encoding detector. Repair normalizes line endings even if no line
is repaired; `changed` reports repairs only.

Synthetic IDs hash the exact UTF-8 JSON array of names, subject, date and complete
body. Consumers choose date formatting. These IDs neither prove identical source
records nor replace a supplied MSGID.

See the [complete API reference](docs/api.md), [PHP API mapping](docs/php-api.md), [contributing](CONTRIBUTING.md),
[release checks](docs/releasing.md) and [security](SECURITY.md).

## Archive reading

`ReaderOptions()` keeps strict reading. Concrete readers may support an explicit
archive mode with a required report callback:

```python
from golded_ftn import ReaderIssue, ReaderOptions

issues: list[ReaderIssue] = []
options = ReaderOptions(archive_mode=True, on_issue=issues.append)
assert options.archive_mode
```

Each `ReaderIssue` identifies the format, actual source path, record identity and
physical byte offset when known. Its action is `recovered`, `skipped` or `stopped`;
its code and detail explain the deviation without including message contents.
Multiple issues may describe one record. A recovery describes an accepted
metadata or decoding deviation; a later skip still excludes that record.
A stop means the area traversal is incomplete, even if earlier messages were
returned. Filesystem and callback failures propagate. The format package defines
the allowed recoveries; core does not read or repair files.
