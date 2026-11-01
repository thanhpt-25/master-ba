import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook

from factories import (
    draft_for,
    incomplete_srs_draft,
    intake_path,
    login_srs_draft,
    make_config,
    qa_block,
    qa_pass,
    srs_item,
)
from masterba.agents import SrsDraft, SrsOpenQuestion
from masterba.llm import FakeLLM
from masterba.models import SrsContent
from masterba.models.enums import SrsKind, TeamRunStatus
from masterba.pipeline import (
    BRD_DOC_ID,
    SRS_DOC_ID,
    assign_srs_ids,
    run_brd,
    run_srs,
)
from masterba.trace_store import (
    DuplicateIdError,
    ImpactNode,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    create_project,
    get_document,
    get_trace_links,
    query_impact,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"


@pytest.fixture
def with_brd(store: ProjectStore) -> ProjectStore:
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    return store


def srs_ok() -> FakeLLM:
    return FakeLLM([login_srs_draft(), qa_pass()])


def test_brd_then_srs_end_done_with_committed_run_records(
    with_brd: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    result = run_srs(with_brd, TEMPLATES, srs_ok())
    assert result.status is TeamRunStatus.DONE
    assert (result.run_id, result.document_id) == ("RUN-0002", SRS_DOC_ID)
    item = f"{SRS_DOC_ID}#item"
    expected = [
        f"doc(PRJ-001): create {SRS_DOC_ID} v1",
        *[f"trace(PRJ-001): link REQ-000{n} -> {item}.{n}" for n in range(1, 5)],
        f"render(PRJ-001): xlsx {SRS_DOC_ID} v1",
        "run(PRJ-001): RUN-0002 done",
    ]
    assert list(reversed(commit_log()[: len(expected)])) == expected
    for run in ("RUN-0001", "RUN-0002"):
        folder = with_brd.path / "runs" / run
        assert {p.name for p in folder.iterdir() if p.is_file()} >= {
            "team-summary.json",
            "team-tasks.json",
            "mailbox.json",
        }


def test_the_rtm_reaches_both_the_brd_item_and_the_srs_item(with_brd: ProjectStore) -> None:
    run_srs(with_brd, TEMPLATES, srs_ok())
    assert query_impact(with_brd, "REQ-0003") == [
        ImpactNode(f"{BRD_DOC_ID}#item.3", 1, "realizes", "downstream"),
        ImpactNode(f"{SRS_DOC_ID}#item.3", 1, "realizes", "downstream"),
    ]
    assert len(get_trace_links(with_brd)) == 5 + 4


def test_srs_content_and_workbook_agree(with_brd: ProjectStore) -> None:
    result = run_srs(with_brd, TEMPLATES, srs_ok())
    _, content = get_document(with_brd, SRS_DOC_ID)
    assert isinstance(content, SrsContent)
    assert [i.requirement_id for i in content.items] == [
        "REQ-0001",
        "REQ-0002",
        "REQ-0003",
        "REQ-0004",
    ]
    assert result.xlsx_path is not None
    sheet = load_workbook(result.xlsx_path)["機能要件"]
    rows = list(sheet.iter_rows(min_row=8, max_col=6, values_only=True))
    assert [r[1] for r in rows] == ["REQ-0001", "REQ-0002", "REQ-0004"]
    non_functional = load_workbook(result.xlsx_path)["非機能要件"]
    assert non_functional["B8"].value == "REQ-0003"


def test_qa_feedback_makes_the_writer_revise(with_brd: ProjectStore) -> None:
    blocked = qa_block("SRS-02", f"{SRS_DOC_ID}#item.2", "No acceptance hint.")
    llm = FakeLLM([login_srs_draft(), blocked, login_srs_draft(), qa_pass()])
    result = run_srs(with_brd, TEMPLATES, llm)
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert result.issues_raised == result.issues_resolved == 1
    assert "No acceptance hint." in llm.calls[2].user
    mailbox = json.loads((with_brd.path / "runs" / "RUN-0002" / "mailbox.json").read_text("utf-8"))
    assert mailbox[0]["ref"] == f"{SRS_DOC_ID}#item.2"


def test_an_uncovered_requirement_goes_back_to_the_writer_without_a_qa_call(
    with_brd: ProjectStore,
) -> None:
    llm = FakeLLM([incomplete_srs_draft(), login_srs_draft(), qa_pass()])
    result = run_srs(with_brd, TEMPLATES, llm)
    assert result.status is TeamRunStatus.DONE
    assert [c.tool_name for c in llm.calls] == ["submit_srs", "submit_srs", "submit_qa_report"]
    assert "not covered by any item: REQ-0003, REQ-0004" in llm.calls[1].user
    mailbox = json.loads((with_brd.path / "runs" / "RUN-0002" / "mailbox.json").read_text("utf-8"))
    assert mailbox[0]["sender"] == "gate"


def test_never_satisfying_qa_escalates_after_max_rounds_and_writes_nothing(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = create_project(projects_root, make_config(max_rounds=2))
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    blocked = qa_block("SRS-01", f"{SRS_DOC_ID}#item.1", "Two obligations.")
    llm = FakeLLM([login_srs_draft(), blocked, login_srs_draft(), blocked])
    result = run_srs(store, TEMPLATES, llm)
    assert result.status is TeamRunStatus.ESCALATED
    assert result.rounds == 2
    # Questions are the one thing an escalated run writes besides its record (spec 13 section 3).
    runs = [c for c in commit_log() if c.startswith("run(")]
    assert runs[0] == "run(PRJ-001): RUN-0002 escalated"
    assert runs[1].startswith("run(PRJ-001): RUN-0001")
    with pytest.raises(NotFoundError):
        get_document(store, SRS_DOC_ID)
    assert not (store.path / "xlsx" / "srs").exists()
    assert len(get_trace_links(store)) == 5


def test_an_escalated_stage_can_be_run_again_as_a_new_run(projects_root: Path) -> None:
    store = create_project(projects_root, make_config(max_rounds=1))
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    first = run_srs(store, TEMPLATES, FakeLLM([incomplete_srs_draft()]))
    second = run_srs(store, TEMPLATES, srs_ok())
    assert (first.run_id, first.status) == ("RUN-0002", TeamRunStatus.ESCALATED)
    assert (second.run_id, second.status) == ("RUN-0003", TeamRunStatus.DONE)


def test_transcripts_stay_local(with_brd: ProjectStore, git_repo: Path) -> None:
    run_srs(with_brd, TEMPLATES, srs_ok())
    transcripts = with_brd.path / "runs" / "RUN-0002" / "transcripts"
    assert sorted(p.name for p in transcripts.iterdir())[0].startswith("001-round-1-submit_srs")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert "transcripts" not in tracked
    assert "RUN-0002/team-summary.json" in tracked


def test_the_srs_needs_a_brd_and_refuses_a_second_srs(
    store: ProjectStore, with_brd: ProjectStore
) -> None:
    run_srs(with_brd, TEMPLATES, srs_ok())
    llm = FakeLLM([])
    with pytest.raises(DuplicateIdError, match="Decision Record"):
        run_srs(with_brd, TEMPLATES, llm)
    assert llm.calls == []


def test_without_a_brd_the_stage_refuses_to_start(store: ProjectStore) -> None:
    with pytest.raises(NotFoundError, match="run the brd stage first"):
        run_srs(store, TEMPLATES, FakeLLM([]))


def test_a_brd_with_nothing_in_scope_cannot_be_specified(projects_root: Path) -> None:
    store = create_project(projects_root, make_config())
    only_out = draft_for(LOGIN).model_copy(
        update={"requirements": [draft_for(LOGIN).requirements[4]]}
    )
    run_brd(store, TEMPLATES, FakeLLM([only_out, qa_pass()]), intake_path(LOGIN))
    with pytest.raises(InvalidDocumentError, match="no in-scope requirements"):
        run_srs(store, TEMPLATES, FakeLLM([]))


def test_assign_srs_ids_numbers_items_dedupes_sources_and_links_each_requirement() -> None:
    draft = SrsDraft(
        items=[
            srs_item(
                SrsKind.FUNCTIONAL, "The system shall a.", ["REQ-0002", "REQ-0001", "REQ-0002"]
            ),
            srs_item(SrsKind.FUNCTIONAL, "The system shall b.", ["REQ-0003"]),
        ]
    )
    out = assign_srs_ids(draft, project_id="PRJ-001")
    first = out.content.items[0]
    assert (first.item_id, first.requirement_id) == (f"{SRS_DOC_ID}#item.1", "REQ-0002")
    assert first.derives_from == ["REQ-0002", "REQ-0001"]
    assert [(link.from_id, link.to_id) for link in out.links] == [
        ("REQ-0002", f"{SRS_DOC_ID}#item.1"),
        ("REQ-0001", f"{SRS_DOC_ID}#item.1"),
        ("REQ-0003", f"{SRS_DOC_ID}#item.2"),
    ]
    assert out.document.content_ref == f"json/srs/{SRS_DOC_ID}.v1.json"


def test_srs_open_questions_are_reported_in_the_result(with_brd: ProjectStore) -> None:
    question = SrsOpenQuestion(question="What availability figure applies?", req_ids=["REQ-0003"])
    draft = login_srs_draft().model_copy(update={"open_questions": [question]})
    result = run_srs(with_brd, TEMPLATES, FakeLLM([draft, qa_pass()]))
    assert result.open_questions == ("REQ-0003: What availability figure applies?",)
