# golded-ftn

Shared FTN message values, reader/writer protocols and text helpers for Python
3.12+. No runtime dependencies. No concrete format readers, writers, database
access or Nornir integration.

This package has not been published. Build and install a local wheel:

```sh
uv sync --locked
uv build
python -m pip install dist/golded_ftn-1.0.0-py3-none-any.whl
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

See [PHP API mapping](docs/php-api.md), [contributing](CONTRIBUTING.md),
[release checks](docs/releasing.md) and [security](SECURITY.md).
