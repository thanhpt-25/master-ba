"""Task list and mailbox entries of a Phase Team run (specs/04-srs-qa-and-team-runtime.md 2.1)."""

from enum import StrEnum
from typing import Any

from pydantic import Field

from masterba.models.base import FrozenModel
from masterba.models.enums import DocType
from masterba.models.ids import ItemRef


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class TeamTask(FrozenModel):
    id: str = Field(pattern=r"^T-\d{2,}$")
    title: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    status: TaskStatus
    depends_on: list[str] = Field(default_factory=list)


class MessageType(StrEnum):
    QUESTION = "question"
    FEEDBACK = "feedback"
    ANSWER = "answer"
    DONE = "done"


class TeamMessage(FrozenModel):
    sender: str = Field(min_length=1)
    to: str = Field(min_length=1)
    type: MessageType
    ref: ItemRef | None = None
    round: int = Field(ge=1)
    body: str = Field(min_length=1)


class RunCheckpoint(FrozenModel):
    """The last validated drafts of a run, so an escalated run can resume (spec 11 section 3.1).

    `drafts` and `feedback` are keyed by role; `upstream` maps each input to its version.
    """

    stage: DocType
    round: int = Field(ge=1)
    upstream: dict[str, int] = Field(default_factory=dict)
    drafts: dict[str, dict[str, Any] | None] = Field(default_factory=dict)
    feedback: dict[str, list[str]] = Field(default_factory=dict)
    customer_questions: list[str] = Field(default_factory=list)
    tokens_used: int = Field(ge=0)
    issues_raised: int = Field(default=0, ge=0)
    issues_resolved: int = Field(default=0, ge=0)
    # (checklist id, ref) pairs that were blocking, per reviewed artifact (spec 11 section 1.5)
    blocking_seen: dict[str, list[tuple[str, str | None]]] = Field(default_factory=dict)
    # Chunk_Refs shown to each writer role in this run (spec 12, Requirement 10.5)
    kb_seen_refs: dict[str, list[str]] = Field(default_factory=dict)
