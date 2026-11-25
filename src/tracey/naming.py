import json
import logging
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
SAFE_TEXT = r'[^\\/:*?"<>|\x00-\x1f]*'
DATE_PARTS = re.compile(r"YYYY|YY|MM|DD|hh|mm|ss")
DATE_FORMATS = [
    "YYYYMMDD",
    "YYYY-MM-DD",
    "YYMMDD",
    "DDMMYYYY",
    "DD.MM.YYYY",
    "YYYY",
    "YYYY-MM",
    "YYYYMMDD-hhmmss",
    "hhmmss",
]


class Kind(StrEnum):
    TEXT = "text"
    SOURCE = "source"
    FOLDER = "folder"
    COUNTER = "counter"
    DATE = "date"
    FIELD = "field"
    LIST = "list"
    JOIN = "join"

    @property
    def label(self) -> str:
        return KIND_LABELS[self]

    @property
    def per_file(self) -> bool:
        return self in (Kind.FIELD, Kind.LIST)


KIND_LABELS = {
    Kind.TEXT: "Text",
    Kind.SOURCE: "Source name",
    Kind.FOLDER: "Folder name",
    Kind.COUNTER: "Counter",
    Kind.DATE: "Date",
    Kind.FIELD: "Input field",
    Kind.LIST: "Choice list",
    Kind.JOIN: "No separator",
}


@dataclass
class Token:
    kind: Kind
    text: str = ""
    label: str = ""
    default: str = ""
    options: list[str] = field(default_factory=list[str])
    start: int = 1
    step: int = 1
    digits: int = 3
    per_name: bool = False
    format: str = "YYYYMMDD"
    file_date: bool = False

    @classmethod
    def new(cls, kind: Kind) -> Token:
        match kind:
            case Kind.TEXT:
                return cls(kind, text="")
            case Kind.FIELD:
                return cls(kind, label="Product ID")
            case Kind.LIST:
                return cls(kind, label="View", options=["front", "back", "side"])
            case _:
                return cls(kind)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Token | None:
        try:
            kind = Kind(data.get("kind"))
        except ValueError:
            return None
        token = cls(kind)
        for f in fields(cls):
            if f.name == "kind" or f.name not in data:
                continue
            value = data[f.name]
            current = getattr(token, f.name)
            if isinstance(current, bool):
                if isinstance(value, bool):
                    setattr(token, f.name, value)
            elif isinstance(current, int):
                if isinstance(value, int) and not isinstance(value, bool):
                    setattr(token, f.name, value)
            elif isinstance(current, list):
                if isinstance(value, list):
                    setattr(token, f.name, [str(v) for v in value])
            elif isinstance(value, str):
                setattr(token, f.name, value)
        return token

    def choices(self) -> list[str]:
        return [o for o in self.options if o]


@dataclass
class NamePattern:
    tokens: list[Token] = field(
        default_factory=lambda: [Token(Kind.SOURCE)],
    )
    separator: str = "_"

    def copy(self) -> NamePattern:
        return deepcopy(self)

    def inputs(self) -> list[Token]:
        seen: set[str] = set()
        found: list[Token] = []
        for token in self.tokens:
            if token.kind.per_file and token.label and token.label not in seen:
                seen.add(token.label)
                found.append(token)
        return found

    def to_json(self) -> str:
        return json.dumps(
            {
                "separator": self.separator,
                "tokens": [asdict(t) for t in self.tokens],
            }
        )

    @classmethod
    def from_json(cls, text: str) -> NamePattern:
        if not text:
            return cls()
        try:
            data = json.loads(text)
        except ValueError:
            log.warning("unreadable naming pattern, using the default")
            return cls()
        if not isinstance(data, dict):
            return cls()
        tokens = [
            token
            for item in data.get("tokens", [])
            if isinstance(item, dict) and (token := Token.from_dict(item))
        ]
        separator = data.get("separator", "_")
        return cls(tokens, separator if isinstance(separator, str) else "_")


def format_date(moment: datetime, pattern: str) -> str:
    values = {
        "YYYY": f"{moment.year:04d}",
        "YY": f"{moment.year % 100:02d}",
        "MM": f"{moment.month:02d}",
        "DD": f"{moment.day:02d}",
        "hh": f"{moment.hour:02d}",
        "mm": f"{moment.minute:02d}",
        "ss": f"{moment.second:02d}",
    }
    return DATE_PARTS.sub(lambda m: values[m.group(0)], pattern)


def file_date(source: Path, fallback: datetime) -> datetime:
    try:
        return datetime.fromtimestamp(source.stat().st_mtime)
    except OSError:
        return fallback


def sanitize(name: str) -> str:
    return FORBIDDEN.sub("-", name).strip().rstrip(". ")


def input_value(token: Token, values: Mapping[str, str]) -> str:
    if token.kind == Kind.LIST:
        choices = token.choices()
        if token.label in values:
            value = values[token.label]
            return value if value in choices else ""
        return choices[0] if choices else ""
    return values.get(token.label, "").strip() or token.default


def counter_value(token: Token, position: int) -> str:
    number = token.start + token.step * position
    sign = "-" if number < 0 else ""
    return f"{sign}{abs(number):0{max(token.digits, 1)}d}"


@dataclass
class Job:
    source: Path
    pattern: NamePattern
    values: Mapping[str, str]


def fixed_parts(job: Job, now: datetime) -> list[str | None]:
    parts: list[str | None] = []
    for token in job.pattern.tokens:
        match token.kind:
            case Kind.TEXT:
                parts.append(token.text)
            case Kind.SOURCE:
                parts.append(job.source.stem)
            case Kind.FOLDER:
                parts.append(job.source.parent.name)
            case Kind.DATE:
                moment = file_date(job.source, now) if token.file_date else now
                parts.append(format_date(moment, token.format))
            case Kind.FIELD | Kind.LIST:
                parts.append(input_value(token, job.values))
            case Kind.COUNTER:
                parts.append(None)
            case Kind.JOIN:
                parts.append("")
    return parts


def join(tokens: Sequence[Token], parts: Sequence[str], separator: str) -> str:
    name = ""
    joined = False
    for token, part in zip(tokens, parts):
        if token.kind == Kind.JOIN:
            joined = True
        elif part:
            name += part if not name or joined else separator + part
            joined = False
    return name


def resolve(jobs: Sequence[Job], now: datetime) -> list[str]:
    counts: dict[tuple[str, ...], int] = {}
    names: list[str] = []
    for job in jobs:
        parts = fixed_parts(job, now)
        has_counter = any(p is None for p in parts)
        per_name = any(
            t.kind == Kind.COUNTER and t.per_name for t in job.pattern.tokens
        )
        position = 0
        if has_counter:
            key = (job.pattern.to_json(),)
            if per_name:
                key += tuple(p for p in parts if p is not None)
            position = counts.get(key, 0)
            counts[key] = position + 1
        filled = [
            counter_value(token, position) if part is None else part
            for token, part in zip(job.pattern.tokens, parts)
        ]
        joined = join(job.pattern.tokens, filled, job.pattern.separator)
        names.append(sanitize(joined) or job.source.stem)
    return names
