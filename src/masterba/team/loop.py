"""The writer-reviewer loop (spec 04 section 3), shared by the BRD and SRS stages."""

from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from masterba.agents.qa_reviewer import QaIssue, QaOutputInvalidError, QaReview
from masterba.llm import LLMResult
from masterba.team.models import MessageType, TaskStatus
from masterba.team.workspace import Team

D = TypeVar("D", bound=BaseModel)


def format_issue(issue: QaIssue) -> str:
    return f"[{issue.checklist_id}] {issue.ref or 'document'}: {issue.message}"


def run_writer_review(
    team: Team,
    *,
    write: Callable[[D | None, Sequence[str]], LLMResult[D]],
    gate: Callable[[D], list[str]],
    review: Callable[[D], QaReview],
) -> D | None:
    """Return the accepted draft, or None after escalating (reasons are in `team.escalations`)."""
    draft: D | None = None
    feedback: list[str] = []
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
        written = write(draft, feedback)
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

        blocking = [i for i in outcome.report.issues if i.severity == "blocking"]
        for issue in outcome.report.issues:
            team.post("qa", "writer", MessageType.FEEDBACK, issue.ref, format_issue(issue))
            if issue.severity == "advisory":
                team.advisory.append(format_issue(issue))
        team.issues_raised += len(blocking)
        open_blocking = len(blocking)
        if not blocking:
            team.issues_resolved = team.issues_raised
            return draft
        feedback = [format_issue(i) for i in blocking]
