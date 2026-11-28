"""Keeping customer data out of template sets (spec 30 section 5)."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from masterba.guard.detect import Finding, find, preview

_PROPERTIES = ("title", "subject", "keywords", "description", "category")
_EXTENDED = ("company", "manager")


@dataclass(frozen=True)
class SetFinding:
    path: str  # relative to the set folder, with a sheet and cell for a workbook
    finding: Finding

    def text(self) -> str:
        return f"{self.path}: {self.finding.kind} {preview(self.finding)}"


def _cells(wb: Any) -> Iterator[tuple[str, Any]]:
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                yield f"{sheet.title}!{cell.coordinate}", cell


def clean_workbook(wb: Any) -> list[str]:
    """Remove comments, descriptive properties and every text cell with a finding."""
    emptied: list[str] = []
    for where, cell in _cells(wb):
        if cell.comment is not None:
            cell.comment = None
        if isinstance(cell.value, str) and find(cell.value):
            cell.value = None
            emptied.append(where)
    for name in _PROPERTIES:
        setattr(wb.properties, name, None)
    for name in _EXTENDED:
        if hasattr(wb.properties, name):
            setattr(wb.properties, name, None)
    return emptied


def workbook_findings(path: Path) -> list[tuple[str, Finding]]:
    """Findings in every sheet (hidden ones too), cell comments and properties."""
    wb: Any = load_workbook(path, data_only=False)
    found: list[tuple[str, Finding]] = []
    for where, cell in _cells(wb):
        if isinstance(cell.value, str):
            found += [(where, f) for f in find(cell.value)]
        if cell.comment is not None and cell.comment.text:
            found += [(f"{where} (comment)", f) for f in find(cell.comment.text)]
    for name in _PROPERTIES:
        value = getattr(wb.properties, name, None)
        if isinstance(value, str):
            found += [(f"properties.{name}", f) for f in find(value)]
    return found


def set_findings(folder: Path) -> list[SetFinding]:
    """Findings in a set's shells, definitions and calibration records (not its samples)."""
    found: list[SetFinding] = []
    if not folder.is_dir():
        return found
    for path in sorted(folder.iterdir()):
        name = path.name
        if name.endswith((".sample.xlsx", ".preview.xlsx")) or not path.is_file():
            continue
        if name.endswith(".xlsx"):
            try:
                hits = workbook_findings(path)
            except Exception:  # noqa: BLE001 - an unreadable shell is reported by the template checks
                continue
            found += [SetFinding(f"{name} {where}", f) for where, f in hits]
        elif name.endswith(".json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            found += [SetFinding(f"{name} line {f.line}", f) for f in find(text)]
    return found
