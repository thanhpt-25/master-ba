import json
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook

from factories import (
    design_ref,
    detail_ref,
    draft_for,
    intake_path,
    login_design_draft,
    login_detail_answered,
    login_detail_draft,
    login_srs_draft,
    login_test_draft,
    login_unit_draft,
    login_unit_draft_with_exclusion,
    login_unit_draft_with_question,
    make_config,
    qa_block,
    qa_pass,
    srs_ref,
)
from masterba.agents import DetailDesignDraft, DraftDetailItem, QaReport, UnitTestDraft
from masterba.llm import FakeLLM
from masterba.models import DetailDesignContent, TestSpecContent
from masterba.models.enums import DetailDesignKind, TeamRunStatus
from masterba.pipeline import (
    DESIGN_DOC_ID,
    DETAIL_DOC_ID,
    UT_DOC_ID,
    StageResult,
    assign_detail_ids,
    run_basic_design,
    run_brd,
    run_detail_design,
    run_srs,
)
from masterba.team import DesignTestResult
from masterba.trace_store import (
    DuplicateIdError,
    NotFoundError,
    ProjectStore,
    create_project,
    get_document,
    query_impact,
    rtm,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"


def build_basic(store: ProjectStore) -> ProjectStore:
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    run_basic_design(
        store,
        TEMPLATES,
        FakeLLM([login_design_draft()]),
        tester_llm=FakeLLM([login_test_draft()]),
        qa_llm=FakeLLM([qa_pass(), qa_pass()]),
    )
    return store


@pytest.fixture
def with_basic(store: ProjectStore) -> ProjectStore:
    return build_basic(store)


def detail(
    store: ProjectStore,
    designs: list[DetailDesignDraft],
    tests: list[UnitTestDraft],
    reports: list[QaReport],
) -> tuple[StageResult, FakeLLM, FakeLLM, FakeLLM]:
    designer, tester, qa = FakeLLM(designs), FakeLLM(tests), FakeLLM(reports)
    result = run_detail_design(store, TEMPLATES, designer, tester_llm=tester, qa_llm=qa)
    return result, designer, tester, qa


def happy(store: ProjectStore) -> StageResult:
    designs, tests = [login_detail_draft()], [login_unit_draft()]
    return detail(store, designs, tests, [qa_pass(), qa_pass()])[0]


def test_the_whole_chain_ends_done_with_two_more_documents(
    with_basic: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    result = happy(with_basic)
    assert result.status is TeamRunStatus.DONE
    assert result.document_ids == (DETAIL_DOC_ID, UT_DOC_ID)
    assert result.run_id == "RUN-0004"
    for doc_id, kind in ((DETAIL_DOC_ID, "detail_design"), (UT_DOC_ID, "test_ut")):
        path = with_basic.path / "xlsx" / kind / f"{doc_id}.v1.xlsx"
        assert load_workbook(path).sheetnames
    assert commit_log()[0] == "run(PRJ-001): RUN-0004 done"
    subjects = list(reversed(commit_log()[:16]))
    kinds = [m.split("(")[0] for m in subjects]
    assert kinds == ["doc"] * 2 + ["trace"] * 11 + ["render"] * 2 + ["run"]


def test_rtm_reaches_it_st_and_ut_cases(with_basic: ProjectStore) -> None:
    happy(with_basic)
    ends = {path[-1] for path in rtm(with_basic, "REQ-0001")}
    assert {
        "DOC-TEST_IT-0001#item.1",
        "DOC-TEST_ST-0001#item.1",
        "DOC-TEST_UT-0001#item.1",
    } <= ends
    upstream = [n.node_id for n in query_impact(with_basic, "TC-UT-0001", "upstream")]
    assert upstream[0] == detail_ref(1)
    assert set(upstream[1:3]) == {design_ref(1), design_ref(2)}
    assert srs_ref(1) in upstream
    assert "REQ-0001" in upstream


def test_stored_documents_carry_the_traceability_fields(with_basic: ProjectStore) -> None:
    happy(with_basic)
    _, detail_content = get_document(with_basic, DETAIL_DOC_ID)
    assert isinstance(detail_content, DetailDesignContent)
    assert detail_content.items[0].refines == [design_ref(1), design_ref(2)]
    _, ut = get_document(with_basic, UT_DOC_ID)
    assert isinstance(ut, TestSpecContent)
    assert [c.test_id for c in ut.items] == [f"TC-UT-000{n}" for n in range(1, 6)]
    assert ut.items[2].verifies == [detail_ref(3)]


def test_exclusions_are_stored_in_the_ut_document(with_basic: ProjectStore) -> None:
    detail(with_basic, [login_detail_draft()], [login_unit_draft_with_exclusion()], [qa_pass()] * 2)
    _, ut = get_document(with_basic, UT_DOC_ID)
    assert isinstance(ut, TestSpecContent)
    assert [(e.item_ref, e.reason) for e in ut.exclusions] == [
        (detail_ref(4), "A policy, not executable code.")
    ]
    assert len(ut.items) == 4


def test_a_question_is_answered_into_the_spec_in_the_same_cycle(with_basic: ProjectStore) -> None:
    result, designer, tester, _ = detail(
        with_basic,
        [login_detail_draft(), login_detail_answered()],
        [login_unit_draft_with_question(), login_unit_draft()],
        [qa_pass(), qa_pass()],
    )
    assert (result.status, result.rounds, result.exchanges) == (TeamRunStatus.DONE, 1, 1)
    _, content = get_document(with_basic, DETAIL_DOC_ID)
    assert isinstance(content, DetailDesignContent)
    assert "locks for 15 minutes" in content.items[1].spec
    mailbox = json.loads(
        (with_basic.path / "runs" / "RUN-0004" / "mailbox.json").read_text("utf-8")
    )
    assert [(m["sender"], m["type"], m["ref"]) for m in mailbox] == [
        ("tester", "question", detail_ref(2)),
        ("designer", "answer", detail_ref(2)),
    ]
    assert "question" in designer.calls[1].user
    assert "answer to" in tester.calls[1].user


def test_a_repeated_question_about_an_answered_item_is_reported_not_blocking(
    with_basic: ProjectStore,
) -> None:
    result, *_ = detail(
        with_basic,
        [login_detail_draft(), login_detail_answered()],
        [login_unit_draft_with_question(), login_unit_draft_with_question()],
        [qa_pass(), qa_pass()],
    )
    assert result.status is TeamRunStatus.DONE
    assert result.open_questions == (
        f"{detail_ref(2)}: How many failed attempts lock the account?",
    )


def test_issues_are_routed_by_document(with_basic: ProjectStore) -> None:
    blocked = qa_block("UT-02", "DOC-TEST_UT-0001#item.2", "No boundary case.")
    result, designer, tester, qa = detail(
        with_basic,
        [login_detail_draft()],
        [login_unit_draft(), login_unit_draft()],
        [qa_pass(), blocked, qa_pass(), qa_pass()],
    )
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert (result.issues_raised, result.issues_resolved) == (1, 1)
    assert len(designer.calls) == 1
    assert len(tester.calls) == 2
    assert "UT-01" in qa.calls[1].system
    assert "DD-01" in qa.calls[0].system
    mailbox = json.loads(
        (with_basic.path / "runs" / "RUN-0004" / "mailbox.json").read_text("utf-8")
    )
    assert [(m["sender"], m["to"]) for m in mailbox] == [("qa", "tester")]


def test_a_detail_design_missing_a_basic_item_goes_back_without_a_qa_call(
    with_basic: ProjectStore,
) -> None:
    incomplete = DetailDesignDraft(items=login_detail_draft().items[:3])
    result, designer, _, qa = detail(
        with_basic,
        [incomplete, login_detail_draft()],
        [login_unit_draft()],
        [qa_pass(), qa_pass()],
    )
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert "not refined by any detail item" in designer.calls[1].user
    assert len(qa.calls) == 2


def test_escalation_writes_no_document(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = build_basic(create_project(projects_root, make_config(max_rounds=1)))
    blocked = qa_block("UT-01", "DOC-TEST_UT-0001#item.1", "Vague.")
    result, *_ = detail(store, [login_detail_draft()], [login_unit_draft()], [qa_pass(), blocked])
    assert result.status is TeamRunStatus.ESCALATED
    assert commit_log()[0].endswith("escalated")
    for doc_id in (DETAIL_DOC_ID, UT_DOC_ID):
        with pytest.raises(NotFoundError):
            get_document(store, doc_id)


def test_the_stage_needs_a_basic_design_and_refuses_a_second_run(
    store: ProjectStore, with_basic: ProjectStore
) -> None:
    happy(with_basic)
    unused = FakeLLM([])
    with pytest.raises(DuplicateIdError, match="Decision Record"):
        run_detail_design(with_basic, TEMPLATES, unused)
    assert unused.calls == []


def test_without_a_basic_design_the_stage_refuses_to_start(store: ProjectStore) -> None:
    with pytest.raises(NotFoundError, match="run the basic stage first"):
        run_detail_design(store, TEMPLATES, FakeLLM([]))
    assert DESIGN_DOC_ID == "DOC-BASIC_DESIGN-0001"


def test_assign_detail_ids_numbers_everything_and_dedupes_links() -> None:
    items = [
        DraftDetailItem(
            kind=DetailDesignKind.MODULE,
            name="M",
            spec="s",
            refines=[design_ref(1), design_ref(2), design_ref(1)],
        )
    ]
    tests = UnitTestDraft(
        ut_cases=[
            login_unit_draft().ut_cases[0].model_copy(update={"verifies": [detail_ref(1)] * 2})
        ]
    )
    out = assign_detail_ids(
        DesignTestResult(DetailDesignDraft(items=items), tests), project_id="PRJ-001"
    )
    assert [d.id for d, _ in out.documents] == [DETAIL_DOC_ID, UT_DOC_ID]
    pairs = [(link.from_id, link.to_id, link.link_type.value) for link in out.links]
    assert pairs == [
        (design_ref(1), detail_ref(1), "realizes"),
        (design_ref(2), detail_ref(1), "realizes"),
        (detail_ref(1), "TC-UT-0001", "tests"),
    ]
