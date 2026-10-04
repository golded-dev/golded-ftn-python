import re

from .models import ControlLine, FtnAddress, MessageControlLines


def extract_msgid(text: str) -> str | None:
    """Return the first unquoted MSGID using the message parser's rules."""
    return parse_message(text).msgid


def parse_message(text: str) -> MessageControlLines:
    kludges: list[ControlLine] = []
    seen_by: list[str] = []
    path: list[str] = []
    msgid = reply = charset = tearline = origin = None
    origin_address = None
    for raw in re.split(r"\r\n|\r|\n", text):
        line = raw.rstrip("\x00")
        if not line or re.match(r"^\s*(?:>|[A-Za-z0-9]{1,6}>)", line):
            continue
        if line.startswith("\x01"):
            match = re.fullmatch(r"\x01([A-Za-z][A-Za-z0-9-]*):\s*(.*)", line)
            if match:
                control = ControlLine(
                    name=match[1].upper(), value=match[2].strip(), raw=raw
                )
                kludges.append(control)
                if control.name == "MSGID" and msgid is None:
                    msgid = control.value
                elif control.name == "REPLY" and reply is None:
                    reply = control.value
                elif control.name in ("CHRS", "CHARSET") and charset is None:
                    charset = control.value
            continue
        match = re.fullmatch(r"(SEEN-BY|PATH):\s*(.*)", line)
        if match:
            (seen_by if match[1] == "SEEN-BY" else path).append(match[2].strip())
        elif line.startswith("---"):
            if tearline is None:
                tearline = line
        elif re.match(r"^\s\* Origin:\s*(.*)$", line):
            if origin is None:
                origin = line.split("Origin:", 1)[1].strip()
            address = re.search(r"\(([^()]+)\)\s*$", line)
            if origin_address is None and address:
                origin_address = FtnAddress.try_from_string(address[1])
    return MessageControlLines(
        kludges=tuple(kludges),
        msgid=msgid,
        reply=reply,
        charset=charset,
        seen_by=tuple(seen_by),
        path=tuple(path),
        tearline=tearline,
        origin=origin,
        origin_address=origin_address,
    )
