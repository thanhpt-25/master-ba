"""Identifier types and helpers (specs/00-constitution.md section 3)."""

import re
from typing import Annotated

from pydantic import StringConstraints

DOC_TYPES = (
    "BRD",
    "SRS",
    "BASIC_DESIGN",
    "DETAIL_DESIGN",
    "TEST_IT",
    "TEST_ST",
    "TEST_UT",
    "TEST_UAT",
)
LEVELS = ("UT", "IT", "ST", "UAT")

_TYPE_ALT = "|".join(DOC_TYPES)
_LEVEL_ALT = "|".join(LEVELS)

PROJECT_ID_PATTERN = r"^PRJ-\d{3}$"
REQ_ID_PATTERN = r"^REQ-\d{4}$"
DOC_ID_PATTERN = rf"^DOC-(?:{_TYPE_ALT})-\d{{4}}$"
ITEM_REF_PATTERN = rf"^DOC-(?:{_TYPE_ALT})-\d{{4}}#item\.\d+$"
DR_ID_PATTERN = r"^DR-\d{4}$"
QUESTION_ID_PATTERN = r"^Q-\d{4}$"
REVIEW_ID_PATTERN = r"^REV-\d{4}$"
TC_ID_PATTERN = rf"^TC-(?:{_LEVEL_ALT})-\d{{4}}$"
RUN_ID_PATTERN = r"^RUN-\d{4}$"
TEAM_TRIGGER_PATTERN = r"^(?:initial|DR-\d{4})$"
SOURCE_ID_PATTERN = r"^KB-\d{4}$"
CHUNK_REF_PATTERN = r"^KB-\d{4}#chunk\.[1-9]\d*$"
NODE_ID_PATTERN = (
    rf"^(?:REQ-\d{{4}}|DOC-(?:{_TYPE_ALT})-\d{{4}}(?:#item\.\d+)?"
    rf"|TC-(?:{_LEVEL_ALT})-\d{{4}}|KB-\d{{4}})$"
)
REQ_OR_ITEM_PATTERN = rf"^(?:REQ-\d{{4}}|DOC-(?:{_TYPE_ALT})-\d{{4}}#item\.\d+)$"

ProjectId = Annotated[str, StringConstraints(pattern=PROJECT_ID_PATTERN)]
ReqId = Annotated[str, StringConstraints(pattern=REQ_ID_PATTERN)]
DocId = Annotated[str, StringConstraints(pattern=DOC_ID_PATTERN)]
ItemRef = Annotated[str, StringConstraints(pattern=ITEM_REF_PATTERN)]
DrId = Annotated[str, StringConstraints(pattern=DR_ID_PATTERN)]
QuestionId = Annotated[str, StringConstraints(pattern=QUESTION_ID_PATTERN)]
ReviewId = Annotated[str, StringConstraints(pattern=REVIEW_ID_PATTERN)]
TcId = Annotated[str, StringConstraints(pattern=TC_ID_PATTERN)]
RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
TeamTrigger = Annotated[str, StringConstraints(pattern=TEAM_TRIGGER_PATTERN)]
SourceId = Annotated[str, StringConstraints(pattern=SOURCE_ID_PATTERN)]
ChunkRef = Annotated[str, StringConstraints(pattern=CHUNK_REF_PATTERN)]
NodeId = Annotated[str, StringConstraints(pattern=NODE_ID_PATTERN)]
ReqOrItemRef = Annotated[str, StringConstraints(pattern=REQ_OR_ITEM_PATTERN)]


def doc_type_of(doc_id: str) -> str:
    """Return the `<TYPE>` part of `DOC-<TYPE>-####` (or of an item ref)."""
    return doc_id.split("#", 1)[0].split("-")[1]


def doc_id_of(item_ref: str) -> str:
    """Return the document id owning an item ref."""
    return item_ref.split("#", 1)[0]


_CHUNK_REF = re.compile(r"^(KB-(\d{4}))#chunk\.([1-9]\d*)$")


def parse_chunk_ref(ref: str) -> tuple[str, int] | None:
    """Return `(Source_Id, n)` for a well-formed `KB-####` + `#chunk.<n>`, None otherwise."""
    match = _CHUNK_REF.fullmatch(ref)
    if match is None:
        return None
    return match.group(1), int(match.group(3))


def chunk_key(ref: str) -> tuple[int, int]:
    """Return `(source number, chunk number)`: the ascending Chunk_Ref order for tie-breaks.

    Plain string order would put `KB-0001#chunk.10` before `KB-0001#chunk.2`.
    Raises ValueError for a malformed ref.
    """
    match = _CHUNK_REF.fullmatch(ref)
    if match is None:
        raise ValueError(f"not a Chunk_Ref: {ref!r}")
    return int(match.group(2)), int(match.group(3))
