"""Template calibration from a real Excel sample (specs/09-template-calibration.md)."""

from masterba.calibration.models import (
    ColumnMap,
    HeaderCell,
    MappingDraft,
    SheetProfile,
    TableMap,
    WorkbookProfile,
)
from masterba.calibration.profile import (
    CalibrationError,
    check_sample,
    heuristic_draft,
    profile_workbook,
)
from masterba.calibration.store import (
    CalibrationResult,
    PreviewResult,
    calibrate,
    check,
    confirm,
    list_templates,
    load_draft,
    preview,
    set_column,
    state_of,
    unconfirm,
)
from masterba.calibration.validate import validate_mapping

__all__ = [
    "CalibrationError",
    "CalibrationResult",
    "ColumnMap",
    "HeaderCell",
    "MappingDraft",
    "PreviewResult",
    "SheetProfile",
    "TableMap",
    "WorkbookProfile",
    "calibrate",
    "check",
    "check_sample",
    "confirm",
    "heuristic_draft",
    "list_templates",
    "load_draft",
    "preview",
    "profile_workbook",
    "set_column",
    "state_of",
    "unconfirm",
    "validate_mapping",
]
