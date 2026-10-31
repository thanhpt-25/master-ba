"""Run workspace of a Phase Team: tasks, mailbox, budget and the run record.

Files live in ``projects/<project_id>/runs/RUN-####/`` (spec 04 section 2). Summary, tasks and
mailbox are committed once at the end; ``transcripts/`` stays local.
"""

import json
import re
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from masterba.agents.qa_reviewer import QaIssue
from masterba.llm import LLM, LLMResult
from masterba.llm.base import T
from masterba.models import TeamRun
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team.models import (
    MessageType,
    RunCheckpoint,
    TaskStatus,
    TeamMessage,
    TeamTask,
)
from masterba.trace_store import ProjectStore
from masterba.trace_store.git import commit_paths

# A job runner (the dashboard) sets this to receive one-line progress messages.
PROGRESS: ContextVar[Callable[[str], None] | None] = ContextVar("masterba_progress", default=None)
ARTIFACT_OWNERS = {
    "draft": "writer",
    "design-draft": "designer",
    "test-draft": "tester",
    "qa-report": "qa",
}
_RUN_DIR = re.compile(r"^RUN-(\d{4})$")
_OPEN = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
CHECKPOINT = "checkpoint.json"
_RUN_GITIGNORE = f"transcripts/\n{CHECKPOINT}\n"


class SingleWriterError(Exception):
    """A role tried to write an artifact it does not own."""


class ResumeError(Exception):
    """A run cannot be resumed (spec 11 section 3.2)."""


