"""The deterministic gate for a mapping draft (spec 09 section 4) and the heuristic draft."""

from openpyxl.utils import column_index_from_string

from masterba.calibration.heuristic import fields_for
from masterba.calibration.models import MappingDraft, SheetProfile, TableMap, WorkbookProfile
from masterba.models.enums import DocType
from masterba.rendering.bindings import HEADER_SOURCES

KNOWN_VALUE_MAPS = {"scope"}


def _sheet(profile: WorkbookProfile, name: str) -> SheetProfile | None:
    return next((s for s in profile.sheets if s.name == name), None)


def _validate_table(table: TableMap, profile: WorkbookProfile, fields: set[str]) -> list[str]:
    errors: list[str] = []
    sheet = _sheet(profile, table.sheet)
    where = f"table on '{table.sheet}'"
    if sheet is None:
        return [f"{where}: the sample has no such sheet"]
    if table.first_row <= table.header_row:
        errors.append(f"{where}: first data row {table.first_row} must come after the header row")
    letters = [c.col for c in table.columns]
    if table.numbering:
        letters.append(table.numbering)
    if len(letters) != len(set(letters)):
        errors.append(f"{where}: a column letter is used twice")
    for letter in letters:
        if column_index_from_string(letter) > max(sheet.max_col, 1):
            errors.append(f"{where}: column {letter} is outside the used range")
    chosen = [c.field for c in table.columns if c.field]
    for field in sorted({f for f in chosen if chosen.count(f) > 1}):
        errors.append(f"{where}: field {field} is mapped to more than one column")
    for column in table.columns:
        if column.field and column.field not in fields:
            errors.append(f"{where}: {column.field} is not a field of this document type")
        if column.value_map and column.value_map not in KNOWN_VALUE_MAPS:
            errors.append(f"{where}: unknown value map {column.value_map}")
    for key in table.where:
        if key not in fields | {"status"}:
            errors.append(f"{where}: filter field {key} is not a field of this document type")
    return errors


def validate_mapping(draft: MappingDraft, profile: WorkbookProfile, doc_type: DocType) -> list[str]:
    """Problems that stop a draft from being built (empty = accepted)."""
    fields = fields_for(doc_type)
    errors: list[str] = []
    if draft.doc_type is not doc_type:
        errors.append(f"the draft is for {draft.doc_type.value}, not {doc_type.value}")
    if not draft.tables:
        errors.append("the draft has no table")
    sheets_used = [t.sheet for t in draft.tables]
    for name in sorted({s for s in sheets_used if sheets_used.count(s) > 1}):
        errors.append(f"more than one table on sheet '{name}' is not supported")
    keys = [t.key for t in draft.tables]
    if len(keys) != len(set(keys)):
        errors.append("table keys must be unique")
    for table in draft.tables:
        errors.extend(_validate_table(table, profile, fields))
        if not any(c.field for c in table.columns):
            errors.append(f"table on '{table.sheet}' maps no column to a field")
    for cell in draft.headers:
        if _sheet(profile, cell.sheet) is None:
            errors.append(f"header cell {cell.cell}: the sample has no sheet '{cell.sheet}'")
        if cell.source not in HEADER_SOURCES:
            errors.append(f"header cell {cell.cell}: unknown source {cell.source}")
    return errors


def advisory_warnings(draft: MappingDraft) -> list[str]:
    """Things a template may do but a reviewer should look at (never block a build)."""
    notes: list[str] = []
    for table in draft.tables:
        mapped = {c.field for c in table.columns if c.field}
        if not mapped & {"item_id", "test_id", "requirement_id"}:
            notes.append(
                f"'{table.sheet}' shows no identifier column; stable ids will not be visible"
            )
    return notes
