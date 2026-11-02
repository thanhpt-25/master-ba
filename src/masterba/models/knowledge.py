"""Knowledge base models (specs/01-data-contracts.md items 16-17, specs/12-local-rag.md).

`KbManifest` is committed as `knowledge/manifest.json`. `Passage`, `SourceIndexState`
and `ReindexRecord` describe the index under `knowledge/index/`, which is not committed.
"""

import datetime as dt
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, PlainSerializer, StringConstraints, model_validator

from masterba.models.base import FrozenModel
from masterba.models.ids import ChunkRef, SourceId


def _to_utc_seconds(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must carry a time zone")
    return value.astimezone(dt.UTC).replace(microsecond=0)


def _format_utc(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


# A time-zone-aware timestamp, stored in UTC without microseconds and written to JSON
# as `2026-11-02T09:14:05Z`. Naive datetimes are rejected.
UtcTimestamp = Annotated[
    dt.datetime,
    AfterValidator(_to_utc_seconds),
    PlainSerializer(_format_utc, return_type=str, when_used="json"),
]

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class KbSource(FrozenModel):
    id: SourceId
    file_name: str = Field(min_length=1, max_length=255)
    suffix: Literal[".md", ".txt", ".xlsx", ".docx", ".pdf"]
    sha256: Sha256Hex
    added_by: str = Field(min_length=1)
    added_at: UtcTimestamp
    removed: bool = False
    removed_at: UtcTimestamp | None = None


class KbManifest(FrozenModel):
    format: Literal[1] = 1
    sources: list[KbSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ascending_unique_ids(self) -> Self:
        ids = [source.id for source in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("source ids must be unique")
        if ids != sorted(ids):
            raise ValueError("sources must be in ascending id order")
        return self


class KbCitation(FrozenModel):
    # A plain string on purpose: the citation gate checks the Chunk_Ref form and reports it.
    chunk_ref: str = Field(min_length=1)
    quote: str | None = None


class Passage(FrozenModel):
    chunk_ref: ChunkRef
    text: str
    heading_path: list[str] = Field(default_factory=list)
    sheet: str | None = None
    rows: tuple[int, int] | None = None
    page: int | None = None
    score: float


class SourceIndexState(FrozenModel):
    sha256: str
    status: Literal["indexed", "failed"]
    reason: str | None = None
    chunks: int = Field(ge=0)


class ReindexRecord(FrozenModel):
    format_version: int
    embedder: str | None
    built_at: UtcTimestamp
    sources: dict[SourceId, SourceIndexState]