def _dump(path: Path, data: Any) -> None:
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Team:
    store: ProjectStore
    run_id: str
    stage: DocType
    max_rounds: int
    token_budget: int | None
    rounds: int = 0
    tokens_used: int = 0
    issues_raised: int = 0
    issues_resolved: int = 0
    escalations: list[str] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    customer_questions: list[str] = field(default_factory=list)
    tasks: list[TeamTask] = field(default_factory=list)
    messages: list[TeamMessage] = field(default_factory=list)
    log_count: int = 0
    exchanges: int = 0
    trigger: str = "initial"
    upstream: dict[str, int] = field(default_factory=dict)
    resumed: int = 0
    carried_tasks: int = 0
    blocking_seen: dict[str, set[tuple[str, str | None]]] = field(default_factory=dict)

    @classmethod
    def open(
        cls,
        store: ProjectStore,
        stage: DocType,
        max_rounds: int,
        token_budget: int | None,
        trigger: str = "initial",
    ) -> "Team":
        runs = store.path / "runs"
        used = [int(m[1]) for p in runs.glob("RUN-*") if (m := _RUN_DIR.match(p.name))]
        run_id = f"RUN-{max(used, default=0) + 1:04d}"
        team = cls(store, run_id, stage, max_rounds, token_budget, trigger=trigger)
        team.transcripts_dir.mkdir(parents=True)
        (team.run_dir / ".gitignore").write_text(_RUN_GITIGNORE, encoding="utf-8")
        return team

    @classmethod
    def reopen(
        cls,
        store: ProjectStore,
        stage: DocType,
        run_id: str,
        more_rounds: int,
        token_budget: int | None,
    ) -> tuple["Team", RunCheckpoint]:
        """Reopen an escalated run from its checkpoint (spec 11 section 3.2)."""
        run_dir = store.path / "runs" / run_id
        if not _RUN_DIR.match(run_id) or not (run_dir / "team-summary.json").is_file():
            raise ResumeError(f"run {run_id} does not exist")
        summary = TeamRun.model_validate(_load(run_dir / "team-summary.json"))
        if summary.stage is not stage:
            raise ResumeError(f"run {run_id} belongs to the {summary.stage.value} stage")
        if summary.status is not TeamRunStatus.ESCALATED:
            raise ResumeError(
                f"run {run_id} ended {summary.status.value}; only escalated runs resume"
            )
        if not (run_dir / CHECKPOINT).is_file():
            raise ResumeError(f"run {run_id} has no checkpoint")
        checkpoint = RunCheckpoint.model_validate(_load(run_dir / CHECKPOINT))
        tasks = [TeamTask.model_validate(t) for t in _load(run_dir / "team-tasks.json")]
        messages = [TeamMessage.model_validate(m) for m in _load(run_dir / "mailbox.json")]
        team = cls(
            store,
            run_id,
            stage,
            summary.rounds + more_rounds,
            token_budget,
            rounds=summary.rounds,
            tokens_used=checkpoint.tokens_used,
            issues_raised=checkpoint.issues_raised,
            issues_resolved=checkpoint.issues_resolved,
            customer_questions=list(checkpoint.customer_questions),
            tasks=tasks,
            messages=messages,
            trigger=summary.trigger,
            upstream=dict(checkpoint.upstream),
            resumed=summary.resumed + 1,
            carried_tasks=len(tasks),
            blocking_seen={a: set(pairs) for a, pairs in checkpoint.blocking_seen.items()},
        )
        team.transcripts_dir.mkdir(parents=True, exist_ok=True)
        team.log_count = len(list(team.transcripts_dir.iterdir()))
        (run_dir / ".gitignore").write_text(_RUN_GITIGNORE, encoding="utf-8")
        return team, checkpoint

    @property
    def run_dir(self) -> Path:
        return self.store.path / "runs" / self.run_id

    @property
    def transcripts_dir(self) -> Path:
        return self.run_dir / "transcripts"

    def emit(self, message: str) -> None:
        listener = PROGRESS.get()
        if listener is not None:
            listener(message)

    def begin_round(self) -> int:
        self.rounds += 1
        self.emit(f"{self.run_id} {self.stage.value}: round {self.rounds} started")
        return self.rounds

    def add_task(self, title: str, owner: str, depends_on: tuple[str, ...] = ()) -> str:
        task = TeamTask(
            id=f"T-{len(self.tasks) + 1:02d}",
            title=title,
            owner=owner,
            status=TaskStatus.TODO,
            depends_on=list(depends_on),
        )
        self.tasks = [*self.tasks, task]
        return task.id

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        self.tasks = [
            t.model_copy(update={"status": status}) if t.id == task_id else t for t in self.tasks
        ]

    def post(
        self, sender: str, to: str, kind: MessageType, ref: str | None, body: str
    ) -> TeamMessage:
        message = TeamMessage(
            sender=sender, to=to, type=kind, ref=ref, round=max(self.rounds, 1), body=body
        )
        self.messages = [*self.messages, message]
        return message

    def write(self, role: str, artifact: str, value: BaseModel) -> None:
        """Record an artifact; only its owner may (single-writer rule)."""
        owner = ARTIFACT_OWNERS.get(artifact)
        if owner is None or owner != role:
            raise SingleWriterError(f"{role!r} may not write {artifact!r} (owner: {owner!r})")
        self.log(artifact, value.model_dump_json(indent=2))

    def log(self, name: str, text: str) -> None:
        self.log_count += 1
        path = self.transcripts_dir / f"{self.log_count:03d}-round-{self.rounds}-{name}.txt"
        path.write_text(text + "\n", encoding="utf-8")

    def charge(self, tokens: int) -> None:
        self.tokens_used += tokens

    def budget_exhausted(self) -> bool:
        return self.token_budget is not None and self.tokens_used >= self.token_budget

    def escalate(self, reasons: list[str]) -> None:
        self.escalations = [*self.escalations, *reasons]

    def save_checkpoint(
        self, drafts: dict[str, BaseModel | None], feedback: dict[str, Sequence[str]]
    ) -> None:
        """Keep the last validated drafts on disk (gitignored), so the run can resume."""
        checkpoint = RunCheckpoint(
            stage=self.stage,
            round=max(self.rounds, 1),
            upstream=self.upstream,
            drafts={k: v.model_dump(mode="json") if v else None for k, v in drafts.items()},
            feedback={k: list(v) for k, v in feedback.items()},
            customer_questions=list(self.customer_questions),
            tokens_used=self.tokens_used,
            issues_raised=self.issues_raised,
            issues_resolved=self.issues_resolved,
            blocking_seen={
                artifact: sorted(pairs, key=lambda p: (p[0], p[1] or ""))
                for artifact, pairs in self.blocking_seen.items()
            },
        )
        _dump(self.run_dir / CHECKPOINT, checkpoint.model_dump(mode="json"))

    def settle(self, artifact: str, issues: Sequence[QaIssue]) -> tuple[list[QaIssue], list[str]]:
        """Only the first review of an artifact may raise new blocking issues (spec 11 1.5).

        Later reviews keep an issue blocking only when the same (checklist id, ref) was blocking
        before; every other blocking issue becomes advisory, with a note for the mailbox.
        """
        first = artifact not in self.blocking_seen
        seen = self.blocking_seen.setdefault(artifact, set())
        settled: list[QaIssue] = []
        notes: list[str] = []
        for issue in issues:
            key = (issue.checklist_id, issue.ref)
            if issue.severity == "blocking" and not first and key not in seen:
                settled.append(issue.model_copy(update={"severity": "advisory"}))
                where = issue.ref or "document"
                notes.append(
                    f"[{issue.checklist_id}] {where}: downgraded (new after the first review)"
                )
                continue
            if issue.severity == "blocking":
                seen.add(key)
            settled.append(issue)
        return settled, notes

    def note_review(self, to: str, notes: Sequence[str], questions: Sequence[str]) -> None:
        """Record what QA normalisation changed (spec 11 section 1)."""
        for note in notes:
            self.post("qa", to, MessageType.FEEDBACK, None, note)
        for question in questions:
            if question not in self.customer_questions:
                self.customer_questions.append(question)

    def finish(self, status: TeamRunStatus) -> TeamRun:
        """Write summary, tasks and mailbox and commit them as one commit."""
        if status is TeamRunStatus.ESCALATED:
            self.tasks = [
                t.model_copy(update={"status": TaskStatus.BLOCKED}) if t.status in _OPEN else t
                for t in self.tasks
            ]
        elif status is TeamRunStatus.DONE and any(
            t.status is not TaskStatus.DONE for t in self.tasks[self.carried_tasks :]
        ):
            raise RuntimeError("a team cannot finish done with unfinished tasks")
        summary = TeamRun(
            run_id=self.run_id,
            stage=self.stage,
            trigger=self.trigger,
            status=status,
            rounds=self.rounds,
            issues_raised=self.issues_raised,
            issues_resolved=self.issues_resolved,
            escalations=list(self.escalations),
            tokens_used=self.tokens_used,
            customer_questions=list(self.customer_questions),
            resumed=self.resumed,
        )
        files = {
            "team-summary.json": summary.model_dump(mode="json"),
            "team-tasks.json": [t.model_dump(mode="json") for t in self.tasks],
            "mailbox.json": [m.model_dump(mode="json") for m in self.messages],
        }
        paths = [self.run_dir / ".gitignore"]
        for name, data in files.items():
            _dump(self.run_dir / name, data)
            paths.append(self.run_dir / name)
        suffix = " (resumed)" if self.resumed else ""
        commit_paths(
            self.store.root,
            paths,
            f"run({self.store.project_id}): {self.run_id} {status.value}{suffix}",
        )
        self.emit(f"{self.run_id} {self.stage.value}: {status.value} after {self.rounds} round(s)")
        return summary


@dataclass
class RecordingLLM:
    """Wraps a model so every request and response lands in the run's transcripts."""

    inner: LLM
    team: Team

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        self.team.log(f"{tool_name}-request", f"{system}\n\n--- user ---\n\n{user}")
        result = self.inner.generate(system=system, user=user, output=output, tool_name=tool_name)
        self.team.log(f"{tool_name}-response", result.value.model_dump_json(indent=2))
        return result
