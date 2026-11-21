"""The quality report and its CLI command (spec 19 part 2, section 9)."""

from pathlib import Path

from factories import draft_for, intake_path, login_srs_draft, qa_pass
from masterba.cli import main
from masterba.llm import FakeLLM
from masterba.pipeline import run_brd, run_srs
from masterba.quality.report import project_quality, to_markdown
from masterba.trace_store import ProjectStore

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"


def test_an_empty_project_says_so(store: ProjectStore) -> None:
    assert to_markdown("PRJ-001", project_quality(store)) == (
        "# Quality report: PRJ-001\n\nNo documents yet.\n"
    )


def test_report_lists_figures_findings_and_the_rubric(store: ProjectStore) -> None:
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    report = {q.doc_id: q for q in project_quality(store)}
    brd, srs = report["DOC-BRD-0001"], report["DOC-SRS-0001"]
    assert brd.missing_sections == ("background", "constraints")
    assert brd.traced_upstream == brd.active_items
    assert srs.traced_upstream == srs.active_items
    assert brd.traced_downstream > 0
    assert "functional items with an acceptance hint" in srs.figures
    text = to_markdown("PRJ-001", list(report.values()))
    assert "| DOC-BRD-0001 | 1 | draft | 5 |" in text
    assert "| 網羅性 (completeness) |" in text
    assert "## DOC-SRS-0001 v1" in text


def test_cli_writes_the_report(store: ProjectStore, tmp_path: Path) -> None:
    out = tmp_path / "quality.md"
    root = store.root.parent
    assert main(["--root", str(root), "quality", "--project", "PRJ-001", "--out", str(out)]) == 0
    assert out.read_text("utf-8").startswith("# Quality report: PRJ-001")
