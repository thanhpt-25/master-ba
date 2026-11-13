from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from masterba.agents import QaIssue, QaOutputInvalidError, QaReport, QaReview
from masterba.llm import LLMError, LLMOutputError, LLMResult
from masterba.models import QuestionDraft
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
        issues=[
            QaIssue(
                checklist_id="BRD-01",
                severity="blocking",
                ref=ref,
                message=message,
                action_required=message,
            )
        ]
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


def test_a_model_with_unchanged_qa_blockers_stops_after_one_targeted_repair(team: Team) -> None:
    script = Script([block(), block(), block()])
    assert run(team, script) is None
    assert len(script.writes) == 2
    assert team.rounds == 2
    assert team.escalations[0].startswith("no progress:")
    assert (team.issues_raised, team.issues_resolved) == (2, 0)


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
    assert team.escalations[0].startswith("no progress:")


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
    assert summary.rounds == 2
    assert all(t.status in {TaskStatus.DONE, TaskStatus.BLOCKED} for t in team.tasks)


def test_review_notes_and_customer_questions_reach_the_team(team: Team) -> None:
    question = f"{REF}: Which tax rate applies?"
    note = f"[BRD-01] {REF}: downgraded (customer question)"

    class Asking(Script):
        def review(self, draft: Draft) -> QaReview:
            self.reviews += 1
            return QaReview(QaReport(), 8, 2, 1, (note,), (question,))

    assert run(team, Asking([])) == Draft(text="draft 1")
    assert team.customer_questions == [question]
    assert [m.body for m in team.messages] == [note]
    run_record = team.finish(TeamRunStatus.DONE)
    assert run_record.customer_questions == [question]


class Failing(Script):
    """The writer's first calls raise a schema error before they return a draft."""

    def __init__(self, reports: list[QaReport | QaOutputInvalidError], failures: int) -> None:
        super().__init__(reports)
        self.failures = failures
        self.calls = 0

    def write(self, previous: Draft | None, feedback: Sequence[str]) -> LLMResult[Draft]:
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMOutputError("items.0.realizes Field required", 7, 5)
        return super().write(previous, feedback)


UNUSABLE = "the last answer could not be used: items.0.realizes Field required"


def test_a_schema_error_from_the_writer_goes_back_as_feedback(team: Team) -> None:
    script = Failing([QaReport()], failures=1)
    assert run(team, script) == Draft(text="draft 1")
    assert script.writes == [(None, [UNUSABLE])]
    assert team.rounds == 2
    assert team.tokens_used == 7 + 5 + 30 + 10  # the failed call still used tokens
    assert [(m.sender, m.to, m.body) for m in team.messages] == [("gate", "writer", UNUSABLE)]
    team.finish(TeamRunStatus.DONE)  # the failed round's task is not left open


def test_a_schema_error_keeps_the_feedback_that_was_already_pending(team: Team) -> None:
    class AfterReview(Failing):
        def write(self, previous: Draft | None, feedback: Sequence[str]) -> LLMResult[Draft]:
            self.calls += 1
            if self.calls == 2:
                raise LLMOutputError("items.0.realizes Field required")
            return Script.write(self, previous, feedback)

    script = AfterReview([block("Split it."), QaReport()], failures=0)
    assert run(team, script) == Draft(text="draft 2")
    assert script.writes[1] == (Draft(text="draft 1"), [f"[BRD-01] {REF}: Split it.", UNUSABLE])


def test_a_schema_error_in_every_round_escalates_after_max_rounds(team: Team) -> None:
    script = Failing([], failures=99)
    assert run(team, script) is None
    assert (script.calls, script.reviews) == (3, 0)
    assert team.escalations == ["max rounds reached (3)", UNUSABLE]


def test_a_blocking_issue_that_is_new_after_the_first_review_is_downgraded(team: Team) -> None:
    other = "DOC-BRD-0001#item.2"
    script = Script([block("A", REF), block("B", other)])
    assert run(team, script) == Draft(text="draft 2")
    assert (team.rounds, team.issues_raised, team.issues_resolved) == (2, 1, 1)
    assert team.advisory == [f"[BRD-01] {other}: B"]
    assert f"[BRD-01] {other}: downgraded (new after the first review)" in [
        m.body for m in team.messages
    ]


def test_the_first_review_may_raise_any_number_of_blocking_issues(team: Team) -> None:
    many = QaReport(issues=block("A", REF).issues + block("B", "DOC-BRD-0001#item.2").issues)
    assert run(team, Script([many, QaReport()])) == Draft(text="draft 2")
    assert team.issues_raised == 2
    assert team.advisory == []


def test_question_drafts_from_qa_and_the_writer_reach_the_team(team: Team) -> None:
    asked = QuestionDraft(refs=[REF], text="Which tax rate?")

    class Asking(Script):
        def review(self, draft: Draft) -> QaReview:
            self.reviews += 1
            return QaReview(QaReport(), 8, 2, 1, (), ("q",), (asked,))

    draft = run_writer_review(
        team,
        write=(script := Asking([])).write,
        gate=script.gate,
        review=script.review,
        writer_questions=lambda d: [QuestionDraft(refs=[], text=f"Writer asks about {d.text}?")],
    )
    assert draft == Draft(text="draft 1")
    assert [q.text for q in team.collected_questions()] == [
        "Writer asks about draft 1?",
        "Which tax rate?",
    ]


def test_customer_blocker_pauses_with_a_checkpoint_without_another_writer_round(team: Team) -> None:
    question = QuestionDraft(refs=[REF], text="BRD-01: Which tax rate applies?")

    class Asking(Script):
        def review(self, draft: Draft) -> QaReview:
            return QaReview(
                QaReport(), 8, 2, 1, question_drafts=(question,), blocking_questions=(question,)
            )

    script = Asking([])
    assert run(team, script) is None
    run_record = team.finish(TeamRunStatus.ESCALATED)
    assert run_record.status is TeamRunStatus.WAITING_FOR_INPUT
    assert script.writes == [(None, [])]
    assert (team.run_dir / "checkpoint.json").is_file()
    assert [draft.text for draft in team.collected_questions()] == [question.text]


def test_a_draft_that_fails_the_gate_offers_no_questions(team: Team) -> None:
    script = Script([QaReport()], gates=[["bad quote"], []])
    run_writer_review(
        team,
        write=script.write,
        gate=script.gate,
        review=script.review,
        writer_questions=lambda d: [QuestionDraft(refs=[], text=f"About {d.text}?")],
    )
    assert [q.text for q in team.collected_questions()] == ["About draft 2?"]


def test_the_blocking_issues_of_the_last_review_are_held_as_objections(team: Team) -> None:
    assert run(team, Script([block("A"), block("A"), block("A")])) is None
    assert [i.message for i in team.objections["writer"]] == ["A"]


def test_a_failed_writer_request_escalates_instead_of_raising(team: Team) -> None:
    class Down(Script):
        def write(self, previous: Draft | None, feedback: Sequence[str]) -> LLMResult[Draft]:
            raise LLMError("model request failed: APIConnectionError: Connection error.")

    assert run(team, Down([])) is None
    assert team.escalations[0].startswith("model request failed in writer: ")
    team.finish(TeamRunStatus.ESCALATED)


def test_a_failed_qa_request_escalates_instead_of_raising(team: Team) -> None:
    class QaDown(Script):
        def review(self, draft: Draft) -> QaReview:
            raise LLMError("model request failed: InternalServerError: 502")

    assert run(team, QaDown([])) is None
    assert team.escalations[0].startswith("model request failed in qa: ")
