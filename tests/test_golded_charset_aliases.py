import pytest

from golded_ftn import detect_charset, to_utf8


@pytest.mark.parametrize(
    "alias", ["CP-866", "+7FIDO", "+7_FIDO", "FIDO7", "FIDO_7", "RUS"]
)
@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
def test_historical_dos_cyrillic_aliases(alias: str, field: str) -> None:
    # Literal CP866 bytes for Привет, including a lowercase letter outside 0x80–AF.
    payload = b"\x8f\xe0\xa8\xa2\xa5\xe2"
    charset = detect_charset(f"\x01{field}: {alias.lower()} 2\r".encode() + payload)
    assert charset == "CP866"
    assert to_utf8(payload, charset) == "Привет"


@pytest.mark.parametrize("alias", ["KOI", "KOI8", "GOST", "CP20866"])
@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
def test_historical_koi8_aliases(alias: str, field: str) -> None:
    # KOI8-R has a different Cyrillic ordering from CP866 and CP1251.
    payload = b"\xf0\xd2\xc9\xd7\xc5\xd4"
    charset = detect_charset(f"\x01{field}: {alias.lower()} 2\r".encode() + payload)
    assert charset == "KOI8-R"
    assert to_utf8(payload, charset) == "Привет"


@pytest.mark.parametrize("alias", ["WIN", "WIN-1251", "WINDOWS-1251", "CP-1251"])
@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
def test_historical_windows_cyrillic_aliases(alias: str, field: str) -> None:
    payload = b"\xcf\xf0\xe8\xe2\xe5\xf2"
    charset = detect_charset(f"\x01{field}: {alias.lower()} 2\r".encode() + payload)
    assert charset == "CP1251"
    assert to_utf8(payload, charset) == "Привет"


@pytest.mark.parametrize(
    ("alias", "expected"),
    [("+7_FIDO", "CP866"), ("GOST", "KOI8-R"), ("WIN", "CP1251")],
)
def test_historical_aliases_work_as_configured_fallbacks(
    alias: str, expected: str
) -> None:
    assert detect_charset(b"Body", alias) == expected
    assert detect_charset(b"\x01CHRS: UNKNOWN 2\rBody", alias) == expected
    assert detect_charset(b"\x01CHRS: CP437 2\rBody", alias) == "CP437"


def test_declarations_keep_priority_over_mime_and_later_kludges() -> None:
    body = (
        b"Content-Type: text/plain; charset=windows-1251\r"
        b"\x01CHRS: GOST 2\r\x01CHARSET: WIN 2\r"
    )
    assert detect_charset(body) == "KOI8-R"
    assert detect_charset(b"Content-Type: text/plain; charset=windows-1251") == "CP850"
    assert detect_charset(b"\x01CHRS: IBMPC 2") == "CP850"
    assert detect_charset(b"\x01CHRS: UNKNOWN 2", "CP437") == "CP437"


@pytest.mark.parametrize("alias", ["KOI8-U", "KOI8U", "KOU", "KOI-U", "CP21866"])
@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
def test_ukrainian_koi8_aliases(alias: str, field: str) -> None:
    # Literal bytes from Unicode's KOI8-U mapping, including all Ukrainian letters.
    payload = b"\xbd\xad\xb4\xa4\xb6\xa6\xb7\xa7"
    charset = detect_charset(f"\x01{field}: {alias.lower()} 2\r".encode() + payload)
    assert charset == "KOI8-U"
    assert to_utf8(payload, charset) == "ҐґЄєІіЇї"


@pytest.mark.parametrize("alias", ["CP1125", "UKR"])
@pytest.mark.parametrize("field", ["CHRS", "CHARSET"])
def test_ukrainian_dos_aliases(alias: str, field: str) -> None:
    # CP1125's Ukrainian extension occupies F2–F9, unlike CP866.
    payload = b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9"
    charset = detect_charset(f"\x01{field}: {alias.lower()} 2\r".encode() + payload)
    assert charset == "CP1125"
    assert to_utf8(payload, charset) == "ҐґЄєІіЇї"
