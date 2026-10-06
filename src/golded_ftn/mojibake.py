import re
from collections import Counter
from dataclasses import dataclass
from email.header import decode_header

from .charset import _resolve_charset

_VISIBLE = ("CP850", "CP437", "CP865", "ISO-8859-1", "Windows-1252")
_INTENDED = ("UTF-8", "ISO-8859-1", "Windows-1252", "CP850")
_DAMAGE = ("Ã", "Â", "â", "�", "°", "÷", "õ", "Õ", "┼", "▀", "³")
_LITERAL_DEGREE = re.compile(r"([0-9][ \t]*°|°[ \t]*[CF](?![A-Za-z]))")
_PROTECTED = re.compile(r"([0-9][ \t]*°|°[ \t]*[CF](?![A-Za-z])|[\u2500-\u259f]+)")
_PLAUSIBLE = "åæøäöüßÅÆØÄÖÜ"
_WORDS = ("møde", "för", "daß", "müßte", "gehört", "geändert", "ændret", "på", "ikke")


@dataclass(frozen=True, slots=True, kw_only=True)
class MojibakeRepairResult:
    """Confidence is a heuristic score, not a probability."""

    text: str
    changed: bool
    confidence: float


def _score(text: str) -> float:
    damage = sum(
        _LITERAL_DEGREE.sub("", text).count("°") if c == "°" else text.count(c)
        for c in _DAMAGE
    )
    damage += len(re.findall(r"[A-Za-z]µ(?=[A-Za-z])", text))
    return (
        -2.5 * damage
        + 1.5 * sum(text.count(c) for c in _PLAUSIBLE)
        + 2.0 * sum(w in text.lower() for w in _WORDS)
    )


def _unsafe_characters(text: str) -> Counter[str]:
    return Counter(
        char
        for char in text
        if (ord(char) < 32 and char != "\t")
        or 127 <= ord(char) <= 159
        or char == "\ufffd"
    )


def _reencode(line: str, visible: str, intended: str, *, framed: bool = False) -> str:
    framed = framed or any(
        "\u2500" <= char <= "\u259f" and char not in "┼▀" for char in line
    )
    if intended == "UTF-8":
        try:
            return "".join(
                part if index % 2 else part.encode(visible).decode(intended)
                for index, part in enumerate(_LITERAL_DEGREE.split(line))
            )
        except UnicodeError:
            pass
    if any(char in _PLAUSIBLE for char in line):
        words = re.split(r"(\s+)", line)
        for index, word in enumerate(words):
            if (
                not any(char in _PLAUSIBLE for char in word)
                and re.search(r"[A-Za-z]", word)
                and (any(char in _DAMAGE for char in word) or "µ" in word)
            ):
                candidate = _reencode(word, visible, intended, framed=framed)
                if _score(candidate) - _score(word) >= 2.5:
                    words[index] = candidate
        return "".join(words)
    # Isolated glyphs inside words can be damaged letters; frames and art are not.
    parts: list[str] = []
    offset = 0
    for match in _PROTECTED.finditer(line):
        parts.append(line[offset : match.start()].encode(visible).decode(intended))
        part = match[0]
        neighbors = (
            line[max(0, match.start() - 1) : match.start()]
            + line[match.end() : match.end() + 1]
        )
        damaged_letter = (
            not framed
            and part in {"┼", "▀"}
            and any(char.isascii() and char.isalpha() for char in neighbors)
        )
        parts.append(part.encode(visible).decode(intended) if damaged_letter else part)
        offset = match.end()
    parts.append(line[offset:].encode(visible).decode(intended))
    return "".join(parts)


def _decode_mime_part(part: bytes | str, charset: str | None) -> str:
    if isinstance(part, str):
        return part
    codec = charset or "ascii"
    try:
        return part.decode(codec)
    except UnicodeDecodeError:
        if codec.lower().replace("_", "-") not in {"ascii", "us-ascii"}:
            raise
        # Old gateways sometimes labelled Latin-1 bytes as ASCII.
        return part.decode("latin-1")


def _repair_line(line: str, declared: str | None, prefer: bool) -> MojibakeRepairResult:
    if line and 32 <= ord(line[0]) <= 96:
        byte_count = (ord(line[0]) - 32) & 63
        if (
            byte_count > 0
            and len(line) == 1 + 4 * ((byte_count + 2) // 3)
            and all(32 <= ord(char) <= 96 for char in line[1:])
        ):
            return MojibakeRepairResult(text=line, changed=False, confidence=0.0)
    if re.search(r"=\?.+\?[QB]\?.+\?=", line, re.IGNORECASE):
        try:
            decoded = "".join(
                _decode_mime_part(part, charset)
                for part, charset in decode_header(line)
            )
            if decoded != line and not (
                _unsafe_characters(decoded) - _unsafe_characters(line)
            ):
                return MojibakeRepairResult(text=decoded, changed=True, confidence=0.95)
        except (LookupError, UnicodeError, ValueError):
            pass
    best_text, best_score = line, 0.0
    if not line.isascii():
        encodings: tuple[str, ...] = ()
        if declared and declared.strip():
            try:
                token = re.split(r"[\s\x00\x01]", declared.strip(), maxsplit=1)[0]
                encodings = (_resolve_charset(token),)
            except LookupError:
                pass
        for visible in dict.fromkeys(encodings + _VISIBLE):
            for intended in dict.fromkeys(encodings + _INTENDED):
                if visible == intended:
                    continue
                try:
                    # Strict round trips exclude candidates that lose characters.
                    candidate = _reencode(line, visible, intended)
                except (LookupError, UnicodeError):
                    continue
                if (
                    intended != "UTF-8"
                    and len(line.strip()) > 1
                    and not any(
                        (char.isascii() and char.isalpha()) or char in _PLAUSIBLE
                        for char in line
                    )
                ):
                    continue
                if _unsafe_characters(candidate) - _unsafe_characters(line):
                    continue
                score = _score(candidate) - _score(line)
                if score > best_score:
                    best_text, best_score = candidate, score
    if best_score < (1.5 if prefer else 2.5):
        return MojibakeRepairResult(text=line, changed=False, confidence=0.0)
    return MojibakeRepairResult(
        text=best_text, changed=True, confidence=min(0.9, 0.4 + best_score / 10)
    )


def repair_mojibake(
    text: str, declared_charset: str | None = None, prefer_quoted_lines: bool = True
) -> MojibakeRepairResult:
    lines = re.split(r"\r\n|\n|\r", text)
    results: list[MojibakeRepairResult] = []
    armour_end: str | None = None
    for line in lines:
        begin = re.fullmatch(
            r"-----BEGIN PGP (SIGNED MESSAGE|MESSAGE|SIGNATURE|"
            r"PUBLIC KEY BLOCK|PRIVATE KEY BLOCK)-----",
            line,
        )
        if armour_end is None and begin:
            kind = "SIGNATURE" if begin[1] == "SIGNED MESSAGE" else begin[1]
            armour_end = f"-----END PGP {kind}-----"
        if armour_end is not None:
            results.append(
                MojibakeRepairResult(text=line, changed=False, confidence=0.0)
            )
            if line == armour_end:
                armour_end = None
        else:
            results.append(
                _repair_line(
                    line,
                    declared_charset,
                    prefer_quoted_lines
                    and bool(re.match(r"^\s*[A-Za-z0-9]{0,4}>", line)),
                )
            )
    changed = any(r.changed for r in results)
    return MojibakeRepairResult(
        text="\n".join(r.text for r in results),
        changed=changed,
        confidence=min(1.0, sum(r.confidence for r in results) / len(results))
        if changed
        else 0.0,
    )
