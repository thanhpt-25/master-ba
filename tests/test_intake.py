"""Word, PDF and Excel intakes become numbered Markdown text (spec 19 section 18)."""

from collections.abc import Callable
from pathlib import Path

import docx
import pytest
from openpyxl import Workbook

from factories import FUNCTIONAL, draft_req, qa_pass
from masterba.agents import BrdDraft
from masterba.intake import blocks_to_markdown, intake_name, intake_text
from masterba.knowledge.extract.blocks import Block
from masterba.llm import FakeLLM
from masterba.models.enums import TeamRunStatus
from masterba.pipeline import run_brd
from masterba.trace_store import InvalidDocumentError, ProjectStore, get_intake, list_requirements
from pdfgen import text_pdf

TEMPLATES = Path(__file__).parents[1] / "templates"


def make_docx(path: Path) -> Path:
    document = docx.Document()
    document.add_heading("Overview", level=1)
    document.add_paragraph("The portal serves registered customers.")
    document.add_heading("Login", level=2)
    document.add_paragraph("A customer shall sign in with email and password.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Screen"
    table.cell(0, 1).text = "Name"
    table.cell(1, 0).text = "SC-01"
    table.cell(1, 1).text = "Login"
    document.add_heading("Orders", level=1)
    document.add_paragraph("A customer shall see their order history.")
    document.save(str(path))
    return path


def make_xlsx(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "要望一覧"
    ws.append(["No", "要望"])
    ws.append([1, "顧客はメールアドレスでログインできること"])
    ws.append([])
    ws.append([2, "顧客は注文履歴を確認できること"])
    wb.save(path)
    return path


def test_a_docx_keeps_headings_paragraphs_and_table_rows_in_order(tmp_path: Path) -> None:
    text = intake_text(make_docx(tmp_path / "rfp.docx"))
    assert text.splitlines() == [
        "# Overview",
        "",
        "The portal serves registered customers.",
        "",
        "## Login",
        "",
        "A customer shall sign in with email and password.",
        "",
        "| Screen | Name |",
        "| SC-01 | Login |",
        "",
        "# Orders",
        "",
        "A customer shall see their order history.",
    ]


def test_a_pdf_marks_each_page(tmp_path: Path) -> None:
    path = tmp_path / "rfp.pdf"
    path.write_bytes(text_pdf(["Customers sign in.", "Customers see orders."]))
    lines = intake_text(path).splitlines()
    assert lines[0] == "<!-- p.1 -->" and "Customers sign in." in lines[1]
    assert "<!-- p.2 -->" in lines and "Customers see orders." in lines[-1]


def test_an_xlsx_names_each_sheet_and_row(tmp_path: Path) -> None:
    text = intake_text(make_xlsx(tmp_path / "req.xlsx"))
    assert text.splitlines() == [
        "## 要望一覧",
        "",
        "R1: No\t要望",
        "R2: 1\t顧客はメールアドレスでログインできること",
        "",
        "R4: 2\t顧客は注文履歴を確認できること",
    ]


def test_headings_shared_with_the_previous_block_are_not_repeated() -> None:
    blocks = [
        Block(text="a", heading_path=("H1", "H2")),
        Block(text="b", heading_path=("H1", "H3")),
    ]
    assert blocks_to_markdown(blocks).splitlines() == [
        "# H1", "", "## H2", "", "a", "", "## H3", "", "b",
    ]  # fmt: skip
    assert blocks_to_markdown([]) == ""


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("intake.md", "intake.md"),
        ("notes.txt", "notes.txt"),
        ("RFP v2.docx", "RFP-v2-docx.md"),
        ("spec.PDF", "spec-pdf.md"),
        ("req.xlsx", "req-xlsx.md"),
    ],
)
def test_converted_files_are_stored_under_a_markdown_name(given: str, stored: str) -> None:
    assert intake_name(given) == stored


def test_japanese_file_names_get_distinct_ascii_names() -> None:
    first, second = intake_name("要件定義.docx"), intake_name("要望一覧.docx")
    assert first != second
    assert first.startswith("intake-") and first.endswith("-docx.md")
    with pytest.raises(InvalidDocumentError, match="unsupported intake type"):
        intake_name("mail.eml")


def test_an_unreadable_file_is_refused_with_its_reason(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(InvalidDocumentError, match="cannot read intake broken.pdf"):
        intake_text(broken)
    empty = tmp_path / "empty.xlsx"
    Workbook().save(empty)
    with pytest.raises(InvalidDocumentError, match="no text found"):
        intake_text(empty)


def test_a_brd_run_on_a_docx_cites_lines_of_the_stored_text(
    store: ProjectStore, tmp_path: Path
) -> None:
    path = make_docx(tmp_path / "rfp.docx")
    lines = intake_text(path).splitlines()
    login = lines.index("A customer shall sign in with email and password.") + 1
    orders = lines.index("A customer shall see their order history.") + 1
    draft = BrdDraft(
        requirements=[
            draft_req("Login", FUNCTIONAL, login, "sign in with email and password"),
            draft_req("Order history", FUNCTIONAL, orders, "see their order history"),
        ]
    )
    result = run_brd(store, TEMPLATES, FakeLLM([draft, qa_pass()]), path)
    assert result.status is TeamRunStatus.DONE
    assert get_intake(store, "rfp-docx.md").splitlines() == lines
    sources = {r.source_ref for r in list_requirements(store)}
    assert sources == {f"intake/rfp-docx.md#L{n}-L{n}" for n in (login, orders)}


def test_an_unreadable_intake_stops_the_brd_stage_with_nothing_written(
    store: ProjectStore, tmp_path: Path, commit_log: Callable[[], list[str]]
) -> None:
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    before = commit_log()
    with pytest.raises(InvalidDocumentError, match="cannot read intake broken.docx"):
        run_brd(store, TEMPLATES, FakeLLM([]), broken)
    assert commit_log() == before
