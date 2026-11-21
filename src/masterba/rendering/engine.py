"""Render a stored document into a workbook (spec 02 sections 1-3). No I/O besides the shell."""

from collections.abc import Sequence
from copy import copy
from datetime import datetime
from enum import Enum
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import IllegalCharacterError
from openpyxl.worksheet.worksheet import Worksheet

from masterba.models import (
    PAYLOAD_BY_TYPE,
    Document,
    Payload,
    PayloadItem,
    TestSpecContent,
    payload_items,
)
from masterba.rendering.bindings import (
    HEADER_SOURCES,
    ListBinding,
    MaxCellLength,
    NonEmptyTable,
    TableBinding,
)
from masterba.rendering.context import EMPTY_CONTEXT, RenderContext
from masterba.rendering.errors import InvalidTemplateError, RenderValidationError
from masterba.rendering.formatting import CellValue, format_value
from masterba.rendering.template import ResolvedTemplate

CREATOR = "MasterBA"
FIXED_TIME = datetime(2000, 1, 1)


def _put(ws: Worksheet, ref: str, value: CellValue) -> None:
    cell: Any = ws[ref]
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"  # never let Excel parse user text as a formula


def _matches(item: PayloadItem, where: dict[str, str]) -> bool:
    for key, expected in where.items():
        actual = getattr(item, key)
        if (actual.value if isinstance(actual, Enum) else str(actual)) != expected:
            return False
    return True


def _list_rows(source: str, content: Payload, context: RenderContext) -> Sequence[object]:
    if source == "$revisions":
        return context.revisions
    if source == "$trace":
        return context.trace
    return content.exclusions if isinstance(content, TestSpecContent) else ()


def _render_table(
    ws: Worksheet,
    table: TableBinding | ListBinding,
    rows: Sequence[object],
    value_maps: dict[str, dict[str, str]],
) -> tuple[int, int]:
    """Write one table; return (row count, longest text length)."""
    columns = [c.col for c in table.columns]
    if table.numbering is not None:
        columns.append(table.numbering.column)
    styles = {col: copy(ws[f"{col}{table.start_row}"]._style) for col in columns}
    longest = 0
    for offset, item in enumerate(rows):
        row = table.start_row + offset
        for col in columns:
            cell: Any = ws[f"{col}{row}"]
            cell._style = copy(styles[col])
        if table.numbering is not None:
            _put(ws, f"{table.numbering.column}{row}", offset + 1)
        for column in table.columns:
            if column.field is None:
                continue
            value_map = value_maps[column.value_map] if column.value_map else None
            value = format_value(column.field, getattr(item, column.field), value_map)
            _put(ws, f"{column.col}{row}", value)
            if isinstance(value, str):
                longest = max(longest, len(value))
    return len(rows), longest


def render_document(
    doc: Document,
    content: Payload,
    template: ResolvedTemplate,
    context: RenderContext | None = None,
) -> Workbook:
    """Fill the template's shell with `content`; raises `RenderError` subclasses on failure.

    `context` supplies the cover, revision history and traceability (spec 19); without it
    those cells stay empty.
    """
    ctx = context or EMPTY_CONTEXT
    if template.definition.doc_type is not doc.type:
        raise InvalidTemplateError(
            f"template is for {template.definition.doc_type}, not {doc.type}"
        )
    if not isinstance(content, PAYLOAD_BY_TYPE[doc.type]):
        raise RenderValidationError(f"payload {type(content).__name__} does not fit {doc.type}")
    wb = load_workbook(template.shell_path)
    names = template.sheet_map
    missing = sorted(name for name in names.values() if name not in wb.sheetnames)
    if missing:
        raise InvalidTemplateError(f"shell {template.shell_path.name} lacks sheets {missing}")
    try:
        value_maps = template.bindings.value_maps
        for head in template.bindings.header:
            raw = HEADER_SOURCES[head.source](doc, ctx)
            value = format_value(head.source, raw, value_maps.get(head.value_map or ""))
            _put(wb[names[head.sheet]], head.cell, value)
        items = payload_items(content)
        counts: dict[str, int] = {}
        longest = 0
        for table in template.bindings.tables:
            matched = [item for item in items if _matches(item, table.where)]
            count, width = _render_table(wb[names[table.sheet]], table, matched, value_maps)
            counts[table.sheet] = counts.get(table.sheet, 0) + count
            longest = max(longest, width)
        for listed in template.bindings.lists:
            rows = _list_rows(listed.source, content, ctx)
            _, width = _render_table(wb[names[listed.sheet]], listed, rows, value_maps)
            longest = max(longest, width)
    except IllegalCharacterError as exc:
        raise RenderValidationError(f"content has a character Excel cannot store: {exc}") from exc
    for rule in template.rules:
        if isinstance(rule, MaxCellLength) and longest > rule.limit:
            raise RenderValidationError(f"a cell has {longest} characters; limit is {rule.limit}")
        if isinstance(rule, NonEmptyTable) and counts.get(rule.table, 0) == 0:
            raise RenderValidationError(f"table {rule.table!r} has no rows")
    wb.properties.creator = CREATOR
    wb.properties.lastModifiedBy = CREATOR
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    return wb
