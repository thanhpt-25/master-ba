"""The writer-reviewer loop (spec 04 section 3), shared by the BRD and SRS stages."""

from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from masterba.agents.qa_reviewer import QaIssue, QaOutputInvalidError, QaReview
from masterba.llm import LLMOutputError, LLMResult
from masterba.team.models import MessageType, TaskStatus
from masterba.team.workspace import Team

D = TypeVar("D", bound=BaseModel)


def format_issue(issue: QaIssue) -> str:
    return f"[{issue.checklist_id}] {issue.ref or 'document'}: {issue.message}"


def unusable_answer(error: LLMOutputError) -> str:
    """Feedback for a model answer that does not fit its schema (spec 11 section 1.6)."""
    return f"the last answer could not be used: {' '.join(str(error).split())[:600]}"


def run_writer_review(
    team: Team,
    *,
    write: Callable[[D | None, Sequence[str]], LLMResult[D]],
    gate: Callable[[D], list[str]],
    review: Callable[[D], QaReview],
    start: D | None = None,
    start_feedback: Sequence[str] = (),
) -> D | None:
    """Return the accepted draft, or None after escalating (reasons are in `team.escalations`).

    `start` and `start_feedback` come from a checkpoint when a run resumes (spec 11 section 3).
    """
    draft: D | None = start
    feedback: list[str] = list(start_feedback)
    previous_task: str | None = None
    open_blocking = 0

    def stop(reasons: list[str]) -> None:
        team.issues_resolved = max(team.issues_raised - open_blocking, 0)
        team.escalate([*reasons, *feedback])

    while True:
        if team.rounds >= team.max_rounds:
            stop([f"max rounds reached ({team.max_rounds})"])
            return None
        if team.budget_exhausted():
            stop([f"token budget exhausted ({team.tokens_used}/{team.token_budget})"])
            return None
        team.begin_round()
        title = "Draft" if team.rounds == 1 else f"Revise (round {team.rounds})"
        draft_task = team.add_task(title, "writer", (previous_task,) if previous_task else ())
        team.set_status(draft_task, TaskStatus.IN_PROGRESS)
        try:
            written = write(draft, feedback)
        except LLMOutputError as exc:
            message = unusable_answer(exc)
            team.post("gate", "writer", MessageType.FEEDBACK, None, message)
            feedback = feedback if message in feedback else [*feedback, message]
            team.set_status(draft_task, TaskStatus.DONE)
            previous_task = draft_task
            continue
        team.charge(written.input_tokens + written.output_tokens)
        draft = written.value
        team.write("writer", "draft", draft)
        team.set_status(draft_task, TaskStatus.DONE)
        previous_task = draft_task

        errors = gate(draft)
        if errors:
            for error in errors:
                team.post("gate", "writer", MessageType.FEEDBACK, None, error)
            feedback = errors
            continue
        team.save_checkpoint({"draft": draft}, {"writer": []})

        if team.budget_exhausted():
            feedback = []
            stop([f"token budget exhausted ({team.tokens_used}/{team.token_budget})"])
            return None
        review_task = team.add_task(f"Review (round {team.rounds})", "qa", (draft_task,))
        team.set_status(review_task, TaskStatus.IN_PROGRESS)
        try:
            outcome = review(draft)
        except QaOutputInvalidError as exc:
            team.charge(exc.input_tokens + exc.output_tokens)
            feedback = []
            stop([f"qa output invalid: {'; '.join(exc.errors)}"])
            return None
        team.charge(outcome.input_tokens + outcome.output_tokens)
        team.write("qa", "qa-report", outcome.report)
        team.set_status(review_task, TaskStatus.DONE)
        previous_task = review_task

        issues, limited = team.settle("draft", outcome.report.issues)
        blocking = [i for i in issues if i.severity == "blocking"]
        for issue in issues:
            team.post("qa", "writer", MessageType.FEEDBACK, issue.ref, format_issue(issue))
            if issue.severity == "advisory":
                team.advisory.append(format_issue(issue))
        team.note_review("writer", [*outcome.notes, *limited], outcome.customer_questions)
        team.issues_raised += len(blocking)
        open_blocking = len(blocking)
        if not blocking:
            team.issues_resolved = team.issues_raised
            return draft
        feedback = [format_issue(i) for i in blocking]
        team.save_checkpoint({"draft": draft}, {"writer": feedback})
