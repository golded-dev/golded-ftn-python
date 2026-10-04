import hashlib
import json


def parse_body(text: str) -> str:
    return text.rstrip("\x00").replace("\r\n", "\n").replace("\r", "\n")


def read_null_padded_field(raw: bytes, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0:
        raise ValueError("offset and length must be non-negative")
    return raw[offset : offset + length].split(b"\x00", 1)[0]


def synthetic_id(
    from_name: str, to_name: str, subject: str, date: str | None, body: str
) -> str:
    payload = json.dumps(
        [from_name, to_name, subject, date, body],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "hash:sha256:" + hashlib.sha256(payload).hexdigest()
