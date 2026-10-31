"""Task list and mailbox entries of a Phase Team run (specs/04-srs-qa-and-team-runtime.md 2.1)."""

from enum import StrEnum

from pydantic import Field

from masterba.models.base import FrozenModel
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
