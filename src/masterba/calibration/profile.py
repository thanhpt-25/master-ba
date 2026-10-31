"""Read the structure of a sample workbook without executing anything (spec 09 section 2)."""

import zipfile
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from masterba.calibration.heuristic import (
    VALUE_MAP_FIELDS,
    doc_info_source,
    fields_for,
    is_numbering,
    match_field,
)
from masterba.calibration.models import (
    ColumnMap,
    HeaderCell,
    MappingDraft,
    SheetProfile,
    TableMap,
    WorkbookProfile,
)
from masterba.models.enums import DocType

MAX_BYTES = 5_000_000
HEADER_SEARCH_ROWS = 15
PROFILE_ROWS = 40
PROFILE_COLUMNS = 40


class CalibrationError(Exception):
    """The sample or the mapping cannot be used (message is meant for the user)."""


def check_sample(path: Path) -> None:
    """Refuse anything that is not a plain, small `.xlsx` before parsing it."""
    if path.suffix.lower() != ".xlsx":
        raise CalibrationError("the sample must be an .xlsx file (not .xlsm, .xls or others)")
    if not path.is_file():
        raise CalibrationError(f"{path.name} does not exist")
    if path.stat().st_size > MAX_BYTES:
        raise CalibrationError(f"the sample is larger than {MAX_BYTES // 1_000_000} MB")
    if not zipfile.is_zipfile(path):
        raise CalibrationError("the file is not an Excel workbook")


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def row_texts(ws: Worksheet, row: int, columns: int) -> list[str]:
    return [_text(ws.cell(row=row, column=c).value) for c in range(1, columns + 1)]


def find_header_row(ws: Worksheet, fields: set[str]) -> tuple[int | None, int]:
    """The row among the first ones that looks most like a table header: (row, recognised)."""
    columns = min(ws.max_column, PROFILE_COLUMNS)
    best: tuple[int, int, int] | None = None
    for row in range(1, min(ws.max_row, HEADER_SEARCH_ROWS) + 1):
        texts = row_texts(ws, row, columns)
        filled = sum(1 for t in texts if t)
        if filled < 3:
            continue
        recognised = sum(1 for t in texts if t and (match_field(t, fields) or is_numbering(t)))
        key = (recognised, filled, -row)
        if best is None or key > (best[0], best[1], -best[2]):
            best = (recognised, filled, row)
    if best is None or best[0] < 1:
        return None, 0
    return best[2], best[0]


def _warnings(ws: Worksheet, header_row: int | None, fields: set[str], columns: int) -> list[str]:
    found: list[str] = []
    if ws.sheet_state != "visible":
        found.append(f"sheet '{ws.title}' is hidden")
    if any(d.hidden for d in ws.column_dimensions.values()):
        found.append(f"sheet '{ws.title}' has hidden columns")
    if ws.protection.sheet:
        found.append(f"sheet '{ws.title}' is protected")
    if getattr(ws, "_images", None) or getattr(ws, "_charts", None):
        found.append(
            f"sheet '{ws.title}' has images or charts, which are dropped from the template"
        )
    if header_row is None:
        return found
    for merged in ws.merged_cells.ranges:
        if merged.min_row > header_row:
            found.append(f"merged cells {merged} in the data rows are not supported")
    last = min(ws.max_row, PROFILE_ROWS + header_row)
    for row in range(header_row + 1, last + 1):
        for column in range(1, columns + 1):
            if ws.cell(row=row, column=column).data_type == "f":
                found.append(f"formula in {get_column_letter(column)}{row} is not reproduced")
                break
    if header_row > 1 and sum(1 for t in row_texts(ws, header_row - 1, columns) if t) >= 3:
        found.append("the header may span two rows; only the lower one is used")
    for row in range(header_row + 2, min(ws.max_row, 200) + 1):
        texts = row_texts(ws, row, columns)
        if sum(1 for t in texts if t and match_field(t, fields)) >= 2:
            found.append(
                f"a second table-looking block starts at row {row}; only the first is used"
            )
            break
    return found


