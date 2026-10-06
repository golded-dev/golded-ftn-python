import codecs
import re
from typing import Literal

DecodeErrors = Literal["strict", "replace", "ignore"]
_ALIASES = {
    "CP850": "CP850",
    "IBM850": "CP850",
    "IBMPC": "CP850",
    "IBM": "CP850",
    "LATIN-1": "ISO-8859-1",
    "LATIN1": "ISO-8859-1",
    "8859-1": "ISO-8859-1",
    "ISO-8859-1": "ISO-8859-1",
    "ISO8859-1": "ISO-8859-1",
    "ASCII": "ASCII",
    "USASCII": "ASCII",
    "CP866": "CP866",
    "IBM866": "CP866",
    "CP-866": "CP866",
    "+7FIDO": "CP866",
    "+7_FIDO": "CP866",
    "FIDO7": "CP866",
    "FIDO_7": "CP866",
    "RUS": "CP866",
    "KOI8-R": "KOI8-R",
    "KOI8R": "KOI8-R",
    "KOI": "KOI8-R",
    "KOI8": "KOI8-R",
    "GOST": "KOI8-R",
    "CP20866": "KOI8-R",
    "KOI8-U": "KOI8-U",
    "KOI8U": "KOI8-U",
    "KOU": "KOI8-U",
    "KOI-U": "KOI8-U",
    "CP21866": "KOI8-U",
    "CP1125": "CP1125",
    "UKR": "CP1125",
    "CP437": "CP437",
    "IBM437": "CP437",
    "CP1251": "CP1251",
    "WIN": "CP1251",
    "WIN-1251": "CP1251",
    "WINDOWS-1251": "CP1251",
    "CP-1251": "CP1251",
    "CP1252": "CP1252",
    "CP1250": "CP1250",
    "LATIN-2": "ISO-8859-2",
    "ISO-8859-2": "ISO-8859-2",
    "UTF-8": "UTF-8",
    "UTF8": "UTF-8",
}


def _resolve_charset(name: str) -> str:
    resolved = _ALIASES.get(name.upper(), name)
    codecs.lookup(resolved)
    return resolved


def detect_charset(raw_body: bytes, fallback: str = "CP850") -> str:
    """Read the first declaration; always validate the configured fallback."""
    fallback = _resolve_charset(fallback)
    match = re.search(
        rb"\x01(?:CHRS|CHARSET):\s*([^\s\x00\x01]+)", raw_body, re.IGNORECASE
    )
    if match is None:
        return fallback
    declared = _ALIASES.get(match[1].decode("ascii", errors="replace").upper())
    return _resolve_charset(declared) if declared is not None else fallback


def to_utf8(
    value: bytes, charset: str = "CP850", *, errors: DecodeErrors = "strict"
) -> str:
    """Decode bytes to Python Unicode after removing trailing null padding."""
    if errors not in ("strict", "replace", "ignore"):
        raise ValueError(f"Unsupported decode error policy: {errors}")
    return value.rstrip(b"\x00").decode(charset, errors=errors)
