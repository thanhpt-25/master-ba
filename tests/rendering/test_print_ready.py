"""Spec 28: every workbook prints on white with borders, and calibrated covers are filled."""

from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from masterba.calibration.preview import demo_document
from masterba.models.enums import DocType
from masterba.rendering import render_document, resolve_template
from masterba.rendering.context import RenderContext, Revision
from masterba.rendering.finish import finish_workbook

REPO = Path(__file__).parents[2]
TEMPLATES = REPO / "templates"
CONTEXT = RenderContext(
    company="ACME",
    author="MasterBA",
    revisions=(
        Revision(1, "2026/11/01", "初版作成", "新規作成", "MasterBA", "佐藤", "2026/11/02"),
        Revision(2, "2026/11/20", "変更 1件", "DR-0001", "MasterBA"),
    ),
)
SAMPLE_TYPES = [t for t in DocType if t is not DocType.TEST_UAT]


def _bordered(cell: Any) -> bool:
    border = cell.border
    sides = [getattr(border, side, None) for side in ("left", "right", "top", "bottom")]
    return all(side is not None and side.style for side in sides)


def _render(company: str, doc_type: DocType) -> Workbook:
    doc, content = demo_document(doc_type)
    return render_document(doc, content, resolve_template(TEMPLATES, company, doc_type), CONTEXT)


@pytest.mark.parametrize("company", ["default", "sample-sier"])
@pytest.mark.parametrize("doc_type", SAMPLE_TYPES)
def test_every_sheet_has_no_gridlines_and_a_page_setup(company: str, doc_type: DocType) -> None:
    wb = _render(company, doc_type)

    for ws in wb.worksheets:
        assert ws.sheet_view.showGridLines is False, (company, doc_type, ws.title)
        assert ws.page_setup.orientation, (company, doc_type, ws.title)
        paper = str(ws.page_setup.paperSize)
        assert paper in {str(ws.PAPERSIZE_A4), str(ws.PAPERSIZE_A3)}, (company, doc_type, ws.title)


def test_the_finishing_pass_keeps_a_page_setup_the_template_chose() -> None:
    wb = Workbook()
    ws: Any = wb.active
    ws.page_setup.orientation = "portrait"

    finish_workbook(wb)

    assert ws.page_setup.orientation == "portrait"
    assert ws.sheet_view.showGridLines is False


@pytest.mark.parametrize("doc_type", SAMPLE_TYPES)
def test_a_calibrated_template_fills_the_cover_info_block_and_history(doc_type: DocType) -> None:
    wb = _render("sample-sier", doc_type)

    cover = wb["表紙"]
    filled = {cover[f"B{r}"].value: cover[f"C{r}"].value for r in range(8, 19, 2)}
    assert filled == {
        "案件名": "PRJ-001",
        "文書番号": f"DOC-{doc_type.value}-0001",
        "版数": "1.0",
        "作成日": "2026/11/01",
        "作成者": "MasterBA",
        "承認者": "佐藤",
    }
    history = wb["改版履歴"]
    rows = [[history.cell(row=r, column=c).value for c in range(1, 6)] for r in (4, 5)]
    assert rows == [
        ["1.0", "2026/11/01", "初版作成", "MasterBA", "佐藤"],
        ["2.0", "2026/11/20", "変更 1件", "MasterBA", None],
    ]
    # The sample styled only the header row; every written row still prints as a grid.
    assert all(_bordered(history.cell(row=r, column=c)) for r in (4, 5) for c in range(1, 6))
    listing = wb.worksheets[2]
    info = {listing[f"A{r}"].value: listing[f"B{r}"].value for r in range(2, 9)}
    assert info["状態"] == "作成中"
    assert info["作成日"] == "2026/11/01" and info["作成者"] == "MasterBA"


def test_a_bare_label_value_pair_gets_borders_but_an_underlined_one_does_not() -> None:
    wb = _render("default", DocType.BRD)
    cover = wb["表紙"]
    title = cover["B4"]

    assert not _bordered(title)  # the cover title has no label to its left
    sier = _render("sample-sier", DocType.BRD)["表紙"]
    assert sier["C8"].border.bottom.style
    assert sier["C8"].border.left is None or not sier["C8"].border.left.style
