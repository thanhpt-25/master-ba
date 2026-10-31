"""Generate `templates/default/` from the catalog.

Run `PYTHONPATH=src uv run python -m masterba.rendering.shells` after editing `catalog.py`;
a test fails when the committed files differ from what this module generates.
"""

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from masterba.models import TemplateDefinition
from masterba.models.enums import TemplateSource
from masterba.rendering.bindings import (
    EXCEL_MAX_CELL_LENGTH,
    Bindings,
    ColumnBinding,
    HeaderBinding,
    NumberingBinding,
    TableBinding,
)
from masterba.rendering.catalog import (
    CATALOG,
    FIRST_ROW,
    HEADER_BLOCK,
    HEADER_ROW,
    NOTE_ROW,
    NUMBER_COL,
    VALUE_MAPS,
    DocSpec,
    SheetSpec,
)
from masterba.rendering.xlsxio import workbook_bytes

DEFAULT_DIR = Path("templates/default")
COMPANY_ID = "default"
FONT = "Meiryo"
_SIDE = Side(style="thin", color="999999")
_BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
_HEAD_FILL = PatternFill("solid", start_color="DDE6F0")
_LABEL_FILL = PatternFill("solid", start_color="F2F2F2")


def _build_sheet(wb: Workbook, sheet: SheetSpec) -> None:
    ws = wb.create_sheet(sheet.name)
    ws["A1"] = sheet.name
    ws["A1"].font = Font(name=FONT, size=14, bold=True)
    for offset, (label, _) in enumerate(HEADER_BLOCK):
        cell = ws.cell(row=2 + offset, column=1, value=label)
        cell.font = Font(name=FONT, size=10, bold=True)
        cell.fill = _LABEL_FILL
        cell.border = _BORDER
        ws.cell(row=2 + offset, column=2).border = _BORDER
    ws.column_dimensions[NUMBER_COL].width = 14
    if sheet.is_placeholder:
        ws.cell(row=HEADER_ROW, column=1, value=sheet.note).font = Font(name=FONT, size=10)
        return
    if sheet.note:
        ws.cell(row=NOTE_ROW, column=1, value=sheet.note).font = Font(
            name=FONT, size=9, italic=True
        )
    headers = ["No.", *[c.header for c in sheet.columns]]
    for index, header in enumerate(headers, start=1):
        head = ws.cell(row=HEADER_ROW, column=index, value=header)
        head.font = Font(name=FONT, size=10, bold=True)
        head.fill = _HEAD_FILL
        head.border = _BORDER
        head.alignment = Alignment(wrap_text=True, vertical="center")
        sample = ws.cell(row=FIRST_ROW, column=index)
        sample.font = Font(name=FONT, size=10)
        sample.border = _BORDER
        sample.alignment = Alignment(wrap_text=True, vertical="top")
    for index, column in enumerate(sheet.columns, start=2):
        ws.column_dimensions[get_column_letter(index)].width = max(
            column.width, 14 if index == 2 else 0
        )
    ws.freeze_panes = f"A{FIRST_ROW}"


def build_shell(spec: DocSpec) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]
    for sheet in spec.sheets:
        _build_sheet(wb, sheet)
    return wb


def _table(sheet: SheetSpec) -> TableBinding:
    columns = [
        ColumnBinding(col=get_column_letter(i), field=c.field, value_map=c.value_map)
        for i, c in enumerate(sheet.columns, start=2)
    ]
    return TableBinding(
        sheet=sheet.key,
        start_row=FIRST_ROW,
        where=dict(sheet.where),
        numbering=NumberingBinding(column=NUMBER_COL),
        columns=columns,
    )


def build_definition(spec: DocSpec) -> TemplateDefinition:
    header = [
        HeaderBinding(sheet=sheet.key, cell=f"B{2 + offset}", source=source)
        for sheet in spec.sheets
        for offset, (_, source) in enumerate(HEADER_BLOCK)
    ]
    tables = [_table(sheet) for sheet in spec.sheets if not sheet.is_placeholder]
    bindings = Bindings(header=header, tables=tables, value_maps=VALUE_MAPS)
    return TemplateDefinition(
        company_id=COMPANY_ID,
        doc_type=spec.doc_type,
        source=TemplateSource.BASELINE,
        sheet_map={sheet.key: sheet.name for sheet in spec.sheets},
        cell_bindings=bindings.model_dump(mode="json"),
        validation_rules=[{"rule": "max_cell_length", "limit": EXCEL_MAX_CELL_LENGTH}],
    )


def definition_json(definition: TemplateDefinition) -> str:
    data = definition.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_default_templates(directory: Path = DEFAULT_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in CATALOG:
        name = spec.doc_type.value
        json_path = directory / f"{name}.template.json"
        json_path.write_text(definition_json(build_definition(spec)), encoding="utf-8")
        xlsx_path = directory / f"{name}.xlsx"
        xlsx_path.write_bytes(workbook_bytes(build_shell(spec)))
        written.extend([json_path, xlsx_path])
    return written


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    for path in write_default_templates(target):
        print(path)


if __name__ == "__main__":
    main()
