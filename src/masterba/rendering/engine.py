"""Render a stored document into a workbook (spec 02 sections 1-3). No I/O besides the shell."""

from collections.abc import Sequence
from copy import copy
from datetime import datetime
from enum import Enum
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Side
from openpyxl.utils.exceptions import IllegalCharacterError
from openpyxl.worksheet.worksheet import Worksheet

from masterba.models import (
    PAYLOAD_BY_TYPE,
    Document,
    Payload,
    PayloadItem,
    TestSpecContent,
    payload_items,
    payload_sections,
)
from masterba.rendering.bindings import (
    CODE_FIELD,
    HEADER_SOURCES,
    VERIFIES_NAME_FIELD,
    ListBinding,
    MaxCellLength,
    NonEmptyTable,
    TableBinding,
)
from masterba.rendering.codes import display_code
from masterba.rendering.context import EMPTY_CONTEXT, RenderContext
from masterba.rendering.errors import InvalidTemplateError, RenderValidationError
from masterba.rendering.finish import finish_workbook
from masterba.rendering.formatting import CellValue, format_value
from masterba.rendering.template import ResolvedTemplate

CREATOR = "MasterBA"
FIXED_TIME = datetime(2000, 1, 1)


def _put(ws: Worksheet, ref: str, value: CellValue) -> None:
    cell: Any = ws[ref]
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"  # never let Excel parse user text as a formula


_SIDE = Side(style="thin", color="808080")
GRID = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
_WRAP_TOP = Alignment(wrap_text=True, vertical="top")


def _has_border(cell: Cell) -> bool:
    border = cell.border
    sides = (getattr(border, side, None) for side in ("left", "right", "top", "bottom"))
    return any(side is not None and side.style for side in sides)


def _frame_header(ws: Worksheet, ref: str) -> None:
    """Border a bare label/value pair: a header cell with no border whose left cell is a label.

    A cell without a label to its left (a cover title) or with any border (an underline) is
    left as the template designed it (spec 28 section 2).
    """
    cell: Any = ws[ref]
    if cell.column == 1 or _has_border(cell):
        return
    label: Any = ws.cell(row=cell.row, column=cell.column - 1)
    if not isinstance(label.value, str) or not label.value.strip():
        return
    cell.border = GRID
    if not _has_border(label):
        label.border = GRID


DATE_FIELDS = frozenset({"date", "approved_on", "asked_on"})
DATE_WIDTH = 11.0
DEFAULT_WIDTH = 8.43


def _fit_label(ws: Worksheet, ref: str) -> None:
    """Shrink a label left of a header cell when it is wider than its column (spec 28)."""
    cell: Any = ws[ref]
    if cell.column == 1:
        return
    label: Any = ws.cell(row=cell.row, column=cell.column - 1)
    if not isinstance(label.value, str):
        return
    letter = label.column_letter
    known = letter in ws.column_dimensions  # reading creates a dimension, so look first
    width = (ws.column_dimensions[letter].width if known else None) or DEFAULT_WIDTH
    if _display_width(label.value) + 1 > width:
        label.alignment = Alignment(
            horizontal=label.alignment.horizontal,
            vertical=label.alignment.vertical or "center",
            shrink_to_fit=True,
        )


def _date_widths(ws: Worksheet, table: TableBinding | ListBinding) -> None:
    """A date column at least wide enough for YYYY/MM/DD on one line."""
    for column in table.columns:
        if column.field in DATE_FIELDS:
            dimension = ws.column_dimensions[column.col]
            dimension.width = max(dimension.width or DEFAULT_WIDTH, DATE_WIDTH)


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
    if source == "$questions":
        return context.questions
    return content.exclusions if isinstance(content, TestSpecContent) else ()


def field_value(row: object, name: str, context: RenderContext) -> object:
    """A row's field, or a derived item field (`$code`, `$verifies_name`, spec 27)."""
    if name == CODE_FIELD and isinstance(row, PayloadItem):
        return display_code(row)
    if name == VERIFIES_NAME_FIELD:
        verifies = getattr(row, "verifies", None) or []
        return context.names.get(verifies[0]) if verifies else None
    return getattr(row, name)


