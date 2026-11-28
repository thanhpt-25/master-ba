"""The document as the default workbook prints it, as JSON for the dashboard (spec 19 section 14).

Built from the same catalog and render context as the shells, with no model and no write, so the
browser shows the text a reviewer would read in Excel. Columns without a field (判定, 実施日, ...)
are hand-entry columns and are left out.
"""

from typing import Any

from masterba.models import Document, Payload, payload_items, payload_sections
from masterba.rendering.bindings import HEADER_SOURCES
from masterba.rendering.catalog import (
    COVER_ROWS,
    JUDGEMENT_CHOICES,
    NOT_RUN,
    SECTION_EMPTY,
    TOTAL,
    VALUE_MAPS,
    DocSpec,
    SheetSpec,
    doc_spec,
)
from masterba.rendering.context import DOC_TITLES, RenderContext
from masterba.rendering.engine import _list_rows, _matches, field_value
from masterba.rendering.formatting import format_value


def _text(field: str, value: object, value_map: str | None) -> str:
    cell = format_value(field, value, VALUE_MAPS.get(value_map or ""))
    return "" if cell is None else str(cell)


def _table(sheet: SheetSpec, rows: list[object], context: RenderContext) -> dict[str, Any]:
    columns = [c for c in sheet.columns if c.field is not None]
    return {
        "key": sheet.key,
        "name": sheet.name,
        "kind": "table",
        "note": sheet.note,
        "columns": [c.header for c in columns],
        "rows": [
            [
                _text(c.field, field_value(row, c.field, context), c.value_map)
                for c in columns
                if c.field
            ]
            for row in rows
        ],
    }


def _fixed(sheet: SheetSpec, columns: list[str], rows: list[list[str]]) -> dict[str, Any]:
    return {
        "key": sheet.key,
        "name": sheet.name,
        "kind": "table",
        "note": sheet.note,
        "columns": columns,
        "rows": rows,
    }


def _toc(spec: DocSpec, sheet: SheetSpec) -> dict[str, Any]:
    rows = [[str(n), s.name, s.summary] for n, s in enumerate(spec.sheets, start=1)]
    return _fixed(sheet, ["No.", "シート名", "記載内容"], rows)


def _progress(sheet: SheetSpec, cases: int) -> dict[str, Any]:
    """Judgements are entered in Excel, so a stored document has every case 未実施."""
    rows = [[label, "0"] for label in JUDGEMENT_CHOICES]
    rows += [[NOT_RUN, str(cases)], [TOTAL, str(cases)]]
    return _fixed(sheet, ["判定", "件数"], rows)


def preview_sheets(doc: Document, content: Payload, context: RenderContext) -> list[dict[str, Any]]:
    spec = doc_spec(doc.type)
    items = payload_items(content)
    written = {s.key: s for s in payload_sections(content)}
    sheets: list[dict[str, Any]] = []
    for sheet in spec.sheets:
        if sheet.is_cover:
            rows = [
                [label, _text(source, HEADER_SOURCES[source](doc, context), value_map)]
                for label, source, value_map in COVER_ROWS
            ]
            sheets.append(
                {
                    "key": sheet.key,
                    "name": sheet.name,
                    "kind": "cover",
                    "title": DOC_TITLES[doc.type],
                    "rows": rows,
                }
            )
        elif sheet.section is not None:
            section = written.get(sheet.section)
            sheets.append(
                {
                    "key": sheet.key,
                    "name": sheet.name,
                    "kind": "section",
                    "body": section.body if section else None,
                    "sources": list(section.sources) if section else [],
                    "empty_text": SECTION_EMPTY,
                }
            )
        elif sheet.is_toc:
            sheets.append(_toc(spec, sheet))
        elif sheet.is_progress:
            cases = spec.sheet("cases")
            sheets.append(_progress(sheet, sum(_matches(i, dict(cases.where)) for i in items)))
        elif sheet.is_placeholder:
            sheets.append(
                {"key": sheet.key, "name": sheet.name, "kind": "note", "note": sheet.note}
            )
        elif sheet.source is not None:
            listed: list[object] = list(_list_rows(sheet.source, content, context))
            sheets.append(_table(sheet, listed, context))
        else:
            where = dict(sheet.where)
            sheets.append(_table(sheet, [i for i in items if _matches(i, where)], context))
    return sheets
