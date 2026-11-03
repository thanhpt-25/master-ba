"""`.xlsx` extraction (Requirements 4.3, 4.4, 2.6): cached values only, nothing evaluated."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from masterba.knowledge.extract.blocks import Block


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def xlsx_blocks(path: Path) -> Iterator[Block]:
    """One block per run of non-empty rows, per sheet, in workbook order."""
    wb = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        for ws in wb.worksheets:
            run: list[tuple[int, str]] = []
            for number, row in enumerate(ws.iter_rows(values_only=True), start=1):
                text = "\t".join(t for t in (_cell_text(v) for v in row) if t)
                if text:
                    run.append((number, text))
                    continue
                if run:
                    yield Block(rows=tuple(run), sheet=ws.title, keep_rows=True)
                run = []
            if run:
                yield Block(rows=tuple(run), sheet=ws.title, keep_rows=True)
    finally:
        wb.close()
