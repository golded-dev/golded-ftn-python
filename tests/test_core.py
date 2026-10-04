import hashlib
import json
import re
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import UTC
from pathlib import Path

import pytest

import golded_ftn as f


@pytest.mark.parametrize(
    "value",
    [
        "2:236/77",
        "2:236/77.1",
        "2:236/77@fidonet",
        "2:236/77.1@fidonet",
        "0:0/0.0@a_B-1.x",
    ],
)
def test_address(value: str) -> None:
    assert str(f.FtnAddress.from_string(" " + value + " ")) == value


@pytest.mark.parametrize(
    "value", ["236/77", "2:236", "2:3/4@", "2:3/4x", "٢:3/4", "2:3/4\nBAD"]
)
def test_invalid_address(value: str) -> None:
    assert f.FtnAddress.try_from_string(value) is None
    with pytest.raises(ValueError):
        f.FtnAddress.from_string(value)


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("IBMPC", "CP850"),
        ("LATIN-1", "ISO-8859-1"),
        ("KOI8R", "KOI8-R"),
        ("IBM866", "CP866"),
        ("UTF8", "UTF-8"),
        ("FIDOMAZ", "CP437"),
    ],
)
@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
def test_charset(alias: str, expected: str, field: str) -> None:
    assert (
        f.detect_charset(f"\x01{field}: {alias.lower()} 2\nBody".encode(), "CP437")
        == expected
    )


def test_byte_boundaries() -> None:
    assert f.detect_charset(b"Hello") == "CP850"
    assert f.to_utf8(b"m\x9bde\x00\x00") == "møde"
    assert f.read_null_padded_field(b"xxA \x00Bxx", 2, 4) == b"A "
    assert f.read_null_padded_field(b"abc", 20, 3) == b""
    assert f.read_null_padded_field(b"abc", 0, 2) == b"ab"
    with pytest.raises(ValueError):
        f.read_null_padded_field(b"abc", -1, 2)
    with pytest.raises(UnicodeDecodeError):
        f.to_utf8(b"\xff", "UTF-8")
    assert f.to_utf8(b"\xff", "UTF-8", errors="replace") == "�"
    assert f.to_utf8(b"\xff", "UTF-8", errors="ignore") == ""
    with pytest.raises(LookupError):
        f.detect_charset(b"\x01CHRS: CP850", "nonsense")
    with pytest.raises(LookupError):
        f.to_utf8(b"a", "nonsense")
    with pytest.raises(TypeError):
        f.detect_charset("text")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        f.parse_body(b"bytes")  # type: ignore[arg-type]
    assert f.parse_body("\x01MSGID: x\r\ny\rz\x00") == "\x01MSGID: x\ny\nz"


def test_control_lines() -> None:
    raw = "\x01msgid: first\x00\x00"
    c = f.parse_message(
        "\r\n".join(
            [
                raw,
                "\x01MSGID: second",
                "\x01REPLY: r1",
                "\x01REPLY: r2",
                "\x01CHRS: LATIN-1 2",
                "\x01CHARSET: UTF-8",
                "\x01X-UNKNOWN: v",
                "\x011BAD: no",
                "SEEN-BY: 236/77 100 101",
                "SEEN-BY: 2:236/77",
                "PATH: 236/77 100/1",
                "--- First",
                "--- Second",
                " * Origin: First board (2:236/77.1@fidonet)",
                " * Origin: Second board (2:236/78)",
            ]
        )
    )
    assert len(c.kludges) == 7
    assert c.kludges[0].raw == raw
    assert c.kludges[-1].name == "X-UNKNOWN"
    assert (c.msgid, c.reply, c.charset) == ("first", "r1", "LATIN-1 2")
    assert c.seen_by == ("236/77 100 101", "2:236/77")
    assert c.path == ("236/77 100/1",)
    assert c.tearline == "--- First"
    assert c.origin == "First board (2:236/77.1@fidonet)"
    assert str(c.origin_address) == "2:236/77.1@fidonet"
    assert f.parse_message(" * Origin: Local echo (236/77)").origin_address is None
    assert f.parse_message("\x01CHARSET: UTF-8").charset == "UTF-8"
    assert f.parse_message(
        " * Origin: First (236/77)\n * Origin: Next (2:236/78)"
    ).origin_address == f.FtnAddress.from_string("2:236/78")


def test_quoted_controls() -> None:
    c = f.parse_message(
        "> SEEN-BY: 236/77\n"
        "OD> PATH: 236/77\nABCD12> \x01MSGID: quoted\n"
        ">  * Origin: Quoted (2:236/77)\nSEEN-BY: 236/100"
    )
    assert c.msgid is c.origin is None
    assert c.path == ()
    assert c.seen_by == ("236/100",)


@pytest.mark.parametrize("terminator", ["\r", "\n", "\x00", ""])
def test_extract_msgid(terminator: str) -> None:
    assert (
        f.extract_msgid("\x01MSGID: 2:236/77 abc123" + terminator) == "2:236/77 abc123"
    )
    assert f.extract_msgid("Body") is None


