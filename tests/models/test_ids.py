from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from masterba.models.ids import (
    DocId,
    DrId,
    ItemRef,
    NodeId,
    ProjectId,
    ReqId,
    RunId,
    TcId,
    doc_id_of,
    doc_type_of,
)


@pytest.mark.parametrize(
    ("tp", "good", "bad"),
    [
        (ProjectId, "PRJ-001", "PRJ-1"),
        (ReqId, "REQ-0001", "REQ-001"),
        (DocId, "DOC-BASIC_DESIGN-0001", "DOC-BASIC-0001"),
        (ItemRef, "DOC-SRS-0001#item.12", "DOC-SRS-0001#row.12"),
        (DrId, "DR-0007", "DR-7"),
        (TcId, "TC-UT-0045", "TC-XX-0045"),
        (RunId, "RUN-0012", "RUN-12"),
    ],
)
def test_id_accepts_valid_and_rejects_invalid(tp: Any, good: str, bad: str) -> None:
    adapter: TypeAdapter[str] = TypeAdapter(tp)
    assert adapter.validate_python(good) == good
    with pytest.raises(ValidationError):
        adapter.validate_python(bad)


@pytest.mark.parametrize(
    "value", ["REQ-0001", "DOC-BRD-0001", "DOC-TEST_UAT-0003#item.4", "TC-IT-0001"]
)
def test_node_id_accepts_every_traceable_kind(value: str) -> None:
    assert TypeAdapter(NodeId).validate_python(value) == value


def test_node_id_rejects_decision_records() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(NodeId).validate_python("DR-0007")


def test_helpers_split_ids() -> None:
    assert doc_type_of("DOC-DETAIL_DESIGN-0002#item.3") == "DETAIL_DESIGN"
    assert doc_id_of("DOC-SRS-0001#item.12") == "DOC-SRS-0001"
    assert doc_id_of("DOC-SRS-0001") == "DOC-SRS-0001"
