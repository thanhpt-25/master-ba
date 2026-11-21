"""The document as the default workbook prints it, as JSON for the dashboard (spec 19 section 14).

Built from the same catalog and render context as the shells, with no model and no write, so the
browser shows the text a reviewer would read in Excel. Columns without a field (判定, 実施日, ...)
are hand-entry columns and are left out.
"""

from typing import Any

from masterba.models import Document, Payload, payload_items, payload_sections
from masterba.rendering.bindings import HEADER_SOURCES
from masterba.rendering.catalog import CATALOG, COVER_ROWS, SECTION_EMPTY, VALUE_MAPS, SheetSpec
from masterba.rendering.context import DOC_TITLES, RenderContext
from masterba.rendering.engine import _list_rows, _matches
from masterba.rendering.formatting import format_value


def _text(field: str, value: object, value_map: str | None) -> str:
    cell = format_value(field, value, VALUE_MAPS.get(value_map or ""))
    return "" if cell is None else str(cell)


def _table(sheet: SheetSpec, rows: list[object]) -> dict[str, Any]:
    columns = [c for c in sheet.columns if c.field is not None]
    return {
        "key": sheet.key,
        "name": sheet.name,
        "kind": "table",
        "note": sheet.note,
        "columns": [c.header for c in columns],
        "rows": [
            [_text(c.field, getattr(row, c.field), c.value_map) for c in columns if c.field]
            for row in rows
        ],
    }


def preview_sheets(doc: Document, content: Payload, context: RenderContext) -> list[dict[str, Any]]:
    spec = next(s for s in CATALOG if s.doc_type is doc.type)
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
        elif sheet.is_placeholder:
            sheets.append(
                {"key": sheet.key, "name": sheet.name, "kind": "note", "note": sheet.note}
            )
        elif sheet.source is not None:
            sheets.append(_table(sheet, list(_list_rows(sheet.source, content, context))))
        else:
            where = dict(sheet.where)
            sheets.append(_table(sheet, [i for i in items if _matches(i, where)]))
    return sheets