@pytest.mark.parametrize(
    ("damaged", "repaired"),
    [
        ("Bruger m°de", "Bruger møde"),
        (
            "Uppgradering av min nyckel f÷r GoldED",
            "Uppgradering av min nyckel för GoldED",
        ),
        (
            "imageclub: K° pÕ indkommende mail til mail.image.dk (┼ben)",
            "imageclub: Kø på indkommende mail til mail.image.dk (Åben)",
        ),
        ("AB> da▀", "AB> daß"),
        ("AB> m³▀te", "AB> müßte"),
        ("AB> geh÷rt", "AB> gehört"),
        ("AB> geõndert", "AB> geändert"),
        ("AB> ³berflogen", "AB> überflogen"),
        ("SÃ¥dan gÃ¸r vi", "Sådan gør vi"),
        ("=?ISO-8859-1?Q?Bruger_m=F8de?=", "Bruger møde"),
        ("=?UTF-8?B?bcO4ZGU=?=", "møde"),
    ],
)
def test_repair(damaged: str, repaired: str) -> None:
    original = damaged
    result = f.repair_mojibake(damaged)
    assert result.text == repaired
    assert result.changed and 0 < result.confidence <= 1
    assert damaged == original


@pytest.mark.parametrize(
    "text",
    [
        "Hello world",
        "Bruger møde på lørdag",
        "Price 10°",
        "",
        "=?UNKNOWN?Q?abc?=",
        "Snowman ☃",
    ],
)
def test_no_repair(text: str) -> None:
    result = f.repair_mojibake(text)
    assert result.text == text
    assert not result.changed and result.confidence == 0


def test_repair_options() -> None:
    assert f.repair_mojibake("Bruger m°de", "IBMPC").text == "Bruger møde"
    assert f.repair_mojibake("Bruger m°de", "UNKNOWN").text == "Bruger møde"
    assert f.repair_mojibake("A\r\nB\r").text == "A\nB\n"
    assert not f.repair_mojibake("A\r\nB").changed
    assert f.repair_mojibake("AB> ³", prefer_quoted_lines=False).changed


def test_identity() -> None:
    payload = ["Å\x00", "Bob", "Hello", None, "a" * 201]
    expected = (
        "hash:sha256:"
        + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert f.synthetic_id("Å\x00", "Bob", "Hello", None, "a" * 201) == expected
    assert f.synthetic_id("a", "b", "c", None, "x" * 201) != f.synthetic_id(
        "a", "b", "c", None, "x" * 200 + "y"
    )
    assert f.synthetic_id("a", "b", "c", None, "") != f.synthetic_id(
        "a", "b", "c", "", ""
    )
    assert f.synthetic_id("a", "b", "c", None, "\r") != f.synthetic_id(
        "a", "b", "c", None, "\n"
    )


def test_values() -> None:
    assert (
        f.ReaderOptions().fallback_charset
        == f.WriterOptions().target_charset
        == "CP850"
    )
    value = f.MessageControlLines()
    assert value.kludges == ()
    assert value.seen_by == value.path == ()
    with pytest.raises(FrozenInstanceError):
        value.msgid = "oops"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")
    message = f.ParsedMessage(
        msgno=1,
        from_name="A",
        to_name="B",
        subject="C",
        body_text="D",
        attributes_raw=0,
    )
    assert message.posted_at is None
    assert message.provenance is None
    assert message.from_address is None
    assert f.ParsedArea(code="A", name="Area", source_type="fake").sort_order == 0
    assert f.MessageProvenance(source_type="fake").source_offset is None
    assert issubclass(f.ParserException, RuntimeError)
    for name in f.__all__:
        public = getattr(f, name)
        if isinstance(public, type) and is_dataclass(public):
            assert public.__dataclass_params__.frozen  # type: ignore[attr-defined]
            assert all(field.kw_only for field in fields(public))


def test_readme() -> None:
    readme = Path(__file__).parents[1] / "README.md"
    namespace: dict[str, object] = {}
    for example in re.findall(r"```python\n(.*?)```", readme.read_text(), re.DOTALL):
        exec(compile(example, str(readme), "exec"), namespace)


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("CP850", "CP850"),
        ("IBM850", "CP850"),
        ("IBM", "CP850"),
        ("LATIN1", "ISO-8859-1"),
        ("8859-1", "ISO-8859-1"),
        ("ISO-8859-1", "ISO-8859-1"),
        ("ISO8859-1", "ISO-8859-1"),
        ("ASCII", "ASCII"),
        ("USASCII", "ASCII"),
        ("CP866", "CP866"),
        ("KOI8-R", "KOI8-R"),
        ("CP437", "CP437"),
        ("IBM437", "CP437"),
        ("CP1251", "CP1251"),
        ("CP1252", "CP1252"),
        ("CP1250", "CP1250"),
        ("LATIN-2", "ISO-8859-2"),
        ("ISO-8859-2", "ISO-8859-2"),
        ("UTF-8", "UTF-8"),
    ],
)
def test_remaining_aliases(alias: str, expected: str) -> None:
    assert f.detect_charset(f"\x01CHRS: {alias} 2".encode()) == expected


def test_collection_input_is_detached() -> None:
    routing = ["236/77"]
    c = f.MessageControlLines(seen_by=routing)  # type: ignore[arg-type]
    routing.append("100")
    assert c.seen_by == ("236/77",)
    kludges = [f.ControlLine(name="X", value="Y", raw="\x01X: Y")]
    outgoing = f.OutgoingMessage(
        from_name="A",
        to_name="B",
        subject="C",
        body_text="D",
        control_lines=kludges,  # type: ignore[arg-type]
    )
    kludges.clear()
    assert len(outgoing.control_lines) == 1


def test_datetime_is_not_guessed() -> None:
    from datetime import datetime

    for date in (datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC)):
        message = f.OutgoingMessage(
            from_name="A", to_name="B", subject="C", body_text="D", posted_at=date
        )
        assert message.posted_at is date
