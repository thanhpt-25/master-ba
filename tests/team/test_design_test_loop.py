from collections.abc import Sequence

import pytest
from pydantic import BaseModel, Field

from masterba.agents import QaIssue, QaOutputInvalidError, QaReport, QaReview
from masterba.llm import LLMResult
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team import (
    MAX_EXCHANGES,
    Answer,
    DesignTestHooks,
    DesignTestResult,
    MessageType,
    Question,
    TaskStatus,
    Team,
    run_design_test_team,
)
from masterba.trace_store import ProjectStore

D_REF = "DOC-BASIC_DESIGN-0001#item.2"
D_REF3 = "DOC-BASIC_DESIGN-0001#item.3"
D_REF4 = "DOC-BASIC_DESIGN-0001#item.4"
T_REF = "DOC-TEST_IT-0001#item.1"


class Design(BaseModel):
    version: int
    answers: list[Answer] = Field(default_factory=list)


class Tests(BaseModel):
    __test__ = False

    version: int
    questions: list[Question] = Field(default_factory=list)


def issue(ref: str | None, message: str = "Fix.") -> QaIssue:
    return QaIssue(
        checklist_id="X-1", severity="blocking", ref=ref, message=message, action_required=message
    )


def report(*issues: QaIssue) -> QaReport:
    return QaReport(issues=list(issues))


class Script:
    """Scripted agents; question_plan[i] = questions of the i-th test draft."""

    def __init__(
        self,
        question_plan: list[list[Question]] | None = None,
        design_reports: list[QaReport | QaOutputInvalidError] | None = None,
        test_reports: list[QaReport] | None = None,
        design_gates: list[list[str]] | None = None,
        test_gates: list[list[str]] | None = None,
        writer_tokens: tuple[int, int] = (20, 10),
    ) -> None:
        self.question_plan = question_plan or []
        self.design_reports = design_reports or []
        self.test_reports = test_reports or []
        self.design_gates = design_gates or []
        self.test_gates = test_gates or []
        self.writer_tokens = writer_tokens
        self.design_calls: list[Sequence[str]] = []
        self.test_calls: list[Sequence[str]] = []
        self.design_reviews = 0
        self.test_reviews = 0

    def answers_for(self, feedback: Sequence[str]) -> list[str]:
        """Refs of the questions found in the feedback (one answer per question)."""
        return [f.split()[1].rstrip(":") for f in feedback if f.startswith("question ")]

    def write_design(self, previous: Design | None, feedback: Sequence[str]) -> LLMResult[Design]:
        self.design_calls.append(list(feedback))
        version = len(self.design_calls)
        answers = [Answer(a, "answered") for a in self.answers_for(feedback)]
        return LLMResult(Design(version=version, answers=answers), *self.writer_tokens)

    def write_tests(
        self, design: Design, previous: Tests | None, feedback: Sequence[str]
    ) -> LLMResult[Tests]:
        self.test_calls.append(list(feedback))
        index = len(self.test_calls) - 1
        questions = self.question_plan[index] if index < len(self.question_plan) else []
        return LLMResult(Tests(version=index + 1, questions=questions), *self.writer_tokens)

    def gate_design(self, design: Design) -> list[str]:
        return self.design_gates.pop(0) if self.design_gates else []

    def gate_tests(self, design: Design, tests: Tests) -> list[str]:
        return self.test_gates.pop(0) if self.test_gates else []

    def review_design(self, design: Design) -> QaReview:
        item = (
            self.design_reports[self.design_reviews]
            if self.design_reviews < len(self.design_reports)
            else QaReport()
        )
        self.design_reviews += 1
        if isinstance(item, QaOutputInvalidError):
            raise item
        return QaReview(item, 8, 2, 1)

    def review_tests(self, design: Design, tests: Tests) -> QaReview:
        item = (
            self.test_reports[self.test_reviews]
            if self.test_reviews < len(self.test_reports)
            else QaReport()
        )
        self.test_reviews += 1
        return QaReview(item, 8, 2, 1)

    def hooks(self) -> DesignTestHooks[Design, Tests]:
        return DesignTestHooks(
            write_design=self.write_design,
            write_tests=self.write_tests,
            gate_design=self.gate_design,
            gate_tests=self.gate_tests,
            questions=lambda t: t.questions,
            answers=lambda d: d.answers,
            review_design=self.review_design,
            review_tests=self.review_tests,
        )