def profile_workbook(path: Path, doc_type: DocType) -> WorkbookProfile:
    """Structure of every sheet; the sample is read with no macros and no external links."""
    check_sample(path)
    fields = fields_for(doc_type)
    try:
        wb: Any = load_workbook(path, data_only=False, keep_vba=False)
    except Exception as exc:  # openpyxl raises many types on corrupt files
        raise CalibrationError(f"the workbook cannot be read: {exc}") from exc
    sheets: list[SheetProfile] = []
    for ws in wb.worksheets:
        columns = min(ws.max_column, PROFILE_COLUMNS)
        header_row, recognised = find_header_row(ws, fields)
        widths = {
            get_column_letter(c): float(ws.column_dimensions[get_column_letter(c)].width)
            for c in range(1, columns + 1)
            if get_column_letter(c) in ws.column_dimensions
            and ws.column_dimensions[get_column_letter(c)].width
        }
        sheets.append(
            SheetProfile(
                name=ws.title,
                max_row=ws.max_row,
                max_col=ws.max_column,
                merged=[str(r) for r in ws.merged_cells.ranges],
                widths=widths,
                rows=[
                    row_texts(ws, r, columns) for r in range(1, min(ws.max_row, PROFILE_ROWS) + 1)
                ],
                header_row=header_row,
                recognised=recognised,
                warnings=_warnings(ws, header_row, fields, columns),
            )
        )
    notes = [] if any(s.is_table for s in sheets) else ["no sheet looks like a table of items"]
    return WorkbookProfile(sheets=sheets, warnings=notes)


def info_cells(ws: Worksheet, header_row: int) -> list[tuple[str, str]]:
    """Document-info cells above the header: (cell to fill, header source)."""
    found: list[tuple[str, str]] = []
    merged = list(ws.merged_cells.ranges)
    for row in range(1, header_row):
        for column in range(1, min(ws.max_column, PROFILE_COLUMNS) + 1):
            source = doc_info_source(_text(ws.cell(row=row, column=column).value))
            if source is None:
                continue
            last = column
            for rng in merged:
                if rng.min_row <= row <= rng.max_row and rng.min_col <= column <= rng.max_col:
                    last = rng.max_col
            target = f"{get_column_letter(last + 1)}{row}"
            found.append((target, source))
    return found


def heuristic_draft(profile: WorkbookProfile, doc_type: DocType, path: Path) -> MappingDraft:
    """Map every table-looking sheet by its header labels; unknown columns stay unmapped."""
    fields = fields_for(doc_type)
    wb = load_workbook(path, data_only=False, keep_vba=False)
    tables: list[TableMap] = []
    headers: list[HeaderCell] = []
    unmapped: list[str] = []
    warnings = list(profile.warnings)
    for sheet in profile.sheets:
        warnings.extend(sheet.warnings)
        if not sheet.is_table or sheet.header_row is None:
            continue
        ws = wb[sheet.name]
        used: set[str] = set()
        numbering: str | None = None
        columns: list[ColumnMap] = []
        for column in range(1, min(sheet.max_col, PROFILE_COLUMNS) + 1):
            letter = get_column_letter(column)
            text = str(ws.cell(row=sheet.header_row, column=column).value or "").strip()
            if not text:
                continue
            if numbering is None and is_numbering(text) and not columns:
                numbering = letter
                continue
            field = match_field(text, fields - used)
            if field is not None:
                used.add(field)
            else:
                unmapped.append(f"{sheet.name}!{letter}: {text}")
            columns.append(
                ColumnMap(
                    col=letter,
                    header=text,
                    field=field,
                    value_map=VALUE_MAP_FIELDS.get(field) if field else None,
                )
            )
        if not columns:
            continue
        tables.append(
            TableMap(
                sheet=sheet.name,
                key=f"t{len(tables) + 1}",
                header_row=sheet.header_row,
                first_row=sheet.header_row + 1,
                numbering=numbering,
                columns=columns,
            )
        )
        headers.extend(
            HeaderCell(sheet=sheet.name, cell=cell, source=source)
            for cell, source in info_cells(ws, sheet.header_row)
        )
    return MappingDraft(
        doc_type=doc_type,
        tables=tables,
        headers=headers,
        unmapped=unmapped,
        warnings=list(dict.fromkeys(warnings)),
    )
