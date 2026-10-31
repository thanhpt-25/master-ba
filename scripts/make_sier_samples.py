"""Write synthetic sample workbooks in the usual Japanese SIer shape (development only).

`uv run python scripts/make_sier_samples.py OUTDIR` makes one `<TYPE>.xlsx` per document type:
a cover sheet, a revision-history sheet and one list sheet with a document-info block, a
dark header row and bordered, wrapped cells. They are the input of `masterba template calibrate`
for the sample company `sample-sier` (no real customer data).
"""

import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

FONT = "Meiryo UI"
HEADER_ROW = 9
INFO_LABELS = ("文書ID", "版数", "プロジェクト", "状態", "作成日", "作成者", "承認者")
TEST_COLUMNS = (
    ("No.", 6), ("テストケースID", 16), ("項目ID", 28), ("テストレベル", 10), ("確認対象", 28),
    ("前提条件", 30), ("入力値", 30), ("操作手順", 40), ("期待結果", 40), ("備考", 20),
)  # fmt: skip

# document type -> (document title, list sheet name, columns as (label, width))
LAYOUTS: dict[str, tuple[str, str, tuple[tuple[str, int], ...]]] = {
    "BRD": ("業務要件定義書", "業務要件一覧", (
        ("No.", 6), ("項目ID", 28), ("要件ID", 12), ("要件名", 28), ("要件内容", 60),
        ("対象範囲", 12), ("出典", 24), ("備考", 20),
    )),
    "SRS": ("システム要件定義書", "システム要件一覧", (
        ("No.", 6), ("項目ID", 28), ("要件ID", 12), ("種別", 12), ("要求記述", 60),
        ("受入観点", 40), ("派生元", 16), ("備考", 20),
    )),
    "BASIC_DESIGN": ("基本設計書", "基本設計一覧", (
        ("No.", 6), ("項目ID", 28), ("種別", 12), ("機能名", 28), ("内容", 60),
        ("実現対象", 28), ("備考", 20),
    )),
    "DETAIL_DESIGN": ("詳細設計書", "詳細設計一覧", (
        ("No.", 6), ("項目ID", 28), ("種別", 12), ("名称", 28), ("仕様", 60),
        ("詳細化対象", 28), ("備考", 20),
    )),
    "TEST_IT": ("結合テスト仕様書", "結合テストケース", TEST_COLUMNS),
    "TEST_ST": ("システムテスト仕様書", "システムテストケース", TEST_COLUMNS),
    "TEST_UT": ("単体テスト仕様書", "単体テストケース", TEST_COLUMNS),
}  # fmt: skip

_SIDE = Side(style="thin", color="808080")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)


def _cover(ws: Any, title: str) -> None:
    ws.title = "表紙"
    ws["B4"] = title
    ws["B4"].font = Font(name=FONT, size=22, bold=True)
    for index, label in enumerate(("案件名", "文書番号", "版数", "作成日", "作成者", "承認者")):
        row = 8 + 2 * index
        ws[f"B{row}"] = label
        ws[f"B{row}"].font = Font(name=FONT, size=11, bold=True)
        ws[f"C{row}"].border = Border(bottom=_SIDE)
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 40


def _history(ws: Any) -> None:
    ws.title = "改版履歴"
    ws["A1"] = "改版履歴"
    ws["A1"].font = Font(name=FONT, size=14, bold=True)
    for col, text in enumerate(("版数", "改版日", "改版内容", "改版者", "承認者"), 1):
        cell = ws.cell(row=3, column=col, value=text)
        cell.font = Font(name=FONT, bold=True)
        cell.border = BORDER
        cell.fill = PatternFill("solid", fgColor="D9E1F2")
    ws.column_dimensions["C"].width = 50


def _list(ws: Any, title: str, sheet: str, columns: tuple[tuple[str, int], ...]) -> None:
    ws.title = sheet
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=16, bold=True)
    for offset, label in enumerate(INFO_LABELS):
        row = 2 + offset
        ws.cell(row=row, column=1, value=label).font = Font(name=FONT, bold=True)
        ws.cell(row=row, column=2).border = Border(bottom=_SIDE)
    for col, (label, width) in enumerate(columns, 1):
        cell = ws.cell(row=HEADER_ROW, column=col, value=label)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
        ws.column_dimensions[cell.column_letter].width = width
        body = ws.cell(row=HEADER_ROW + 1, column=col)
        body.font = Font(name=FONT, size=10)
        body.alignment = Alignment(vertical="top", wrap_text=True)
        body.border = BORDER
    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)
    ws.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def write_sample(doc_type: str, path: Path) -> Path:
    title, sheet, columns = LAYOUTS[doc_type]
    wb = Workbook()
    cover = wb.active
    assert cover is not None
    _cover(cover, title)
    _history(wb.create_sheet())
    _list(wb.create_sheet(), title, sheet, columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: make_sier_samples.py OUTDIR\n")
        return 2
    for doc_type in LAYOUTS:
        sys.stdout.write(f"{write_sample(doc_type, Path(argv[0]) / f'{doc_type}.xlsx')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
