import pytest

from golded_ftn import detect_charset, extract_msgid, parse_message, repair_mojibake


@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
@pytest.mark.parametrize("suffix", [b"\x00", b"\x00\x00", b" 2\x00", b"\x01X: y"])
@pytest.mark.parametrize(
    ("alias", "expected"),
    [("UTF-8", "UTF-8"), ("LATIN-1", "ISO-8859-1"), ("CP850", "CP850")],
)
def test_charset_token_boundaries(
    field: str, suffix: bytes, alias: str, expected: str
) -> None:
    assert (
        detect_charset(f"\x01{field}: {alias}".encode() + suffix, "CP437") == expected
    )


@pytest.mark.parametrize(
    ("alias", "expected"), [("KOI8R", "KOI8-R"), ("IBMPC", "CP850"), ("IBM", "CP850")]
)
def test_fallback_aliases(alias: str, expected: str) -> None:
    assert detect_charset(b"Body", alias) == expected
    assert detect_charset(b"\x01CHRS: UNKNOWN", alias) == expected
    assert detect_charset(b"\x01CHRS: CP437", alias) == "CP437"


@pytest.mark.parametrize("body", [b"Body", b"\x01CHRS: CP850", b"\x01CHRS: UNKNOWN"])
def test_invalid_fallback_always_fails(body: bytes) -> None:
    with pytest.raises(LookupError):
        detect_charset(body, "NOT-A-CODEC")


@pytest.mark.parametrize(
    ("alias", "canonical", "original"),
    [
        ("KOI8R", "KOI8-R", "Привет"),
        ("IBMPC", "CP850", "Bruger møde"),
        ("IBM", "CP850", "Bruger møde"),
    ],
)
def test_repair_declared_alias(alias: str, canonical: str, original: str) -> None:
    damaged = original.encode("utf-8").decode(canonical)
    result = repair_mojibake(damaged, alias)
    assert result == repair_mojibake(damaged, canonical)
    assert result.text == original
    assert result.changed


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\x01msgid: abc", "abc"),
        ("\x01MsGiD: abc", "abc"),
        ("> \x01MSGID: quoted", None),
        ("OD> \x01MSGID: quoted\n\x01MSGID: actual", "actual"),
        ("\x01MSGID: first\n\x01MSGID: second", "first"),
        ("\x01MSGID:\n\x01MSGID: second", ""),
        ("\x01MSGID: foo\x00bar", "foo\x00bar"),
        ("\x01MSGID: foo\x00\x00", "foo"),
        ("Body \x01MSGID: embedded", None),
        ("\x01MSGID: foo\x01", "foo\x01"),
        ("Body", None),
    ],
)
def test_shared_msgid_rules(text: str, expected: str | None) -> None:
    assert extract_msgid(text) == parse_message(text).msgid == expected
