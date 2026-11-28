"""Generate `templates/default/` from the catalog.

Run `PYTHONPATH=src uv run python -m masterba.rendering.shells` after editing `catalog.py`;
a test fails when the committed files differ from what this module generates.
"""

import json
import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from masterba.models import TemplateDefinition
from masterba.models.enums import TemplateSource
from masterba.rendering.bindings import (
    EXCEL_MAX_CELL_LENGTH,
    Bindings,
    ColumnBinding,
    HeaderBinding,
    ListBinding,
    NumberingBinding,
    SectionBinding,
    TableBinding,
)
from masterba.rendering.catalog import (
    BAND_COLUMNS,
    BAND_MIN_WIDTH,
    CATALOG,
    COVER_FIRST_ROW,
    COVER_NOTE,
    COVER_ROWS,
    COVER_STAMPS,
    COVER_SYSTEM_CELL,
    COVER_TITLE_CELL,
    FIRST_ROW,
    HEADER_BAND,
    HEADER_ROW,
    JUDGEMENT_CHOICES,
    JUDGEMENT_HEADER,
    LAST_ROW,
    NOT_RUN,
    NOTE_ROW,
    NUMBER_COL,
    PROGRESS_HEADERS,
    SECTION_BODY_CELL,
    SECTION_BODY_HEADER,
    SECTION_EMPTY,
    SECTION_SOURCES_CELL,
    SECTION_SOURCES_HEADER,
    SECTION_SOURCES_HEADER_ROW,
    TITLE_CELL,
    TOTAL,
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
_THICK = Side(style="medium", color="1F3864")
TOC_HEADERS = ("No.", "シート名", "記載内容")
_CENTER_TOP = Alignment(horizontal="center", vertical="top")
FOOTER_LEFT = "&F"
FOOTER_RIGHT = "ページ &P / &N"


def _print_setup(ws: Worksheet, title_rows: str | None) -> None:
    """A4 landscape, one page wide, header row repeated, file name and page in the footer."""
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_options.horizontalCentered = True
    if title_rows:
        ws.print_title_rows = title_rows
    footer: Any = ws.oddFooter
    footer.left.text = FOOTER_LEFT
    footer.left.size = 8
    footer.right.text = FOOTER_RIGHT
    footer.right.size = 8


def _build_cover(wb: Workbook, sheet: SheetSpec) -> None:
    ws = wb.create_sheet(sheet.name)
    ws.sheet_view.showGridLines = False
    for col, width in (("A", 4), ("B", 18), ("C", 44), ("D", 4), ("E", 12), ("F", 12), ("G", 12)):
        ws.column_dimensions[col].width = width
    title = ws[COVER_TITLE_CELL]
    title.font = Font(name=FONT, size=26, bold=True, color="1F3864")
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[title.row].height = 48
    for col in "BCDEFG":
        ws[f"{col}{title.row + 1}"].border = Border(bottom=_THICK)
    ws[COVER_SYSTEM_CELL].font = Font(name=FONT, size=14, color="1F3864")
    for offset, (label, _, _) in enumerate(COVER_ROWS):
        row = COVER_FIRST_ROW + offset
        head = ws.cell(row=row, column=2, value=label)
        head.font = Font(name=FONT, size=11, bold=True)
        head.fill = _LABEL_FILL
        head.border = _BORDER
        value = ws.cell(row=row, column=3)
        value.font = Font(name=FONT, size=11)
        value.border = _BORDER
        value.alignment = Alignment(horizontal="left")
        ws.row_dimensions[row].height = 22
    for index, stamp in enumerate(COVER_STAMPS, start=5):
        head = ws.cell(row=COVER_FIRST_ROW, column=index, value=stamp)
        head.font = Font(name=FONT, size=10, bold=True)
        head.fill = _HEAD_FILL
        head.border = _BORDER
        head.alignment = Alignment(horizontal="center")
        for row in range(COVER_FIRST_ROW + 1, COVER_FIRST_ROW + 4):
            ws.cell(row=row, column=index).border = _BORDER
    note_row = COVER_FIRST_ROW + len(COVER_ROWS) + 2
    ws.cell(row=note_row, column=2, value=COVER_NOTE).font = Font(name=FONT, size=9, italic=True)
    _print_setup(ws, None)


def _merge_band_width(ws: Worksheet, ref: str) -> None:
    row = ws[ref].row
    ws.merge_cells(f"{BAND_COLUMNS[0]}{row}:{BAND_COLUMNS[-1]}{row}")


def _build_section(ws: Worksheet) -> None:
    """A prose sheet: a wide merged cell for the body, then its sources."""
    for row, label in (
        (HEADER_ROW, SECTION_BODY_HEADER),
        (SECTION_SOURCES_HEADER_ROW, SECTION_SOURCES_HEADER),
    ):
        head = ws.cell(row=row, column=1, value=label)
        head.font = Font(name=FONT, size=10, bold=True)
        head.fill = _HEAD_FILL
        head.border = _BORDER
        _merge_band_width(ws, head.coordinate)
    for ref, size in ((SECTION_BODY_CELL, 10.5), (SECTION_SOURCES_CELL, 9)):
        cell = ws[ref]
        cell.font = Font(name=FONT, size=size)
        cell.border = _BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        _merge_band_width(ws, ref)
    _print_setup(ws, None)


def _build_toc(ws: Worksheet, spec: DocSpec) -> None:
    """目次: one fixed row per sheet of the workbook."""
    _head_row(ws, TOC_HEADERS)
    for offset, sheet in enumerate(spec.sheets):
        row = FIRST_ROW + offset
        entries: tuple[int | str, ...] = (offset + 1, sheet.name, sheet.summary)
        for index, entry in enumerate(entries, start=1):
            cell = ws.cell(row=row, column=index, value=entry)
            cell.font = Font(name=FONT, size=10)
            cell.border = _BORDER
        ws.cell(row=row, column=1).alignment = _CENTER_TOP
    for letter, width in (("B", 28), ("C", 60)):
        ws.column_dimensions[letter].width = width
    _print_setup(ws, f"{HEADER_ROW}:{HEADER_ROW}")


def _quoted(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _build_progress(ws: Worksheet, spec: DocSpec) -> None:
    """消化状況: judgement counts by fixed formulas over the 判定 column of the cases sheet."""
    cases = spec.sheet("cases")
    headers = [c.header for c in cases.columns]
    judgement = get_column_letter(headers.index(JUDGEMENT_HEADER) + 2)
    case_id = get_column_letter(2)
    source = _quoted(cases.name)
    _head_row(ws, PROGRESS_HEADERS)
    labels = (*JUDGEMENT_CHOICES, NOT_RUN, TOTAL)
    total_row = FIRST_ROW + len(labels) - 1
    for offset, label in enumerate(labels):
        row = FIRST_ROW + offset
        if label == TOTAL:
            count = f"=COUNTA({source}!${case_id}${FIRST_ROW}:${case_id}${LAST_ROW})"
        elif label == NOT_RUN:
            count = f"=C{total_row}-SUM(C{FIRST_ROW}:C{row - 1})"
        else:
            span = f"${judgement}${FIRST_ROW}:${judgement}${LAST_ROW}"
            count = f"=COUNTIF({source}!{span},B{row})"
        ratio = f'=IF($C${total_row}=0,"",C{row}/$C${total_row})'
        number: int | None = None if label == TOTAL else offset + 1
        values: tuple[int | str | None, ...] = (number, label, count, ratio)
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = Font(name=FONT, size=10, bold=label == TOTAL)
            cell.border = _BORDER
        ws.cell(row=row, column=4).number_format = "0.0%"
        ws.cell(row=row, column=1).alignment = _CENTER_TOP
    _print_setup(ws, None)


def _head_row(ws: Worksheet, headers: tuple[str, ...] | list[str]) -> None:
    for index, header in enumerate(headers, start=1):
        head = ws.cell(row=HEADER_ROW, column=index, value=header)
        head.font = Font(name=FONT, size=10, bold=True)
        head.fill = _HEAD_FILL
        head.border = _BORDER
        head.alignment = Alignment(wrap_text=True, vertical="center")


def _build_band(ws: Worksheet, sheet: SheetSpec) -> None:
    """Sheet title in A1 and the header band at rows 2 and 3 (spec 26 section 1)."""
    ws[TITLE_CELL] = sheet.name
    ws[TITLE_CELL].font = Font(name=FONT, size=14, bold=True)
    for band in HEADER_BAND:
        label = ws[f"{band.label_col}{band.row}"]
        label.value = band.label
        label.font = Font(name=FONT, size=9, bold=True)
        label.fill = _LABEL_FILL
        label.border = _BORDER
        value = ws[f"{band.value_col}{band.row}"]
        value.font = Font(name=FONT, size=9)
        value.border = _BORDER
        value.alignment = Alignment(shrink_to_fit=True, vertical="center")
        if band.source is None:
            value.value = sheet.name


def _band_widths(ws: Worksheet) -> None:
    for col in BAND_COLUMNS:
        dimension = ws.column_dimensions[col]
        dimension.width = max(dimension.width or 0, BAND_MIN_WIDTH)


def _add_judgement_list(ws: Worksheet, sheet: SheetSpec) -> None:
    headers = [c.header for c in sheet.columns]
    if JUDGEMENT_HEADER not in headers:
        return
    col = get_column_letter(headers.index(JUDGEMENT_HEADER) + 2)
    choices = ",".join(JUDGEMENT_CHOICES)
    check = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True)
    check.add(f"{col}{FIRST_ROW}:{col}{LAST_ROW}")
    ws.add_data_validation(check)


def _build_sheet(wb: Workbook, spec: DocSpec, sheet: SheetSpec) -> None:
    if sheet.is_cover:
        _build_cover(wb, sheet)
        return
    ws = wb.create_sheet(sheet.name)
    _build_band(ws, sheet)
    ws.column_dimensions[NUMBER_COL].width = 6
    if sheet.is_toc:
        _build_toc(ws, spec)
    elif sheet.is_progress:
        _build_progress(ws, spec)
    elif sheet.is_placeholder:
        ws.cell(row=HEADER_ROW, column=1, value=sheet.note).font = Font(name=FONT, size=10)
        _print_setup(ws, None)
    elif sheet.section is not None:
        _build_section(ws)
    else:
        _build_table(ws, sheet)
    _band_widths(ws)


def _build_table(ws: Worksheet, sheet: SheetSpec) -> None:
    if sheet.note:
        ws.cell(row=NOTE_ROW, column=1, value=sheet.note).font = Font(
            name=FONT, size=9, italic=True
        )
    headers = ["No.", *[c.header for c in sheet.columns]]
    _head_row(ws, headers)
    for index in range(1, len(headers) + 1):
        sample = ws.cell(row=FIRST_ROW, column=index)
        sample.font = Font(name=FONT, size=10)
        sample.border = _BORDER
        sample.alignment = Alignment(wrap_text=True, vertical="top")
    ws.cell(row=FIRST_ROW, column=1).alignment = _CENTER_TOP
    for index, column in enumerate(sheet.columns, start=2):
        ws.column_dimensions[get_column_letter(index)].width = column.width
    ws.freeze_panes = f"A{FIRST_ROW}"
    _add_judgement_list(ws, sheet)
    _print_setup(ws, f"{HEADER_ROW}:{HEADER_ROW}")


def build_shell(spec: DocSpec) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]
    for sheet in spec.sheets:
        _build_sheet(wb, spec, sheet)
    return wb


