"""Turn a validated mapping and the sample into a template definition and a clean shell."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from masterba.calibration.models import MappingDraft
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
from masterba.rendering.engine import CREATOR, FIXED_TIME
from masterba.rendering.xlsxio import workbook_bytes

DEFAULT_VALUE_MAPS: dict[str, dict[str, str]] = {"scope": {"in": "対象", "out": "対象外"}}


@dataclass(frozen=True)
class BuiltTemplate:
    definition: TemplateDefinition
    shell: bytes


def _sheet_keys(draft: MappingDraft) -> dict[str, str]:
    """Logical key per sheet name: the table key for table sheets, `s<n>` for header-only sheets."""
    keys = {t.sheet: t.key for t in draft.tables}
    for cell in draft.headers:
        keys.setdefault(cell.sheet, f"s{len(keys) + 1}")
    return keys


def build_definition(draft: MappingDraft, company_id: str) -> TemplateDefinition:
    keys = _sheet_keys(draft)
    tables = [
        TableBinding(
            sheet=table.key,
            start_row=table.first_row,
            where={"status": "active", **table.where},
            numbering=NumberingBinding(column=table.numbering) if table.numbering else None,
            columns=[
                ColumnBinding(col=c.col, field=c.field, value_map=c.value_map)
                for c in table.columns
            ],
        )
        for table in draft.tables
    ]
    used_maps = {c.value_map for t in draft.tables for c in t.columns if c.value_map}
    bindings = Bindings(
        header=[
            HeaderBinding(sheet=keys[h.sheet], cell=h.cell, source=h.source) for h in draft.headers
        ],
        tables=tables,
        value_maps={name: DEFAULT_VALUE_MAPS[name] for name in sorted(used_maps)},
    )
    return TemplateDefinition(
        company_id=company_id,
        doc_type=draft.doc_type,
        source=TemplateSource.CALIBRATED_FROM_SAMPLE,
        sheet_map={key: name for name, key in keys.items()},
        cell_bindings=bindings.model_dump(mode="json"),
        validation_rules=[{"rule": "max_cell_length", "limit": EXCEL_MAX_CELL_LENGTH}],
    )


def _clear(ws: Worksheet, first_row: int, columns: list[str]) -> None:
    """Remove sample values from the data rows but keep every style."""
    for row in range(first_row, ws.max_row + 1):
        for letter in columns:
            ws[f"{letter}{row}"].value = None


def build_shell(draft: MappingDraft, sample: Path) -> bytes:
    """The sample without its data values, macros, images, charts and external links."""
    wb: Any = load_workbook(sample, data_only=False, keep_vba=False)
    for table in draft.tables:
        letters = [c.col for c in table.columns] + ([table.numbering] if table.numbering else [])
        _clear(wb[table.sheet], table.first_row, letters)
    for cell in draft.headers:
        wb[cell.sheet][cell.cell].value = None
    for sheet in wb.worksheets:
        sheet._images = []
        sheet._charts = []
    wb._external_links = []
    wb.properties.creator = CREATOR
    wb.properties.lastModifiedBy = CREATOR
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    return workbook_bytes(wb)


def build_template(draft: MappingDraft, sample: Path, company_id: str) -> BuiltTemplate:
    return BuiltTemplate(build_definition(draft, company_id), build_shell(draft, sample))


def shell_headers(shell: bytes, draft: MappingDraft) -> dict[str, list[str]]:
    """Header texts per table sheet of a shell (used by the layout comparison tests)."""
    wb = load_workbook(BytesIO(shell))
    out: dict[str, list[str]] = {}
    for table in draft.tables:
        ws = wb[table.sheet]
        out[table.sheet] = [
            str(ws.cell(row=table.header_row, column=c).value or "")
            for c in range(1, ws.max_column + 1)
        ]
    return out
