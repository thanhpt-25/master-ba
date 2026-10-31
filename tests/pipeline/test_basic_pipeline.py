import json
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook

from factories import (
    design_ref,
    draft_for,
    intake_path,
    login_design_answered,
    login_design_draft,
    login_srs_draft,
    login_test_draft,
    login_test_draft_with_exclusions,
    login_test_draft_with_question,
    make_config,
    qa_block,
    qa_pass,
    srs_ref,
)
from masterba.agents import BasicDesignDraft, DraftDesignItem, QaIssue, QaReport, TestDraft
from masterba.llm import FakeLLM
from masterba.models import BasicDesignContent, TestSpecContent
from masterba.models.enums import BasicDesignKind, TeamRunStatus
from masterba.pipeline import (
    DESIGN_DOC_ID,
    IT_DOC_ID,
    ST_DOC_ID,
    StageResult,
    assign_basic_ids,
    run_basic_design,
    run_brd,
    run_srs,
)
from masterba.team import DesignTestResult
from masterba.trace_store import (
    DuplicateIdError,
    NotFoundError,
    ProjectStore,
    create_project,
    get_document,
    get_trace_links,
    query_impact,
    rtm,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"


def build_srs(store: ProjectStore) -> ProjectStore:
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    return store


@pytest.fixture
def with_srs(store: ProjectStore) -> ProjectStore:
    return build_srs(store)


def basic(
    store: ProjectStore,
    designs: list[BasicDesignDraft],
    tests: list[TestDraft],
    reports: list[QaReport],
) -> tuple[StageResult, FakeLLM, FakeLLM, FakeLLM]:
    designer, tester, qa = FakeLLM(designs), FakeLLM(tests), FakeLLM(reports)
    result = run_basic_design(store, TEMPLATES, designer, tester_llm=tester, qa_llm=qa)
    return result, designer, tester, qa


def happy(store: ProjectStore) -> StageResult:
    designs, tests = [login_design_draft()], [login_test_draft()]
    return basic(store, designs, tests, [qa_pass(), qa_pass()])[0]


def test_brd_srs_basic_end_done_with_three_documents_and_workbooks(
    with_srs: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    result = happy(with_srs)
    assert result.status is TeamRunStatus.DONE
    assert result.document_ids == (DESIGN_DOC_ID, IT_DOC_ID, ST_DOC_ID)
    assert result.run_id == "RUN-0003"
    for doc_id, kind in (
        (DESIGN_DOC_ID, "basic_design"),
        (IT_DOC_ID, "test_it"),
        (ST_DOC_ID, "test_st"),
    ):
        path = with_srs.path / "xlsx" / kind / f"{doc_id}.v1.xlsx"
        assert load_workbook(path).sheetnames
    prefixes = [m.split("(")[0] for m in reversed(commit_log()[:21])]
    assert prefixes == ["doc"] * 3 + ["trace"] * 14 + ["render"] * 3 + ["run"]
    assert commit_log()[0] == "run(PRJ-001): RUN-0003 done"


def test_rtm_reaches_both_an_it_case_and_an_st_case(with_srs: ProjectStore) -> None:
    happy(with_srs)
    ends = {path[-1] for path in rtm(with_srs, "REQ-0001")}
    assert {f"{IT_DOC_ID}#item.1", f"{ST_DOC_ID}#item.1"} <= ends
    upstream = {n.node_id for n in query_impact(with_srs, "TC-ST-0001", "upstream")}
    assert {srs_ref(1), "REQ-0001"} <= upstream
    it_upstream = [n.node_id for n in query_impact(with_srs, "TC-IT-0001", "upstream")]
    assert it_upstream[:2] == [design_ref(1), srs_ref(1)]


def test_stored_documents_carry_the_traceability_fields(with_srs: ProjectStore) -> None:
    happy(with_srs)
    _, design = get_document(with_srs, DESIGN_DOC_ID)
    assert isinstance(design, BasicDesignContent)
    assert design.items[1].realizes == [srs_ref(1)]
    _, it = get_document(with_srs, IT_DOC_ID)
    _, st = get_document(with_srs, ST_DOC_ID)
    assert isinstance(it, TestSpecContent)
    assert isinstance(st, TestSpecContent)
    assert [c.test_id for c in it.items] == [f"TC-IT-000{n}" for n in range(1, 6)]
    assert [c.test_id for c in st.items] == [f"TC-ST-000{n}" for n in range(1, 5)]
    assert it.items[2].verifies == [design_ref(3)]
    assert st.items[3].verifies == [srs_ref(4)]
    assert len(get_trace_links(with_srs)) == 5 + 4 + 14  # BRD, SRS, then Basic Design and tests


def test_exclusions_are_stored_with_the_right_document(with_srs: ProjectStore) -> None:
    basic(
        with_srs,
        [login_design_draft()],
        [login_test_draft_with_exclusions()],
        [qa_pass(), qa_pass()],
    )
    _, it = get_document(with_srs, IT_DOC_ID)
    _, st = get_document(with_srs, ST_DOC_ID)
    assert isinstance(it, TestSpecContent)
    assert isinstance(st, TestSpecContent)
    assert [(e.item_ref, e.reason) for e in it.exclusions] == [
        (design_ref(4), "Needs a production monitoring setup.")
    ]
    assert [(e.item_ref, e.reason) for e in st.exclusions] == [
        (srs_ref(3), "Cannot be shown in a test period.")
    ]
    assert len(it.items) == 4
    assert len(st.items) == 3


def test_a_tester_question_is_answered_into_the_design_and_the_run_ends_done(
    with_srs: ProjectStore,
) -> None:
    result, designer, tester, _ = basic(
        with_srs,
        [login_design_draft(), login_design_answered()],
        [login_test_draft_with_question(), login_test_draft()],
        [qa_pass(), qa_pass()],
    )
    assert (result.status, result.rounds, result.exchanges) == (TeamRunStatus.DONE, 1, 1)
    _, design = get_document(with_srs, DESIGN_DOC_ID)
    assert isinstance(design, BasicDesignContent)
    assert "8 to 64 characters" in design.items[1].description
    mailbox = json.loads((with_srs.path / "runs" / "RUN-0003" / "mailbox.json").read_text("utf-8"))
    assert [(m["sender"], m["type"], m["ref"]) for m in mailbox] == [
        ("tester", "question", design_ref(2)),
        ("designer", "answer", design_ref(2)),
    ]
    assert "question" in designer.calls[1].user
    assert "answer to" in tester.calls[1].user


def test_a_blocking_issue_on_a_test_goes_to_the_tester_only(with_srs: ProjectStore) -> None:
    blocked = qa_block("TS-02", f"{IT_DOC_ID}#item.2", "No boundary case.")
    result, designer, tester, qa = basic(
        with_srs,
        [login_design_draft()],
        [login_test_draft(), login_test_draft()],
        [qa_pass(), blocked, qa_pass(), qa_pass()],
    )
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert (result.issues_raised, result.issues_resolved) == (1, 1)
    assert len(designer.calls) == 1
    assert len(tester.calls) == 2
    assert "No boundary case." in tester.calls[1].user
    mailbox = json.loads((with_srs.path / "runs" / "RUN-0003" / "mailbox.json").read_text("utf-8"))
    assert [(m["sender"], m["to"], m["ref"]) for m in mailbox] == [
        ("qa", "tester", f"{IT_DOC_ID}#item.2")
    ]
    assert "TS-01" in qa.calls[1].system
    assert "BD-01" in qa.calls[0].system


def test_a_blocking_issue_on_the_design_sends_both_agents_back_to_work(
    with_srs: ProjectStore,
) -> None:
    blocked = qa_block("BD-02", design_ref(1), "No limits stated.")
    result, designer, tester, _ = basic(
        with_srs,
        [login_design_draft(), login_design_draft()],
        [login_test_draft(), login_test_draft()],
        [blocked, qa_pass(), qa_pass(), qa_pass()],
    )
    assert result.status is TeamRunStatus.DONE
    assert (len(designer.calls), len(tester.calls)) == (2, 2)
    assert "the design was revised" in tester.calls[1].user


def test_a_design_that_misses_an_srs_item_goes_back_without_a_qa_call(
    with_srs: ProjectStore,
) -> None:
    incomplete = BasicDesignDraft(items=login_design_draft().items[:3])
    result, designer, _, qa = basic(
        with_srs,
        [incomplete, login_design_draft()],
        [login_test_draft()],
        [qa_pass(), qa_pass()],
    )
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 2)
    assert "SRS items not realised by any design item" in designer.calls[1].user
    assert len(qa.calls) == 2


def test_never_satisfying_qa_escalates_and_writes_no_document(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = build_srs(create_project(projects_root, make_config(max_rounds=1)))
    blocked = qa_block("TS-01", f"{IT_DOC_ID}#item.1", "Vague.")
    result, *_ = basic(store, [login_design_draft()], [login_test_draft()], [qa_pass(), blocked])
    assert result.status is TeamRunStatus.ESCALATED
    assert result.escalations[0] == "max rounds reached (1)"
    assert commit_log()[0] == "run(PRJ-001): RUN-0003 escalated"
    for doc_id in (DESIGN_DOC_ID, IT_DOC_ID, ST_DOC_ID):
        with pytest.raises(NotFoundError):
            get_document(store, doc_id)
    assert not (store.path / "xlsx" / "basic_design").exists()


def test_the_stage_needs_an_srs_and_refuses_a_second_run(
    store: ProjectStore, with_srs: ProjectStore
) -> None:
    happy(with_srs)
    unused = FakeLLM([])
    with pytest.raises(DuplicateIdError, match="Decision Record"):
        run_basic_design(with_srs, TEMPLATES, unused)
    assert unused.calls == []


def test_without_an_srs_the_stage_refuses_to_start(store: ProjectStore) -> None:
    with pytest.raises(NotFoundError, match="run the srs stage first"):
        run_basic_design(store, TEMPLATES, FakeLLM([]))


def test_assign_basic_ids_numbers_everything_and_dedupes_links() -> None:
    items = [
        DraftDesignItem(
            kind=BasicDesignKind.FUNCTION,
            name="F",
            description="d",
            realizes=[srs_ref(1), srs_ref(2), srs_ref(1)],
        )
    ]
    tests = TestDraft(
        it_cases=[
            login_test_draft().it_cases[0].model_copy(update={"verifies": [design_ref(1)] * 2})
        ],
        st_cases=[login_test_draft().st_cases[0]],
    )
    out = assign_basic_ids(
        DesignTestResult(BasicDesignDraft(items=items), tests), project_id="PRJ-001"
    )
    assert [d.id for d, _ in out.documents] == [DESIGN_DOC_ID, IT_DOC_ID, ST_DOC_ID]
    pairs = [(link.from_id, link.to_id, link.link_type.value) for link in out.links]
    assert pairs == [
        (srs_ref(1), design_ref(1), "realizes"),
        (srs_ref(2), design_ref(1), "realizes"),
        (design_ref(1), "TC-IT-0001", "tests"),
        (srs_ref(1), "TC-ST-0001", "tests"),
    ]


def test_a_question_that_stays_open_after_the_answer_is_reported_not_blocking(
    with_srs: ProjectStore,
) -> None:
    again = login_test_draft_with_question()
    result, *_ = basic(
        with_srs,
        [login_design_draft(), login_design_answered()],
        [login_test_draft_with_question(), again],
        [qa_pass(), qa_pass()],
    )
    assert result.status is TeamRunStatus.DONE
    assert result.open_questions == (
        f"{design_ref(2)}: What are the minimum and maximum password lengths?",
    )


def test_a_blocking_issue_that_names_no_action_does_not_block_the_run(
    with_srs: ProjectStore,
) -> None:
    # Regression for spec 05 run 4: the last blocking issue said the case "is acceptable as
    # written". Without `action_required` it is advisory (spec 11 section 1), so the run is done.
    ref = f"{ST_DOC_ID}#item.1"
    acceptable = QaReport(
        issues=[
            QaIssue(
                checklist_id="TS-02",
                severity="blocking",
                ref=ref,
                message="None are specified for this item, so this case is acceptable as written.",
            )
        ]
    )
    result, *_ = basic(
        with_srs, [login_design_draft()], [login_test_draft()], [qa_pass(), acceptable]
    )
    assert (result.status, result.rounds) == (TeamRunStatus.DONE, 1)
    assert any(ref in issue for issue in result.advisory)
    mailbox = json.loads(
        (with_srs.path / "runs" / result.run_id / "mailbox.json").read_text("utf-8")
    )
    assert f"[TS-02] {ref}: downgraded (no action required)" in [m["body"] for m in mailbox]
