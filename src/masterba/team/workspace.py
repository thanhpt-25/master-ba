"""Run workspace of a Phase Team: tasks, mailbox, budget and the run record.

Files live in ``projects/<project_id>/runs/RUN-####/`` (spec 04 section 2). Summary, tasks and
mailbox are committed once at the end; ``transcripts/`` stays local.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from masterba.llm import LLM, LLMResult
from masterba.llm.base import T
from masterba.models import TeamRun
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team.models import MessageType, TaskStatus, TeamMessage, TeamTask
from masterba.trace_store import ProjectStore
from masterba.trace_store.git import commit_paths

ARTIFACT_OWNERS = {"draft": "writer", "qa-report": "qa"}
_RUN_DIR = re.compile(r"^RUN-(\d{4})$")
_OPEN = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}


class SingleWriterError(Exception):
    """A role tried to write an artifact it does not own."""


def _dump(path: Path, data: Any) -> None:
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


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
    tasks: list[TeamTask] = field(default_factory=list)
    messages: list[TeamMessage] = field(default_factory=list)
    log_count: int = 0

    @classmethod
    def open(
        cls, store: ProjectStore, stage: DocType, max_rounds: int, token_budget: int | None
    ) -> "Team":
        runs = store.path / "runs"
        used = [int(m[1]) for p in runs.glob("RUN-*") if (m := _RUN_DIR.match(p.name))]
        run_id = f"RUN-{max(used, default=0) + 1:04d}"
        team = cls(store, run_id, stage, max_rounds, token_budget)
        team.transcripts_dir.mkdir(parents=True)
        (team.run_dir / ".gitignore").write_text("transcripts/\n", encoding="utf-8")
        return team

    @property
    def run_dir(self) -> Path:
        return self.store.path / "runs" / self.run_id

    @property
    def transcripts_dir(self) -> Path:
        return self.run_dir / "transcripts"

    def begin_round(self) -> int:
        self.rounds += 1
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

    def finish(self, status: TeamRunStatus) -> TeamRun:
        """Write summary, tasks and mailbox and commit them as one commit."""
        if status is TeamRunStatus.ESCALATED:
            self.tasks = [
                t.model_copy(update={"status": TaskStatus.BLOCKED}) if t.status in _OPEN else t
                for t in self.tasks
            ]
        elif status is TeamRunStatus.DONE and any(
            t.status is not TaskStatus.DONE for t in self.tasks
        ):
            raise RuntimeError("a team cannot finish done with unfinished tasks")
        summary = TeamRun(
            run_id=self.run_id,
            stage=self.stage,
            trigger="initial",
            status=status,
            rounds=self.rounds,
            issues_raised=self.issues_raised,
            issues_resolved=self.issues_resolved,
            escalations=list(self.escalations),
            tokens_used=self.tokens_used,
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
        commit_paths(
            self.store.root, paths, f"run({self.store.project_id}): {self.run_id} {status.value}"
        )
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