def ask(text: str = "What is the limit?", ref: str = D_REF) -> list[Question]:
    return [Question(ref, text)]


@pytest.fixture
def team(store: ProjectStore) -> Team:
    return Team.open(store, DocType.BASIC_DESIGN, max_rounds=3, token_budget=None)


def run(team: Team, script: Script) -> DesignTestResult[Design, Tests] | None:
    return run_design_test_team(team, script.hooks())


def test_everything_accepted_in_the_first_cycle(team: Team) -> None:
    script = Script()
    result = run(team, script)
    assert result is not None
    assert (result.design.version, result.tests.version) == (1, 1)
    assert (team.rounds, team.exchanges, team.issues_raised) == (1, 0, 0)
    assert [(t.title, t.owner, t.status) for t in team.tasks] == [
        ("Draft design", "designer", TaskStatus.DONE),
        ("Write tests", "tester", TaskStatus.DONE),
        ("Review design (round 1)", "qa", TaskStatus.DONE),
        ("Review tests (round 1)", "qa", TaskStatus.DONE),
    ]
    assert team.messages == []


def test_a_tester_question_is_answered_inside_the_same_cycle(team: Team) -> None:
    script = Script(question_plan=[ask()])
    result = run(team, script)
    assert result is not None
    assert (team.rounds, team.exchanges) == (1, 1)
    assert script.design_calls[1] == [f"question {D_REF}: What is the limit?"]
    assert script.test_calls[1][0] == "the design was revised; re-check every case against it"
    assert script.test_calls[1][1] == f"answer to {D_REF}: answered"
    assert [(m.sender, m.to, m.type, m.ref) for m in team.messages] == [
        ("tester", "designer", MessageType.QUESTION, D_REF),
        ("designer", "tester", MessageType.ANSWER, D_REF),
    ]
    assert [t.title for t in team.tasks][:4] == [
        "Draft design",
        "Write tests",
        "Revise design (round 1)",
        "Revise tests (round 1)",
    ]


def test_after_two_exchanges_further_questions_carry_over_to_the_next_round(team: Team) -> None:
    script = Script(question_plan=[ask("q1"), ask("q2", D_REF3), ask("q3", D_REF4)])
    result = run(team, script)
    assert result is not None
    assert MAX_EXCHANGES == 2
    assert (team.rounds, team.exchanges) == (2, 2)
    assert len(script.design_calls) == 4
    assert script.design_calls[3] == [f"question {D_REF4}: q3"]
    assert len(script.test_calls) == 4


def test_unanswered_questions_at_the_round_limit_are_listed_in_the_escalation(
    store: ProjectStore,
) -> None:
    team = Team.open(store, DocType.BASIC_DESIGN, max_rounds=1, token_budget=None)
    script = Script(question_plan=[ask("q1"), ask("q2", D_REF3), ask("q3", D_REF4)])
    assert run(team, script) is None
    assert team.escalations == ["max rounds reached (1)", f"question {D_REF4}: q3"]
    assert team.exchanges == 2


def test_blocking_design_issue_goes_to_the_designer_and_test_issue_to_the_tester(
    team: Team,
) -> None:
    script = Script(
        design_reports=[report(issue("DOC-BASIC_DESIGN-0001#item.1", "Too vague.")), QaReport()],
        test_reports=[report(issue(T_REF, "No boundary case.")), QaReport()],
    )
    result = run(team, script)
    assert result is not None
    assert (team.rounds, team.issues_raised, team.issues_resolved) == (2, 2, 2)
    assert script.design_calls[1] == ["[X-1] DOC-BASIC_DESIGN-0001#item.1: Too vague."]
    revised_tests = script.test_calls[1]
    assert f"[X-1] {T_REF}: No boundary case." in revised_tests
    assert "the design was revised; re-check every case against it" in revised_tests
    assert [(m.sender, m.to, m.type.value, m.ref) for m in team.messages] == [
        ("qa", "designer", "feedback", "DOC-BASIC_DESIGN-0001#item.1"),
        ("qa", "tester", "feedback", T_REF),
    ]


