"""Synthetic SIer-style sample workbooks for the calibration tests (no real customer data)."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font


def brd_sample(path: Path) -> Path:
    """Title rows, a doc-info block, header on row 4, Japanese labels in another order."""
    wb = Workbook()
    cover = wb.active
    assert cover is not None
    cover.title = "表紙"
    cover["A1"] = "業務要件定義書"
    cover["A3"] = "文書ID"
    cover["A4"] = "版数"
    ws = wb.create_sheet("要件一覧")
    ws["A1"] = "要件一覧"
    ws["A2"] = "文書ID"
    ws["A3"] = "版"
    for col, text in enumerate(("No.", "要件ID", "要件名", "要件内容", "対象範囲", "備考"), 1):
        cell = ws.cell(row=4, column=col, value=text)
        cell.font = Font(bold=True)
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 60
    ws.cell(row=5, column=1, value=1)
    ws.cell(row=5, column=3, value="old sample data")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def srs_sample(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "システム要求"
    for col, text in enumerate(("No.", "要求ID", "種別", "要求記述", "派生元", "受入観点"), 1):
        ws.cell(row=2, column=col, value=text)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def unreadable_sample(path: Path) -> Path:
    """A sheet with no table-looking header at all."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws["A1"] = "just a memo"
    wb.save(path)
    return path
