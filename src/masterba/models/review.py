"""Phase review records (specs/15-phase-review-gates.md section 4)."""

from typing import Annotated, Self

from pydantic import AfterValidator, Field, model_validator

from masterba.models.base import FrozenModel
from masterba.models.enums import ReviewDecision, ReviewStage
from masterba.models.ids import DocId, DrId, ItemRef, QuestionId, ReviewId, RunId
from masterba.models.knowledge import UtcTimestamp

MAX_COMMENT_CHARS = 2_000


def _plain_text(text: str) -> str:
    if not text.strip():
        raise ValueError("a comment needs text")
    if any(ord(c) < 0x20 and c not in "\n\t" for c in text):
        raise ValueError("a comment may not contain control characters")
    return text


class ReviewComment(FrozenModel):
    ref: ItemRef | None = None  # an item of the phase's documents; none means the whole phase
    text: Annotated[str, Field(max_length=MAX_COMMENT_CHARS), AfterValidator(_plain_text)]


class ReviewedDocument(FrozenModel):
    doc_id: DocId
    version: int = Field(ge=1)


class Review(FrozenModel):
    id: ReviewId
    stage: ReviewStage
    documents: list[ReviewedDocument] = Field(min_length=1)
    decision: ReviewDecision
    by: str = Field(min_length=1)
    at: UtcTimestamp
    comments: list[ReviewComment] = Field(default_factory=list)
    open_questions: list[QuestionId] = Field(default_factory=list)
    dr_id: DrId | None = None
    revision_run: RunId | None = None

    @model_validator(mode="after")
    def _decision_fields(self) -> Self:
        rejected = self.decision is ReviewDecision.REJECTED
        if rejected != bool(self.comments):
            raise ValueError("a rejection needs comments and an approval has none")
        if not rejected and (self.dr_id or self.revision_run):
            raise ValueError("an approval has no dr_id and no revision_run")
        return self