def _columns(sheet: SheetSpec) -> list[ColumnBinding]:
    return [
        ColumnBinding(col=get_column_letter(i), field=c.field, value_map=c.value_map)
        for i, c in enumerate(sheet.columns, start=2)
    ]


def _table(sheet: SheetSpec) -> TableBinding:
    return TableBinding(
        sheet=sheet.key,
        start_row=FIRST_ROW,
        where=dict(sheet.where),
        numbering=NumberingBinding(column=NUMBER_COL),
        columns=_columns(sheet),
    )


def _list(sheet: SheetSpec) -> ListBinding:
    return ListBinding.model_validate(
        {
            "sheet": sheet.key,
            "start_row": FIRST_ROW,
            "source": sheet.source,
            "numbering": NumberingBinding(column=NUMBER_COL),
            "columns": _columns(sheet),
        }
    )


def _header(sheet: SheetSpec) -> list[HeaderBinding]:
    if sheet.is_cover:
        rows = [
            HeaderBinding(
                sheet=sheet.key,
                cell=f"C{COVER_FIRST_ROW + offset}",
                source=source,
                value_map=value_map,
            )
            for offset, (_, source, value_map) in enumerate(COVER_ROWS)
        ]
        return [
            HeaderBinding(sheet=sheet.key, cell=COVER_TITLE_CELL, source="$document.title"),
            HeaderBinding(sheet=sheet.key, cell=COVER_SYSTEM_CELL, source="$project.name"),
            *rows,
        ]
    return [
        HeaderBinding(
            sheet=sheet.key,
            cell=f"{band.value_col}{band.row}",
            source=band.source,
            value_map=band.value_map,
        )
        for band in HEADER_BAND
        if band.source is not None
    ]


def build_definition(spec: DocSpec) -> TemplateDefinition:
    header = [binding for sheet in spec.sheets for binding in _header(sheet)]
    tables = [_table(s) for s in spec.sheets if s.columns and s.source is None]
    lists = [_list(s) for s in spec.sheets if s.columns and s.source is not None]
    sections = [
        SectionBinding(
            sheet=s.key,
            key=s.section,
            body_cell=SECTION_BODY_CELL,
            sources_cell=SECTION_SOURCES_CELL,
            empty_text=SECTION_EMPTY,
        )
        for s in spec.sheets
        if s.section is not None
    ]
    bindings = Bindings(
        header=header, tables=tables, lists=lists, sections=sections, value_maps=VALUE_MAPS
    )
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
