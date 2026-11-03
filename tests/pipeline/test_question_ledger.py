"""Stages record their open questions in the ledger (spec 13 section 3)."""

from pathlib import Path

from factories import (
    draft_for,
    incomplete_srs_draft,
    intake_path,
    login_design_answered,
    login_design_draft,
    login_srs_draft,
    login_test_draft_with_question,
    make_config,
    qa_block,
    qa_pass,
)
from masterba.llm import FakeLLM
from masterba.models import QuestionDraft
from masterba.models.enums import DocType, QuestionOrigin, TeamRunStatus
from masterba.pipeline import SRS_DOC_ID, Resume, run_basic_design, run_brd, run_srs
from masterba.questions import record_questions
from masterba.questions.answer import answer_question
from masterba.trace_store import ProjectStore, create_project, get_question, list_questions

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"


def with_brd(projects_root: Path, max_rounds: int = 3) -> ProjectStore:
    store = create_project(projects_root, make_config(max_rounds=max_rounds))
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    return store


def test_a_brd_open_question_is_recorded_with_its_intake_lines(projects_root: Path) -> None:
    store = create_project(projects_root, make_config())
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    question = get_question(store, "Q-0001")
    assert question.text == "What response time counts as fast?"
    assert question.refs == ["intake/login_system.txt#L8-L8"]
    assert (question.stage.value, question.run_id) == ("BRD", result.run_id)
    assert (result.question_ids, result.reasked) == (("Q-0001",), 0)


def test_an_escalated_run_records_the_objections_qa_still_held(projects_root: Path) -> None:
    store = with_brd(projects_root, max_rounds=1)
    blocked = qa_block("SRS-01", f"{SRS_DOC_ID}#item.1", "Two obligations.")
    result = run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), blocked]))
    assert result.status is TeamRunStatus.ESCALATED
    [objection] = [q for q in list_questions(store) if q.origin is QuestionOrigin.QA_BLOCKER]
    assert "Two obligations." in objection.text and "SRS-01" in objection.text
    assert objection.refs == []  # the draft's own item does not exist as a stored node
    assert objection.id in result.question_ids


def test_gate_errors_are_not_questions(projects_root: Path) -> None:
    store = with_brd(projects_root, max_rounds=1)
    before = len(list_questions(store))
    result = run_srs(store, TEMPLATES, FakeLLM([incomplete_srs_draft()]))
    assert result.status is TeamRunStatus.ESCALATED
    assert len(list_questions(store)) == before


def test_an_unanswered_tester_question_is_recorded_after_a_basic_design_run(
    projects_root: Path,
) -> None:
    store = with_brd(projects_root)
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    asking = login_test_draft_with_question()
    result = run_basic_design(
        store,
        TEMPLATES,
        FakeLLM([login_design_draft(), login_design_answered()]),
        tester_llm=FakeLLM([asking, asking]),
        qa_llm=FakeLLM([qa_pass(), qa_pass()]),
    )
    assert result.status is TeamRunStatus.DONE
    texts = [q.text for q in list_questions(store)]
    assert "What are the minimum and maximum password lengths?" in texts
    assert result.question_ids


def answered(store: ProjectStore, text: str = "Does the limit count business days?") -> None:
    record_questions(store, "RUN-0001", DocType.SRS, [QuestionDraft(refs=[], text=text)])
    answer_question(store, "Q-0002", "Business days only.", "alice")


def test_a_confirmed_fact_reaches_every_writer_and_qa_call(projects_root: Path) -> None:
    store = with_brd(projects_root)
    answered(store)
    llm = FakeLLM([login_srs_draft(), qa_pass()])
    run_srs(store, TEMPLATES, llm)
    assert len(llm.calls) == 2
    for call in llm.calls:
        assert "<confirmed>" in call.user and "Business days only." in call.user


def test_a_resumed_run_sees_an_answer_given_after_it_escalated(projects_root: Path) -> None:
    store = with_brd(projects_root, max_rounds=1)
    blocked = qa_block("SRS-01", f"{SRS_DOC_ID}#item.1", "Two obligations.")
    first = run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), blocked]))
    answered(store)
    llm = FakeLLM([login_srs_draft(), qa_pass()])
    run_srs(store, TEMPLATES, llm, resume=Resume(first.run_id, 1))
    assert "Business days only." in llm.calls[0].user


def test_there_is_no_block_before_an_answer(projects_root: Path) -> None:
    store = with_brd(projects_root)
    llm = FakeLLM([login_srs_draft(), qa_pass()])
    run_srs(store, TEMPLATES, llm)
    assert all("<confirmed>" not in call.user for call in llm.calls)


def test_an_open_question_reaches_every_later_call_until_it_is_answered(
    projects_root: Path,
) -> None:
    # Spec 13 section 5.1: a later stage may not decide a point the customer was asked about.
    store = with_brd(projects_root)
    open_ids = [q.id for q in list_questions(store) if q.status.value == "open"]
    assert open_ids, "the login BRD draft raises open questions"
    llm = FakeLLM([login_srs_draft(), qa_pass()])
    run_srs(store, TEMPLATES, llm)
    for call in llm.calls:
        assert "<open_questions>" in call.user and "Do not state an answer" in call.user
        assert all(qid in call.user for qid in open_ids)


def test_answered_and_withdrawn_questions_leave_the_open_block(projects_root: Path) -> None:
    from masterba.questions import open_questions, open_questions_block
    from masterba.questions.answer import withdraw_question

    store = with_brd(projects_root)
    first, *rest = [q.id for q in open_questions(store)]
    answer_question(store, first, "Yes.", "alice")
    for qid in rest:
        withdraw_question(store, qid)
    assert open_questions(store) == [] and open_questions_block([]) == ""
    llm = FakeLLM([login_srs_draft(), qa_pass()])
    run_srs(store, TEMPLATES, llm)
    assert all("<open_questions>" not in call.user for call in llm.calls)
    assert all("<confirmed>" in call.user for call in llm.calls)