# A merged section cell does not grow with its text in Excel, so its height is set from the
# text: about this many half-width characters fit on one line of the merged width.
SECTION_LINE_WIDTH = 120
LINE_HEIGHT = 15
MAX_ROW_HEIGHT = 409


def _display_width(text: str) -> int:
    return sum(1 if ord(ch) < 0x2E80 else 2 for ch in text)


def text_height(text: str | None) -> float | None:
    """Row height (points) for `text` in a merged section cell; None keeps the default."""
    if not text:
        return None
    lines = sum(max(1, -(-_display_width(line) // SECTION_LINE_WIDTH)) for line in text.split("\n"))
    return float(min(MAX_ROW_HEIGHT, lines * LINE_HEIGHT + 6))


def _render_table(
    ws: Worksheet,
    table: TableBinding | ListBinding,
    rows: Sequence[object],
    value_maps: dict[str, dict[str, str]],
    context: RenderContext,
) -> tuple[int, int]:
    """Write one table; return (row count, longest text length)."""
    columns = [c.col for c in table.columns]
    if table.numbering is not None:
        columns.append(table.numbering.column)
    styles = {col: copy(ws[f"{col}{table.start_row}"]._style) for col in columns}
    _date_widths(ws, table)
    # A first data row without borders still prints as a grid (spec 28 section 2).
    bare = {col for col in columns if not _has_border(ws[f"{col}{table.start_row}"])}
    longest = 0
    for offset, item in enumerate(rows):
        row = table.start_row + offset
        for col in columns:
            cell: Any = ws[f"{col}{row}"]
            cell._style = copy(styles[col])
            if col in bare:
                cell.border = GRID
                cell.alignment = _WRAP_TOP
        if table.numbering is not None:
            _put(ws, f"{table.numbering.column}{row}", offset + 1)
        for column in table.columns:
            if column.field is None:
                continue
            value_map = value_maps[column.value_map] if column.value_map else None
            raw = field_value(item, column.field, context)
            value = format_value(column.field, raw, value_map)
            _put(ws, f"{column.col}{row}", value)
            if isinstance(value, str):
                longest = max(longest, len(value))
    return len(rows), longest


def _fit_merged(ws: Worksheet, ref: str, text: str | None) -> None:
    """Size the row of a merged cell to its text; a plain cell grows by itself in Excel."""
    if not any(ref in merged for merged in ws.merged_cells.ranges):
        return
    height = text_height(text)
    if height is not None:
        ws.row_dimensions[ws[ref].row].height = height


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
            _frame_header(wb[names[head.sheet]], head.cell)
            _fit_label(wb[names[head.sheet]], head.cell)
        items = payload_items(content)
        counts: dict[str, int] = {}
        longest = 0
        for table in template.bindings.tables:
            matched = [item for item in items if _matches(item, table.where)]
            count, width = _render_table(wb[names[table.sheet]], table, matched, value_maps, ctx)
            counts[table.sheet] = counts.get(table.sheet, 0) + count
            longest = max(longest, width)
        written = {s.key: s for s in payload_sections(content)}
        for binding in template.bindings.sections:
            ws = wb[names[binding.sheet]]
            section = written.get(binding.key)
            body = section.body if section else binding.empty_text
            _put(ws, binding.body_cell, body)
            _fit_merged(ws, binding.body_cell, body)
            longest = max(longest, len(body or ""))
            if binding.sources_cell is not None:
                sources = "\n".join(section.sources) if section else None
                _put(ws, binding.sources_cell, sources)
                _fit_merged(ws, binding.sources_cell, sources)
        for listed in template.bindings.lists:
            rows = _list_rows(listed.source, content, ctx)
            _, width = _render_table(wb[names[listed.sheet]], listed, rows, value_maps, ctx)
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
    return finish_workbook(wb)
