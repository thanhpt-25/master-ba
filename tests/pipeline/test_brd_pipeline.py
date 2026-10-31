import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook

from factories import bad_draft, draft_for, intake_path, make_config, make_requirement
from masterba.agents import DraftRejectedError
from masterba.llm import AnthropicLLM, FakeLLM
from masterba.models import BrdContent
from masterba.models.enums import ItemStatus
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


def test_full_run_writes_everything_in_the_documented_commit_order(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
    assert result.requirement_ids == tuple(f"REQ-000{n}" for n in range(1, 6))
    item = f"{BRD_DOC_ID}#item"
    expected = [
        "intake(PRJ-001): add login_system.txt",
        *[f"req(PRJ-001): add REQ-000{n}" for n in range(1, 6)],
        f"doc(PRJ-001): create {BRD_DOC_ID} v1",
        *[f"trace(PRJ-001): link REQ-000{n} -> {item}.{n}" for n in range(1, 6)],
        f"render(PRJ-001): xlsx {BRD_DOC_ID} v1",
    ]
    assert list(reversed(commit_log()[: len(expected)])) == expected
    assert (result.attempts, result.input_tokens, result.output_tokens) == (1, 100, 50)


def test_stored_json_and_xlsx_agree(store: ProjectStore) -> None:
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
    doc, content = get_document(store, BRD_DOC_ID)
    assert isinstance(content, BrdContent)
    assert doc.version == 1
    sheet = load_workbook(result.xlsx_path)["業務要件"]
    rows = list(sheet.iter_rows(min_row=8, max_col=7, values_only=True))
    assert [(r[1], r[2], r[3]) for r in rows] == [
        (i.requirement_id, i.item_id, i.title) for i in content.items
    ]
    scope = load_workbook(result.xlsx_path)
    assert (
        len(list(scope["システム化の範囲"].iter_rows(min_row=8, max_col=1, values_only=True))) == 4
    )
    assert [r[3] for r in scope["対象外"].iter_rows(min_row=8, max_col=4, values_only=True)] == [
        "Account administration"
    ]


def test_every_citation_points_inside_the_stored_intake_and_quotes_match(
    store: ProjectStore,
) -> None:
    draft = draft_for(LOGIN)
    run_brd(store, TEMPLATES, FakeLLM([draft]), intake_path(LOGIN))
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
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
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
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
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


def test_a_bad_draft_is_retried_and_then_accepted(store: ProjectStore) -> None:
    llm = FakeLLM([bad_draft(), draft_for(LOGIN)])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert result.attempts == 2
    assert len(llm.calls) == 2


def test_two_bad_drafts_leave_only_the_intake_behind(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    before = len(commit_log())
    with pytest.raises(DraftRejectedError):
        run_brd(store, TEMPLATES, FakeLLM([bad_draft(), bad_draft()]), intake_path(LOGIN))
    assert commit_log()[: len(commit_log()) - before] == ["intake(PRJ-001): add login_system.txt"]
    assert list_requirements(store) == []
    assert get_trace_links(store) == []
    with pytest.raises(NotFoundError):
        get_document(store, BRD_DOC_ID)
    assert not (store.path / "xlsx").exists()


def test_a_second_run_on_an_existing_brd_is_refused_before_anything_is_written(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
    count = len(commit_log())
    llm = FakeLLM([])
    with pytest.raises(DuplicateIdError, match="Decision Record"):
        run_brd(store, TEMPLATES, llm, intake_path("leave_management.txt"))
    assert len(commit_log()) == count
    assert llm.calls == []


def test_rerunning_after_a_rejection_needs_reuse_intake(store: ProjectStore) -> None:
    with pytest.raises(DraftRejectedError):
        run_brd(store, TEMPLATES, FakeLLM([bad_draft(), bad_draft()]), intake_path(LOGIN))
    with pytest.raises(DuplicateIdError, match="--reuse-intake"):
        run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
    result = run_brd(
        store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN), reuse_intake=True
    )
    assert result.document_id == BRD_DOC_ID


def test_reuse_intake_refuses_a_changed_file(store: ProjectStore, tmp_path: Path) -> None:
    with pytest.raises(DraftRejectedError):
        run_brd(store, TEMPLATES, FakeLLM([bad_draft(), bad_draft()]), intake_path(LOGIN))
    changed = tmp_path / LOGIN
    changed.write_text(intake_path(LOGIN).read_text("utf-8") + "One more line.\n", "utf-8")
    with pytest.raises(InvalidDocumentError, match="differs"):
        run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), changed, reuse_intake=True)


def test_crlf_intake_is_stored_with_unix_newlines_and_reusable(
    store: ProjectStore, tmp_path: Path
) -> None:
    crlf = tmp_path / LOGIN
    crlf.write_bytes(intake_path(LOGIN).read_text("utf-8").replace("\n", "\r\n").encode())
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), crlf)
    assert "\r" not in get_intake(store, LOGIN)


def test_oversized_intake_is_refused(store: ProjectStore, tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    big.write_text("x" * 200_001, encoding="utf-8")
    with pytest.raises(InvalidDocumentError, match="longer than"):
        run_brd(store, TEMPLATES, FakeLLM([]), big)


def test_open_questions_and_uncovered_lines_are_reported(store: ProjectStore) -> None:
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN)]), intake_path(LOGIN))
    assert result.open_questions == ("L8-L8: What response time counts as fast?",)
    assert result.uncovered_lines == (1, 2, 9, 10)


@pytest.mark.parametrize("name", FIXTURES)
def test_every_intake_fixture_produces_a_workbook_that_opens(
    projects_root: Path, name: str
) -> None:
    store = create_project(projects_root, make_config())
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(name)]), intake_path(name))
    workbook = load_workbook(result.xlsx_path)
    assert "業務要件" in workbook.sheetnames
    reopened = open_project(projects_root, "PRJ-001")
    assert len(list_requirements(reopened)) == len(result.requirement_ids)


def test_japanese_text_survives_to_the_workbook(projects_root: Path) -> None:
    store = create_project(projects_root, make_config())
    name = "inventory_mixed_ja.txt"
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(name)]), intake_path(name))
    sheet = load_workbook(result.xlsx_path)["業務要件"]
    assert sheet["D9"].value == "在庫数のリアルタイム確認"


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_model_produces_a_structurally_valid_brd(store: ProjectStore) -> None:
    llm = AnthropicLLM(os.environ.get("MASTERBA_MODEL", "claude-sonnet-5-5"))
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert len(result.requirement_ids) >= 3
    assert result.xlsx_path.exists()
    shutil.copy(result.xlsx_path, store.root / "live-review.xlsx")  # for the manual review
