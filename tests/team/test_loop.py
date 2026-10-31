from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from masterba.agents import QaIssue, QaOutputInvalidError, QaReport, QaReview
from masterba.llm import LLMResult
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team import MessageType, TaskStatus, Team, run_writer_review
from masterba.trace_store import ProjectStore

REF = "DOC-BRD-0001#item.1"


class Draft(BaseModel):
    text: str


class Script:
    """Scripted writer, gate and reviewer that record how they were called."""

    def __init__(
        self,
        reports: list[QaReport | QaOutputInvalidError],
        gates: list[list[str]] | None = None,
        writer_tokens: tuple[int, int] = (20, 10),
        qa_tokens: tuple[int, int] = (8, 2),
    ) -> None:
        self.reports = reports
        self.gates = gates or []
        self.writer_tokens = writer_tokens
        self.qa_tokens = qa_tokens
        self.writes: list[tuple[Draft | None, Sequence[str]]] = []
        self.reviews = 0

    def write(self, previous: Draft | None, feedback: Sequence[str]) -> LLMResult[Draft]:
        self.writes.append((previous, list(feedback)))
        return LLMResult(Draft(text=f"draft {len(self.writes)}"), *self.writer_tokens)

    def gate(self, draft: Draft) -> list[str]:
        return self.gates.pop(0) if self.gates else []

    def review(self, draft: Draft) -> QaReview:
        report = self.reports[self.reviews]
        self.reviews += 1
        if isinstance(report, QaOutputInvalidError):
            raise report
        return QaReview(report, *self.qa_tokens, attempts=1)


def block(message: str = "Split it.", ref: str | None = REF) -> QaReport:
    return QaReport(
        issues=[QaIssue(checklist_id="BRD-01", severity="blocking", ref=ref, message=message)]
    )


def run(team: Team, script: Script) -> Draft | None:
    return run_writer_review(team, write=script.write, gate=script.gate, review=script.review)


@pytest.fixture
def team(store: ProjectStore) -> Team:
    return Team.open(store, DocType.BRD, max_rounds=3, token_budget=None)


def test_accepted_in_the_first_round(team: Team) -> None:
    script = Script([QaReport()])
    draft = run(team, script)
    assert draft == Draft(text="draft 1")
    assert (team.rounds, team.issues_raised, team.issues_resolved) == (1, 0, 0)
    assert [(t.id, t.title, t.owner, t.status) for t in team.tasks] == [
        ("T-01", "Draft", "writer", TaskStatus.DONE),
        ("T-02", "Review (round 1)", "qa", TaskStatus.DONE),
    ]
    assert team.tasks[1].depends_on == ["T-01"]
    assert team.tokens_used == 40
    assert team.messages == []


def test_blocking_feedback_reaches_the_writer_and_the_next_draft_passes(team: Team) -> None:
    script = Script([block("Split this item."), QaReport()])
    assert run(team, script) == Draft(text="draft 2")
    previous, feedback = script.writes[1]
    assert previous == Draft(text="draft 1")
    assert feedback == [f"[BRD-01] {REF}: Split this item."]
    assert (team.rounds, team.issues_raised, team.issues_resolved) == (2, 1, 1)
    [message] = team.messages
    assert (message.sender, message.to, message.type, message.ref, message.round) == (
        "qa",
        "writer",
        MessageType.FEEDBACK,
        REF,
        1,
    )
    assert [t.title for t in team.tasks] == [
        "Draft",
        "Review (round 1)",
        "Revise (round 2)",
        "Review (round 2)",
    ]
    assert all(t.status is TaskStatus.DONE for t in team.tasks)


def test_a_model_that_never_satisfies_qa_escalates_after_exactly_max_rounds(team: Team) -> None:
    script = Script([block(), block(), block()])
    assert run(team, script) is None
    assert len(script.writes) == 3
    assert team.rounds == 3
    assert team.escalations[0] == "max rounds reached (3)"
    assert f"[BRD-01] {REF}: Split it." in team.escalations
    assert (team.issues_raised, team.issues_resolved) == (3, 2)


def test_gate_errors_go_back_to_the_writer_without_a_review(team: Team) -> None:
    script = Script([QaReport()], gates=[["quote not found"], []])
    assert run(team, script) == Draft(text="draft 2")
    assert script.reviews == 1
    assert script.writes[1][1] == ["quote not found"]
    [message] = team.messages
    assert (message.sender, message.ref) == ("gate", None)
    assert [t.title for t in team.tasks] == ["Draft", "Revise (round 2)", "Review (round 2)"]


def test_gate_errors_in_every_round_escalate_without_ever_calling_qa(team: Team) -> None:
    script = Script([], gates=[["bad"], ["bad"], ["bad"]])
    assert run(team, script) is None
    assert script.reviews == 0
    assert team.escalations == ["max rounds reached (3)", "bad"]


def test_budget_stops_before_the_qa_call_once_the_writer_used_it_up(store: ProjectStore) -> None:
    team = Team.open(store, DocType.BRD, max_rounds=3, token_budget=25)
    script = Script([QaReport()])
    assert run(team, script) is None
    assert script.reviews == 0
    assert team.escalations == ["token budget exhausted (30/25)"]


def test_budget_stops_before_the_next_writer_call(store: ProjectStore) -> None:
    team = Team.open(store, DocType.BRD, max_rounds=5, token_budget=100)
    script = Script([block(), block(), block()], writer_tokens=(30, 10), qa_tokens=(8, 2))
    assert run(team, script) is None
    assert len(script.writes) == 2
    assert team.tokens_used == 100
    assert team.escalations[0] == "token budget exhausted (100/100)"


def test_an_unusable_qa_report_escalates_and_still_counts_its_tokens(team: Team) -> None:
    script = Script([QaOutputInvalidError(["unknown checklist_id"], 7, 3)])
    assert run(team, script) is None
    assert team.escalations == ["qa output invalid: unknown checklist_id"]
    assert team.tokens_used == 30 + 10


def test_advisory_issues_do_not_block_but_are_recorded(team: Team) -> None:
    advisory = QaReport(
        issues=[QaIssue(checklist_id="BRD-04", severity="advisory", ref=None, message="Vague.")]
    )
    assert run(team, Script([advisory])) == Draft(text="draft 1")
    assert team.advisory == ["[BRD-04] document: Vague."]
    assert team.issues_raised == 0
    assert [m.ref for m in team.messages] == [None]


def test_summary_of_an_escalated_run_blocks_open_tasks(team: Team) -> None:
    run(team, Script([block(), block(), block()]))
    summary = team.finish(TeamRunStatus.ESCALATED)
    assert summary.status is TeamRunStatus.ESCALATED
    assert summary.rounds == 3
    assert all(t.status in {TaskStatus.DONE, TaskStatus.BLOCKED} for t in team.tasks)
