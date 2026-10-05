import re
from dataclasses import dataclass
from email.header import decode_header

from .charset import _resolve_charset

_VISIBLE = ("CP850", "CP437", "CP865", "ISO-8859-1", "Windows-1252")
_INTENDED = ("UTF-8", "ISO-8859-1", "Windows-1252", "CP850")
_DAMAGE = ("Ã", "Â", "â", "�", "°", "÷", "õ", "Õ", "┼", "▀", "³")
_LITERAL_DEGREE = re.compile(r"([0-9][ \t]*°|°[ \t]*[CF](?![A-Za-z]))")
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
    return (
        -2.5 * damage
        + 1.5 * sum(text.count(c) for c in _PLAUSIBLE)
        + 2.0 * sum(w in text.lower() for w in _WORDS)
    )


def _repair_line(line: str, declared: str | None, prefer: bool) -> MojibakeRepairResult:
    if re.search(r"=\?.+\?[QB]\?.+\?=", line, re.IGNORECASE):
        try:
            decoded = "".join(
                part.decode(charset or "ascii") if isinstance(part, bytes) else part
                for part, charset in decode_header(line)
            )
            if decoded != line:
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
                    candidate = "".join(
                        part if index % 2 else part.encode(visible).decode(intended)
                        for index, part in enumerate(_LITERAL_DEGREE.split(line))
                    )
                except (LookupError, UnicodeError):
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
    results = [
        _repair_line(
            line,
            declared_charset,
            prefer_quoted_lines and bool(re.match(r"^\s*[A-Za-z0-9]{0,4}>", line)),
        )
        for line in lines
    ]
    changed = any(r.changed for r in results)
    return MojibakeRepairResult(
        text="\n".join(r.text for r in results),
        changed=changed,
        confidence=min(1.0, sum(r.confidence for r in results) / len(results))
        if changed
        else 0.0,
    )
