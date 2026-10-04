from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlLine:
    name: str
    value: str
    raw: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FtnAddress:
    zone: int
    net: int
    node: int
    point: int | None = None
    domain: str | None = None

    @classmethod
    def try_from_string(cls, value: str) -> FtnAddress | None:
        match = re.fullmatch(
            r"([0-9]+):([0-9]+)/([0-9]+)(?:\.([0-9]+))?(?:@([A-Za-z0-9][A-Za-z0-9._-]*))?",
            value.strip(),
        )
        if match is None:
            return None
        zone, net, node, point, domain = match.groups()
        return cls(
            zone=int(zone),
            net=int(net),
            node=int(node),
            point=int(point) if point is not None else None,
            domain=domain,
        )

    @classmethod
    def from_string(cls, value: str) -> FtnAddress:
        address = cls.try_from_string(value)
        if address is None:
            raise ValueError(f"Invalid FTN address [{value}].")
        return address

    def __str__(self) -> str:
        value = f"{self.zone}:{self.net}/{self.node}"
        if self.point is not None:
            value += f".{self.point}"
        if self.domain is not None:
            value += f"@{self.domain}"
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageControlLines:
    kludges: tuple[ControlLine, ...] = ()
    msgid: str | None = None
    reply: str | None = None
    charset: str | None = None
    seen_by: tuple[str, ...] = ()
    path: tuple[str, ...] = ()
    tearline: str | None = None
    origin: str | None = None
    origin_address: FtnAddress | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kludges", tuple(self.kludges))
        object.__setattr__(self, "seen_by", tuple(self.seen_by))
        object.__setattr__(self, "path", tuple(self.path))


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageProvenance:
    source_type: str
    source_path: str | None = None
    source_id: str | None = None
    source_offset: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageSource:
    source_type: str
    path: str
    code: str
    name: str
    sort_order: int = 0
    meta_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OutgoingMessage:
    from_name: str
    to_name: str
    subject: str
    body_text: str
    external_id: str | None = None
    from_address: FtnAddress | None = None
    to_address: FtnAddress | None = None
    posted_at: datetime | None = None
    attributes_raw: int | None = None
    control_lines: tuple[ControlLine, ...] = ()
    provenance: MessageProvenance | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "control_lines", tuple(self.control_lines))


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedArea:
    code: str
    name: str
    source_type: str
    sort_order: int = 0
    meta_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedMessage:
    msgno: int
    from_name: str
    to_name: str
    subject: str
    body_text: str
    attributes_raw: int
    posted_at: datetime | None = None
    external_id: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    reply_to_msgno: int | None = None
    reply1st_msgno: int | None = None
    reply_next_msgno: int | None = None
    area_code: str | None = None
    area_name: str | None = None
    area_sort_order: int | None = None
    area_meta_key: str | None = None
    control_lines: MessageControlLines | None = None
    provenance: MessageProvenance | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReaderOptions:
    fallback_charset: str = "CP850"


@dataclass(frozen=True, slots=True, kw_only=True)
class WriterOptions:
    target_charset: str = "CP850"


class ParserException(RuntimeError):
    """A concrete reader could not parse its source."""
