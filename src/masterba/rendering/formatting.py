"""Cell value formatting (spec 02 section 2.3)."""

from collections.abc import Mapping
from enum import Enum

CellValue = str | int | None

NUMBERED_FIELDS = frozenset({"steps"})


def _text(value: object, value_map: Mapping[str, str] | None) -> str:
    raw = value.value if isinstance(value, Enum) else str(value)
    raw = str(raw)
    return value_map.get(raw, raw) if value_map else raw


def format_value(
    field: str, value: object, value_map: Mapping[str, str] | None = None
) -> CellValue:
    """Convert one payload field value into what a cell holds."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, list | tuple):
        if not value:
            return None
        parts = [_text(v, value_map) for v in value]
        if field in NUMBERED_FIELDS:
            parts = [f"{n}. {part}" for n, part in enumerate(parts, start=1)]
        return "\n".join(parts)
    return _text(value, value_map)
