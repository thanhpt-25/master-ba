import pytest

from masterba.agents import QaIssue
from masterba.models import QuestionDraft
from masterba.models.enums import DocType, QuestionOrigin, TeamRunStatus
from masterba.team import Team
from masterba.team.workspace import OBJECTION_CAP
from masterba.trace_store import ProjectStore


@pytest.fixture
def team(store: ProjectStore) -> Team:
    return Team.open(store, DocType.SRS, max_rounds=3, token_budget=None)


def asked(text: str) -> QuestionDraft:
    return QuestionDraft(refs=[], text=text)


def blocker(number: int, ref: str | None = "DOC-SRS-0001#item.1") -> QaIssue:
    return QaIssue(
        checklist_id="SRS-02",
        severity="blocking",
        ref=ref,
        message=f"Point {number}.",
        action_required="Fix.",
    )


def test_writer_questions_are_replaced_and_the_others_accumulate(team: Team) -> None:
    team.offer_questions("writer", [asked("A?")], replace=True)
    team.offer_questions("writer", [asked("B?")], replace=True)
    team.offer_questions("qa", [asked("C?")])
    team.offer_questions("qa", [asked("D?")])
    assert [q.text for q in team.collected_questions()] == ["B?", "C?", "D?"]


def test_objections_are_collected_only_for_an_escalated_run(team: Team) -> None:
    team.hold_objection("writer", [blocker(1)])
    assert team.collected_questions() == []
    [objection] = team.collected_questions(escalated=True)
    assert objection.origin is QuestionOrigin.QA_BLOCKER
    assert objection.text == (
        f"QA (SRS-02), {team.run_id}, DOC-SRS-0001#item.1 of the draft: Point 1. "
        "Specify the missing detail or accept the draft as it is."
    )


def test_an_objection_without_a_reference_names_the_draft(team: Team) -> None:
    team.hold_objection("writer", [blocker(1, ref=None)])
    [objection] = team.collected_questions(escalated=True)
    assert ", the draft: Point 1." in objection.text


def test_a_later_review_replaces_the_objections_of_that_owner(team: Team) -> None:
    team.hold_objection("designer", [blocker(1)])
    team.hold_objection("designer", [blocker(2)])
    team.hold_objection("tester", [blocker(3)])
    texts = [q.text for q in team.collected_questions(escalated=True)]
    assert [("Point 2." in t, "Point 3." in t) for t in texts] == [(True, False), (False, True)]


def test_more_than_the_cap_are_left_out_and_noted_in_the_run_record(team: Team) -> None:
    team.hold_objection("writer", [blocker(n) for n in range(OBJECTION_CAP + 3)])
    team.escalate(["max rounds reached (3)"])
    summary = team.finish(TeamRunStatus.ESCALATED)
    assert len(team.collected_questions(escalated=True)) == OBJECTION_CAP
    assert summary.escalations[-1] == "3 more QA objections were not recorded as questions"
