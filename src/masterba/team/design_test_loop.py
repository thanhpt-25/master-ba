"""The designer-tester-QA loop (spec 05 section 3).

One *cycle* (= one round) lets the designer and tester do what is pending, runs the gates and then
asks QA. Inside a cycle the tester may question the designer, at most `MAX_EXCHANGES` times.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel

from masterba.agents.qa_reviewer import QaIssue, QaOutputInvalidError, QaReview
from masterba.llm import LLMOutputError, LLMResult
from masterba.models import QuestionDraft
from masterba.team.loop import format_issue, unusable_answer
from masterba.team.models import MessageType, TaskStatus
from masterba.team.workspace import Team

D = TypeVar("D", bound=BaseModel)
T = TypeVar("T", bound=BaseModel)
MAX_EXCHANGES = 2


@dataclass(frozen=True)
class Question:
    ref: str
    text: str


@dataclass(frozen=True)
class Answer:
    ref: str
    text: str


@dataclass(frozen=True)
class DesignTestHooks(Generic[D, T]):
    """What the loop needs from the agents; keeps the loop independent of their models."""

    write_design: Callable[[D | None, Sequence[str]], LLMResult[D]]
    write_tests: Callable[[D, T | None, Sequence[str]], LLMResult[T]]
    gate_design: Callable[[D], list[str]]
    gate_tests: Callable[[D, T], list[str]]
    questions: Callable[[T], list[Question]]
    answers: Callable[[D], list[Answer]]
    review_design: Callable[[D], QaReview]
    review_tests: Callable[[D, T], QaReview]


@dataclass(frozen=True)
class DesignTestStart(Generic[D, T]):
    """Where a resumed run picks up (spec 11 section 3): drafts and feedback from a checkpoint."""

    design: D | None
    tests: T | None
    to_designer: tuple[str, ...] = ()
    to_tester: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True)
class DesignTestResult(Generic[D, T]):
    design: D
    tests: T
    unresolved: tuple[str, ...] = ()


class _Next(Enum):
    ESCALATED = "escalated"
    END_CYCLE = "end_cycle"
    READY = "ready"


class _Loop(Generic[D, T]):
    def __init__(
        self, team: Team, hooks: DesignTestHooks[D, T], start: DesignTestStart[D, T] | None
    ) -> None:
        self.team = team
        self.hooks = hooks
        self.design: D | None = start.design if start else None
        self.tests: T | None = start.tests if start else None
        self.to_designer: list[str] = list(start.to_designer) if start else []
        self.to_tester: list[str] = list(start.to_tester) if start else []
        self.open_blocking = 0
        self.answered: set[str] = set()
        self.unresolved: list[str] = list(start.unresolved) if start else []
        self.last_task: str | None = None

    def _checkpoint(self) -> None:
        self.team.save_checkpoint(
            {"design": self.design, "tests": self.tests},
            {
                "designer": self.to_designer,
                "tester": self.to_tester,
                "unresolved": self.unresolved,
            },
        )

    # -- helpers -------------------------------------------------------------------------------
    def _stop(self, reasons: list[str]) -> _Next:
        team = self.team
        team.issues_resolved = max(team.issues_raised - self.open_blocking, 0)
        team.escalate([*reasons, *self.to_designer, *self.to_tester])
        return _Next.ESCALATED

    def _out_of_budget(self) -> bool:
        team = self.team
        if not team.budget_exhausted():
            return False
        self._stop([f"token budget exhausted ({team.tokens_used}/{team.token_budget})"])
        return True

    def _task(self, title: str, owner: str) -> str:
        deps = (self.last_task,) if self.last_task else ()
        task = self.team.add_task(title, owner, deps)
        self.team.set_status(task, TaskStatus.IN_PROGRESS)
        return task

    def _done(self, task: str) -> None:
        self.team.set_status(task, TaskStatus.DONE)
        self.last_task = task

    def _gate_failed(self, errors: list[str], to: str) -> None:
        for error in errors:
            self.team.post("gate", to, MessageType.FEEDBACK, None, error)

    # -- steps ---------------------------------------------------------------------------------
    def _designer(self) -> _Next | None:
        team = self.team
        if self._out_of_budget():
            return _Next.ESCALATED
        first = self.design is None
        title = "Draft design" if first else f"Revise design (round {team.rounds})"
        task = self._task(title, "designer")
        try:
            written = self.hooks.write_design(self.design, list(self.to_designer))
        except LLMOutputError as exc:
            self._done(task)
            message = unusable_answer(exc)
            self._gate_failed([message], "designer")
            if message not in self.to_designer:
                self.to_designer = [*self.to_designer, message]
            return _Next.END_CYCLE
        team.charge(written.input_tokens + written.output_tokens)
        self.design = written.value
        team.write("designer", "design-draft", self.design)
        self._done(task)
        answers = self.hooks.answers(self.design)
        self.answered.update(a.ref for a in answers)
        for answer in answers:
            team.post("designer", "tester", MessageType.ANSWER, answer.ref, answer.text)
        errors = self.hooks.gate_design(self.design)
        if errors:
            self._gate_failed(errors, "designer")
            self.to_designer = errors
            return _Next.END_CYCLE
        self.to_designer = []
        if self.tests is not None:
            self.to_tester = [
                *self.to_tester,
                "the design was revised; re-check every case against it",
                *[f"answer to {a.ref}: {a.text}" for a in answers],
            ]
        return None

    def _tester(self) -> _Next | None:
        team = self.team
        assert self.design is not None
        if self._out_of_budget():
            return _Next.ESCALATED
        title = "Write tests" if self.tests is None else f"Revise tests (round {team.rounds})"
        task = self._task(title, "tester")
        try:
            written = self.hooks.write_tests(self.design, self.tests, list(self.to_tester))
        except LLMOutputError as exc:
            self._done(task)
            message = unusable_answer(exc)
            self._gate_failed([message], "tester")
            if message not in self.to_tester:
                self.to_tester = [*self.to_tester, message]
            return _Next.END_CYCLE
        team.charge(written.input_tokens + written.output_tokens)
        self.tests = written.value
        team.write("tester", "test-draft", self.tests)
        self._done(task)
        errors = self.hooks.gate_tests(self.design, self.tests)
        if errors:
            self._gate_failed(errors, "tester")
            self.to_tester = errors
            return _Next.END_CYCLE
        self.to_tester = []
        return None

    def _cycle_until_ready(self) -> _Next:
        """Designer and tester work until both gates pass and no question is open."""
        exchanges = 0
        while True:
            if self.design is None or self.to_designer:
                outcome = self._designer()
                if outcome is not None:
                    return outcome
            if self.tests is None or self.to_tester:
                outcome = self._tester()
                if outcome is not None:
                    return outcome
            assert self.tests is not None
            asked = self.hooks.questions(self.tests)
            # A question about an item the designer already answered cannot be settled inside
            # the team (the information is missing): it stops blocking and is reported.
            questions = [q for q in asked if q.ref not in self.answered]
            stale = [q for q in asked if q.ref in self.answered]
            for question in stale:
                text = f"{question.ref}: {question.text}"
                if text not in self.unresolved:
                    self.team.post(
                        "tester", "customer", MessageType.QUESTION, question.ref, question.text
                    )
            self.unresolved = [f"{q.ref}: {q.text}" for q in stale]
            self.team.offer_questions(
                "tester", [QuestionDraft(refs=[q.ref], text=q.text) for q in stale], replace=True
            )
            if not questions:
                return _Next.READY
            for question in questions:
                self.team.post(
                    "tester", "designer", MessageType.QUESTION, question.ref, question.text
                )
            self.to_designer = [f"question {q.ref}: {q.text}" for q in questions]
            if exchanges >= MAX_EXCHANGES:
                return _Next.END_CYCLE
            exchanges += 1
            self.team.exchanges += 1

    def _review_one(
        self, owner: str, title: str, call: Callable[[], QaReview]
    ) -> list[QaIssue] | None:
        """One QA review; return its blocking issues, or None when the team escalated."""
        team = self.team
        if self._out_of_budget():
            return None
        task = self._task(f"{title} (round {team.rounds})", "qa")
        try:
            outcome = call()
        except QaOutputInvalidError as exc:
            team.charge(exc.input_tokens + exc.output_tokens)
            self.to_designer = []
            self.to_tester = []
            self._stop([f"qa output invalid: {'; '.join(exc.errors)}"])
            return None
        team.charge(outcome.input_tokens + outcome.output_tokens)
        team.write("qa", "qa-report", outcome.report)
        self._done(task)
        blocking: list[QaIssue] = []
        issues, limited = team.settle(owner, outcome.report.issues)
        for issue in issues:
            team.post("qa", owner, MessageType.FEEDBACK, issue.ref, format_issue(issue))
            if issue.severity == "advisory":
                team.advisory.append(format_issue(issue))
            else:
                blocking.append(issue)
        team.note_review(owner, [*outcome.notes, *limited], outcome.customer_questions)
        team.offer_questions("qa", outcome.question_drafts)
        team.hold_objection(owner, blocking)
        return blocking

    def _review(self) -> _Next | None:
        """QA reviews design then tests; None means both passed."""
        team = self.team
        assert self.design is not None and self.tests is not None
        design, tests = self.design, self.tests
        in_design = self._review_one(
            "designer", "Review design", lambda: self.hooks.review_design(design)
        )
        if in_design is None:
            return _Next.ESCALATED
        in_tests = self._review_one(
            "tester", "Review tests", lambda: self.hooks.review_tests(design, tests)
        )
        if in_tests is None:
            return _Next.ESCALATED
        found = len(in_design) + len(in_tests)
        team.issues_raised += found
        self.open_blocking = found
        if not found:
            team.issues_resolved = team.issues_raised
            return None
        self.to_designer = [format_issue(i) for i in in_design]
        self.to_tester = [format_issue(i) for i in in_tests]
        self._checkpoint()
        return _Next.END_CYCLE

    def run(self) -> DesignTestResult[D, T] | None:
        team = self.team
        while True:
            if team.rounds >= team.max_rounds:
                self._stop([f"max rounds reached ({team.max_rounds})"])
                return None
            if self._out_of_budget():
                return None
            team.begin_round()
            cycle = self._cycle_until_ready()
            if cycle is _Next.ESCALATED:
                return None
            if cycle is _Next.END_CYCLE:
                continue
            self._checkpoint()
            verdict = self._review()
            if verdict is _Next.ESCALATED:
                return None
            if verdict is None:
                assert self.design is not None and self.tests is not None
                return DesignTestResult(self.design, self.tests, tuple(self.unresolved))


def run_design_test_team(
    team: Team, hooks: DesignTestHooks[D, T], start: DesignTestStart[D, T] | None = None
) -> DesignTestResult[D, T] | None:
    """Return the accepted design and tests, or None after escalating."""
    return _Loop(team, hooks, start).run()
