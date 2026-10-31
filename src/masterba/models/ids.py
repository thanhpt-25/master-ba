"""Identifier types and helpers (specs/00-constitution.md section 3)."""

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
TC_ID_PATTERN = rf"^TC-(?:{_LEVEL_ALT})-\d{{4}}$"
RUN_ID_PATTERN = r"^RUN-\d{4}$"
TEAM_TRIGGER_PATTERN = r"^(?:initial|DR-\d{4})$"
NODE_ID_PATTERN = (
    rf"^(?:REQ-\d{{4}}|DOC-(?:{_TYPE_ALT})-\d{{4}}(?:#item\.\d+)?|TC-(?:{_LEVEL_ALT})-\d{{4}})$"
)
REQ_OR_ITEM_PATTERN = rf"^(?:REQ-\d{{4}}|DOC-(?:{_TYPE_ALT})-\d{{4}}#item\.\d+)$"

ProjectId = Annotated[str, StringConstraints(pattern=PROJECT_ID_PATTERN)]
ReqId = Annotated[str, StringConstraints(pattern=REQ_ID_PATTERN)]
DocId = Annotated[str, StringConstraints(pattern=DOC_ID_PATTERN)]
ItemRef = Annotated[str, StringConstraints(pattern=ITEM_REF_PATTERN)]
DrId = Annotated[str, StringConstraints(pattern=DR_ID_PATTERN)]
TcId = Annotated[str, StringConstraints(pattern=TC_ID_PATTERN)]
RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
TeamTrigger = Annotated[str, StringConstraints(pattern=TEAM_TRIGGER_PATTERN)]
NodeId = Annotated[str, StringConstraints(pattern=NODE_ID_PATTERN)]
ReqOrItemRef = Annotated[str, StringConstraints(pattern=REQ_OR_ITEM_PATTERN)]


def doc_type_of(doc_id: str) -> str:
    """Return the `<TYPE>` part of `DOC-<TYPE>-####` (or of an item ref)."""
    return doc_id.split("#", 1)[0].split("-")[1]


def doc_id_of(item_ref: str) -> str:
    """Return the document id owning an item ref."""
    return item_ref.split("#", 1)[0]
