"""Finishing pass for every workbook the system writes (spec 28 section 1). No I/O.

Sheets show and print on white (no gridlines), and a sheet whose template set no page setup
gets A4 landscape, one page wide, with the file name and page number in the footer.
"""

from typing import Any

from openpyxl import Workbook
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

FOOTER_LEFT = "&F"
FOOTER_RIGHT = "ページ &P / &N"
FOOTER_SIZE = 8


def print_setup(ws: Worksheet, title_rows: str | None = None) -> None:
    """A4 landscape, one page wide, optional repeated rows, file name and page in the footer."""
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
    footer.left.size = FOOTER_SIZE
    footer.right.text = FOOTER_RIGHT
    footer.right.size = FOOTER_SIZE


def finish_sheet(ws: Worksheet) -> None:
    ws.sheet_view.showGridLines = False
    if not ws.page_setup.orientation:
        print_setup(ws)


def finish_workbook(wb: Workbook) -> Workbook:
    for ws in wb.worksheets:
        finish_sheet(ws)
    return wb
