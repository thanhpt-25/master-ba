# Feature: local-rag, Property 8: Spreadsheet chunks follow blocks of non-empty rows
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from openpyxl import Workbook

from masterba.knowledge.extract import ExtractionError, extract_source

_cell = st.sampled_from([None, "", "  ", "受注", "顧客", "x" * 300, "42"])
_sheet = st.lists(st.lists(_cell, min_size=1, max_size=4), min_size=1, max_size=12)


def _runs(grid: list[list[str | None]]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = None
    for n, row in enumerate(grid, start=1):
        filled = any(v is not None and str(v).strip() for v in row)
        if filled and start is None:
            start = n
        if not filled and start is not None:
            runs.append((start, n - 1))
            start = None
    if start is not None:
        runs.append((start, len(grid)))
    return runs


@given(st.lists(_sheet, min_size=1, max_size=3))
def test_spreadsheet_chunks(sheets: list[list[list[str | None]]]) -> None:
    wb = Workbook()
    first: Any = wb.active
    wb.remove(first)
    for i, grid in enumerate(sheets):
        ws = wb.create_sheet(f"S{i}")
        for r, row in enumerate(grid, start=1):
            for c, value in enumerate(row, start=1):
                ws.cell(r, c, value)
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "KB-0001.xlsx"
        wb.save(path)
        try:
            chunks = extract_source("KB-0001", path, ".xlsx")
        except ExtractionError as exc:
            assert str(exc) == "no text found"
            assert not any(_runs(g) for g in sheets)
            return
    order = [f"S{i}" for i in range(len(sheets))]
    assert [order.index(c.sheet or "") for c in chunks] == sorted(
        order.index(c.sheet or "") for c in chunks
    )
    for i, grid in enumerate(sheets):
        mine = [c for c in chunks if c.sheet == f"S{i}"]
        for first, last in _runs(grid):
            inside = [c.rows for c in mine if c.rows and first <= c.rows[0] <= last]
            assert all(r is not None and r[1] <= last for r in inside)
            covered = sorted({n for r in inside if r for n in range(r[0], r[1] + 1)})
            assert covered == list(range(first, last + 1))
