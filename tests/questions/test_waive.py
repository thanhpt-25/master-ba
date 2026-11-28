"""Waiving a QA objection: the customer accepts the draft as it is (spec 13 section 6.1)."""

import datetime as dt

import pytest

from masterba.agents import QaIssue
from masterba.models import QuestionDraft
from masterba.models.enums import DocType, QuestionOrigin
from masterba.questions import record_questions
from masterba.questions.answer import QuestionError, answer_question
from masterba.questions.facts import attach_facts
from masterba.team import Team
from masterba.team.workspace import objection_key
from masterba.trace_store import ProjectStore, get_question

ISSUE = QaIssue(
    checklist_id="BRD-01",
    severity="blocking",
    ref="DOC-BRD-0001#item.1",
    message="Not grounded.",
    action_required="Remove it.",
)


def objection_for(store: ProjectStore, team: Team) -> str:
    """Record the team's objection to ISSUE as a QA blocker question; return its id."""
    team.hold_objection("draft", [ISSUE])
    drafts = team.collected_questions(escalated=True)
    return record_questions(store, team.run_id, DocType.BRD, drafts).ids[0]


def waive(store: ProjectStore, qid: str) -> None:
    answer_question(store, qid, "Keep it.", "alice", today=lambda: dt.date(2026, 11, 2), waive=True)


def test_the_objection_text_is_read_back_as_its_key(store: ProjectStore) -> None:
    team = Team.open(store, DocType.BRD, 3, None)
    qid = objection_for(store, team)
    question = get_question(store, qid)
    assert question.origin is QuestionOrigin.QA_BLOCKER
    assert objection_key(question.text) == (team.run_id, "BRD-01", "DOC-BRD-0001#item.1")
    assert objection_key("BD-02: a question QA raised for the customer") is None


def test_a_waived_objection_no_longer_blocks_its_run(store: ProjectStore) -> None:
    team = Team.open(store, DocType.BRD, 3, None)
    qid = objection_for(store, team)
    waive(store, qid)
    assert get_question(store, qid).waived

    attach_facts(team)
    settled, notes = team.settle("draft", [ISSUE, ISSUE.model_copy(update={"ref": None})])

    assert [i.severity for i in settled] == ["advisory", "blocking"]
    assert notes == [f"[BRD-01] DOC-BRD-0001#item.1: waived by the customer ({qid})"]


def test_a_waiver_applies_only_to_the_run_that_raised_it(store: ProjectStore) -> None:
    first = Team.open(store, DocType.BRD, 3, None)
    waive(store, objection_for(store, first))
    other = Team.open(store, DocType.BRD, 3, None)
    attach_facts(other)
    settled, _ = other.settle("draft", [ISSUE])
    assert settled[0].severity == "blocking"


def test_only_a_qa_objection_can_be_waived(store: ProjectStore) -> None:
    qid = record_questions(
        store, "RUN-0001", DocType.SRS, [QuestionDraft(text="What counts as a day?")]
    ).ids[0]
    with pytest.raises(QuestionError, match="not a QA objection"):
        waive(store, qid)
    assert not get_question(store, qid).waived
