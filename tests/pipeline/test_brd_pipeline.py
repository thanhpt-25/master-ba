import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook

from factories import (
    bad_draft,
    draft_for,
    intake_path,
    make_config,
    make_requirement,
    qa_block,
    qa_pass,
)
from masterba.llm import AnthropicLLM, FakeLLM
from masterba.models import BrdContent
from masterba.models.enums import DocLanguage, ItemStatus, TeamRunStatus
from masterba.pipeline import BRD_DOC_ID, assign_ids, next_requirement_number, run_brd
from masterba.trace_store import (
    DuplicateIdError,
    ImpactNode,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    add_requirement,
    create_project,
    get_document,
    get_intake,
    get_trace_links,
    list_requirements,
    open_project,
    query_impact,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"
FIXTURES = ["login_system.txt", "leave_management.txt", "inventory_mixed_ja.txt"]
CITATION = re.compile(r"^intake/(?P<name>[^#]+)#L(?P<start>\d+)-L(?P<end>\d+)$")


def accepted(name: str = LOGIN) -> FakeLLM:
    """A scripted model whose first draft passes the gate and QA."""
    return FakeLLM([draft_for(name), qa_pass()])


def test_full_run_writes_everything_in_the_documented_commit_order(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    result = run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    assert result.status is TeamRunStatus.DONE
    assert result.requirement_ids == tuple(f"REQ-000{n}" for n in range(1, 6))
    item = f"{BRD_DOC_ID}#item"
    expected = [
        "intake(PRJ-001): add login_system.txt",
        *[f"req(PRJ-001): add REQ-000{n}" for n in range(1, 6)],
        f"doc(PRJ-001): create {BRD_DOC_ID} v1",
        *[f"trace(PRJ-001): link REQ-000{n} -> {item}.{n}" for n in range(1, 6)],
        f"render(PRJ-001): xlsx {BRD_DOC_ID} v1",
        "run(PRJ-001): RUN-0001 done",
        "question(PRJ-001): add Q-0001",  # the draft's open question (spec 13 section 3)
    ]
    assert list(reversed(commit_log()[: len(expected)])) == expected
    assert (result.rounds, result.tokens_used) == (1, 300)


def test_stored_json_and_xlsx_agree(store: ProjectStore) -> None:
    result = run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    assert result.xlsx_path is not None
    _, content = get_document(store, BRD_DOC_ID)
    assert isinstance(content, BrdContent)
    workbook = load_workbook(result.xlsx_path)
    rows = list(workbook["業務要件"].iter_rows(min_row=8, max_col=7, values_only=True))
    assert [(r[1], r[2], r[3]) for r in rows] == [
        (i.requirement_id, i.item_id, i.title) for i in content.items
    ]
    scope = workbook["システム化の範囲"].iter_rows(min_row=8, max_col=1, values_only=True)
    assert len(list(scope)) == 4
    out = workbook["対象外"].iter_rows(min_row=8, max_col=4, values_only=True)
    assert [r[3] for r in out] == ["Account administration"]


def test_every_citation_points_inside_the_stored_intake_and_quotes_match(
    store: ProjectStore,
) -> None:
    draft = draft_for(LOGIN)
    run_brd(store, TEMPLATES, FakeLLM([draft, qa_pass()]), intake_path(LOGIN))
    stored = get_intake(store, LOGIN).split("\n")
    _, content = get_document(store, BRD_DOC_ID)
    assert isinstance(content, BrdContent)
    requirements = list_requirements(store)
    assert [r.source_ref for r in requirements] == [i.source_ref for i in content.items]
    for requirement, quoted in zip(requirements, draft.requirements, strict=True):
        found = CITATION.match(requirement.source_ref)
        assert found is not None
        start, end = int(found["start"]), int(found["end"])
        assert 1 <= start <= end <= len(stored) - 1
        cited = " ".join(stored[start - 1 : end])
        assert " ".join(quoted.evidence_quote.split()) in " ".join(cited.split())


def test_each_requirement_traces_to_its_brd_item(store: ProjectStore) -> None:
    run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    assert query_impact(store, "REQ-0001") == [
        ImpactNode(f"{BRD_DOC_ID}#item.1", 1, "realizes", "downstream")
    ]
    assert len(get_trace_links(store)) == 5


def test_requirement_numbers_continue_after_existing_ones_including_removed(
    store: ProjectStore,
) -> None:
    for n in (1, 2):
        add_requirement(store, make_requirement(n))
    removed = make_requirement(3).model_copy(update={"status": ItemStatus.REMOVED})
    add_requirement(store, removed)
    result = run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    assert result.requirement_ids[0] == "REQ-0004"
    assert result.requirement_ids[-1] == "REQ-0008"
    assert next_requirement_number(list_requirements(store)) == 9


def test_assign_ids_is_pure_and_follows_draft_order() -> None:
    draft = draft_for("leave_management.txt")
    out = assign_ids(draft, project_id="PRJ-001", intake_ref="intake/x.txt", first_req_number=7)
    assert [r.id for r in out.requirements] == ["REQ-0007", "REQ-0008", "REQ-0009", "REQ-0010"]
    assert [i.item_id for i in out.content.items][:2] == [
        f"{BRD_DOC_ID}#item.1",
        f"{BRD_DOC_ID}#item.2",
    ]
    assert out.requirements[2].source_ref == "intake/x.txt#L4-L4"
    assert [(link.from_id, link.to_id) for link in out.links][0] == (
        "REQ-0007",
        f"{BRD_DOC_ID}#item.1",
    )


def test_a_gate_failure_is_revised_without_calling_qa(store: ProjectStore) -> None:
    llm = FakeLLM([bad_draft(), draft_for(LOGIN), qa_pass()])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert [c.tool_name for c in llm.calls] == ["submit_brd", "submit_brd", "submit_qa_report"]
    assert "evidence_quote is not found" in llm.calls[1].user


def test_qa_feedback_is_revised_and_recorded_in_the_mailbox(store: ProjectStore) -> None:
    blocked = qa_block("BRD-01", f"{BRD_DOC_ID}#item.2", "Item 2 mixes two needs.")
    llm = FakeLLM([draft_for(LOGIN), blocked, draft_for(LOGIN), qa_pass()])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert (result.issues_raised, result.issues_resolved) == (1, 1)
    assert "Item 2 mixes two needs." in llm.calls[2].user
    mailbox = json.loads((store.path / "runs" / "RUN-0001" / "mailbox.json").read_text("utf-8"))
    assert [(m["sender"], m["ref"]) for m in mailbox] == [("qa", f"{BRD_DOC_ID}#item.2")]


def test_a_separate_qa_model_receives_only_the_review_calls(store: ProjectStore) -> None:
    writer, reviewer = FakeLLM([draft_for(LOGIN)]), FakeLLM([qa_pass()])
    run_brd(store, TEMPLATES, writer, intake_path(LOGIN), qa_llm=reviewer)
    assert [c.tool_name for c in writer.calls] == ["submit_brd"]
    assert [c.tool_name for c in reviewer.calls] == ["submit_qa_report"]
    assert "BRD-01" in reviewer.calls[0].system


def test_repeating_the_same_qa_blocker_escalates_without_writing_the_draft(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = create_project(projects_root, make_config(max_rounds=2))
    blocked = qa_block("BRD-03", f"{BRD_DOC_ID}#item.1", "Not verifiable.")
    llm = FakeLLM([draft_for(LOGIN), blocked, draft_for(LOGIN), blocked])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert result.status is TeamRunStatus.ESCALATED
    assert result.rounds == 2
    assert result.escalations[0] == "no progress: the same QA blockers remained after a targeted revision"
    assert result.document_id is None
    # Besides its record, an escalated run writes only questions (spec 13 section 3): the
    # draft's open question and QA's objection.
    assert commit_log()[:4] == [
        "question(PRJ-001): add Q-0002",
        "question(PRJ-001): add Q-0001",
        "run(PRJ-001): RUN-0001 escalated",
        "intake(PRJ-001): add login_system.txt",
    ]
    assert list_requirements(store) == []
    assert get_trace_links(store) == []
    with pytest.raises(NotFoundError):
        get_document(store, BRD_DOC_ID)
    assert not (store.path / "xlsx").exists()


def test_a_second_run_on_an_existing_brd_is_refused_before_anything_is_written(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    count = len(commit_log())
    llm = FakeLLM([])
    with pytest.raises(DuplicateIdError, match="Decision Record"):
        run_brd(store, TEMPLATES, llm, intake_path("leave_management.txt"))
    assert len(commit_log()) == count
    assert llm.calls == []


def test_rerunning_after_an_escalation_needs_reuse_intake_and_gets_a_new_run(
    projects_root: Path,
) -> None:
    store = create_project(projects_root, make_config(max_rounds=1))
    first = run_brd(store, TEMPLATES, FakeLLM([bad_draft()]), intake_path(LOGIN))
    assert (first.status, first.run_id) == (TeamRunStatus.ESCALATED, "RUN-0001")
    with pytest.raises(DuplicateIdError, match="--reuse-intake"):
        run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    second = run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN), reuse_intake=True)
    assert (second.status, second.run_id) == (TeamRunStatus.DONE, "RUN-0002")


def test_reuse_intake_refuses_a_changed_file(projects_root: Path, tmp_path: Path) -> None:
    store = create_project(projects_root, make_config(max_rounds=1))
    run_brd(store, TEMPLATES, FakeLLM([bad_draft()]), intake_path(LOGIN))
    changed = tmp_path / LOGIN
    changed.write_text(intake_path(LOGIN).read_text("utf-8") + "One more line.\n", "utf-8")
    with pytest.raises(InvalidDocumentError, match="differs"):
        run_brd(store, TEMPLATES, accepted(), changed, reuse_intake=True)


def test_crlf_intake_is_stored_with_unix_newlines(store: ProjectStore, tmp_path: Path) -> None:
    crlf = tmp_path / LOGIN
    crlf.write_bytes(intake_path(LOGIN).read_text("utf-8").replace("\n", "\r\n").encode())
    run_brd(store, TEMPLATES, accepted(), crlf)
    assert "\r" not in get_intake(store, LOGIN)


def test_oversized_intake_is_refused(store: ProjectStore, tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    big.write_text("x" * 200_001, encoding="utf-8")
    with pytest.raises(InvalidDocumentError, match="longer than"):
        run_brd(store, TEMPLATES, FakeLLM([]), big)


def test_open_questions_and_uncovered_lines_are_reported(store: ProjectStore) -> None:
    result = run_brd(store, TEMPLATES, accepted(), intake_path(LOGIN))
    assert result.open_questions == ("L8-L8: What response time counts as fast?",)
    assert result.uncovered_lines == (1, 2, 9, 10)


@pytest.mark.parametrize("name", FIXTURES)
def test_every_intake_fixture_produces_a_workbook_that_opens(
    projects_root: Path, name: str
) -> None:
    language = DocLanguage.JA if "ja" in name else DocLanguage.EN
    store = create_project(projects_root, make_config(language=language))
    result = run_brd(store, TEMPLATES, accepted(name), intake_path(name))
    assert result.xlsx_path is not None
    assert "業務要件" in load_workbook(result.xlsx_path).sheetnames
    reopened = open_project(projects_root, "PRJ-001")
    assert len(list_requirements(reopened)) == len(result.requirement_ids)


def test_japanese_text_survives_to_the_workbook(projects_root: Path) -> None:
    store = create_project(projects_root, make_config(language=DocLanguage.JA))
    name = "inventory_mixed_ja.txt"
    result = run_brd(store, TEMPLATES, accepted(name), intake_path(name))
    assert result.xlsx_path is not None
    assert load_workbook(result.xlsx_path)["業務要件"]["D9"].value == "在庫数のリアルタイム確認"


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_model_produces_a_structurally_valid_brd(store: ProjectStore) -> None:
    llm = AnthropicLLM(os.environ.get("MASTERBA_MODEL", "claude-sonnet-5-5"))
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert result.status in {TeamRunStatus.DONE, TeamRunStatus.ESCALATED}
    if result.status is TeamRunStatus.DONE:
        assert len(result.requirement_ids) >= 3
        assert result.xlsx_path is not None
        shutil.copy(result.xlsx_path, store.root / "live-review.xlsx")  # for the manual review