def test_a_test_only_issue_makes_only_the_tester_revise(team: Team) -> None:
    script = Script(test_reports=[report(issue(T_REF)), QaReport()])
    assert run(team, script) is not None
    assert len(script.design_calls) == 1
    assert len(script.test_calls) == 2
    assert script.test_calls[1] == [f"[X-1] {T_REF}: Fix."]


def test_design_gate_errors_end_the_cycle_without_tests_or_review(team: Team) -> None:
    script = Script(design_gates=[["SRS item uncovered"], []])
    assert run(team, script) is not None
    assert (team.rounds, len(script.design_calls), len(script.test_calls)) == (2, 2, 1)
    assert script.design_calls[1] == ["SRS item uncovered"]
    assert (team.messages[0].sender, team.messages[0].to) == ("gate", "designer")


def test_test_gate_errors_end_the_cycle_without_a_review(team: Team) -> None:
    script = Script(test_gates=[["design item untested"], []])
    assert run(team, script) is not None
    assert (team.rounds, len(script.design_calls), len(script.test_calls)) == (2, 1, 2)
    assert script.test_calls[1] == ["design item untested"]
    assert script.design_reviews == 1
    assert (team.messages[0].sender, team.messages[0].to) == ("gate", "tester")


def test_exhausting_the_rounds_escalates_with_the_open_issues(team: Team) -> None:
    script = Script(test_reports=[report(issue(T_REF, "Still wrong."))] * 3)
    assert run(team, script) is None
    assert team.rounds == 3
    assert team.escalations[0] == "max rounds reached (3)"
    assert f"[X-1] {T_REF}: Still wrong." in team.escalations
    assert (team.issues_raised, team.issues_resolved) == (3, 2)
    summary = team.finish(TeamRunStatus.ESCALATED)
    assert summary.rounds == 3


def test_the_budget_is_checked_before_every_call(store: ProjectStore) -> None:
    team = Team.open(store, DocType.BASIC_DESIGN, max_rounds=5, token_budget=45)
    script = Script(writer_tokens=(20, 10))
    assert run(team, script) is None
    assert len(script.design_calls) == 1
    assert len(script.test_calls) == 1
    assert team.escalations == ["token budget exhausted (60/45)"]


def test_an_unusable_qa_report_escalates_and_counts_its_tokens(team: Team) -> None:
    script = Script(design_reports=[QaOutputInvalidError(["unknown checklist_id"], 7, 3)])
    assert run(team, script) is None
    assert team.escalations == ["qa output invalid: unknown checklist_id"]
    assert team.tokens_used == 60 + 10


def test_advisory_issues_do_not_block(team: Team) -> None:
    advisory = QaIssue(checklist_id="X-2", severity="advisory", ref=None, message="Wording.")
    script = Script(test_reports=[report(advisory)])
    assert run(team, script) is not None
    assert team.advisory == ["[X-2] document: Wording."]
    assert team.issues_raised == 0


def test_owners_are_the_design_and_test_roles(team: Team) -> None:
    run(team, Script())
    names = sorted(p.name for p in team.transcripts_dir.iterdir())
    assert any(n.endswith("design-draft.txt") for n in names)
    assert any(n.endswith("test-draft.txt") for n in names)
    assert sum(n.endswith("qa-report.txt") for n in names) == 2


def test_asking_again_about_an_answered_item_stops_blocking_and_is_reported(team: Team) -> None:
    script = Script(question_plan=[ask("first"), ask("still open")])
    result = run(team, script)
    assert result is not None
    assert (team.rounds, team.exchanges) == (1, 1)
    assert result.unresolved == (f"{D_REF}: still open",)
    assert len(script.design_calls) == 2
    assert len(script.test_calls) == 2
    assert [(m.sender, m.to, m.type.value) for m in team.messages] == [
        ("tester", "designer", "question"),
        ("designer", "tester", "answer"),
        ("tester", "customer", "question"),
    ]


def test_a_clean_run_has_no_unresolved_questions(team: Team) -> None:
    result = run(team, Script())
    assert result is not None
    assert result.unresolved == ()
