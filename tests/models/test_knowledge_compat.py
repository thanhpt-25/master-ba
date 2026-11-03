"""Id helpers and loading of data written before the knowledge base fields (spec 12)."""

import pytest

from masterba.agents.qa_reviewer import Check, QaIssue
from masterba.agents.requirements_analyst import BrdDraft
from masterba.models.enums import DocType, DrTrigger
from masterba.models.ids import chunk_key, parse_chunk_ref
from masterba.models.payloads import SrsItem
from masterba.team.models import RunCheckpoint


def test_chunk_key_orders_numerically() -> None:
    refs = ["KB-0002#chunk.1", "KB-0001#chunk.10", "KB-0001#chunk.2"]
    assert sorted(refs, key=chunk_key) == ["KB-0001#chunk.2", "KB-0001#chunk.10", "KB-0002#chunk.1"]


@pytest.mark.parametrize(
    "ref", ["KB-0001#chunk.0", "KB-001#chunk.1", "KB-0001#chunk.01", "KB-0001", "x", ""]
)
def test_malformed_chunk_refs(ref: str) -> None:
    assert parse_chunk_ref(ref) is None
    with pytest.raises(ValueError):
        chunk_key(ref)


def test_parse_chunk_ref() -> None:
    assert parse_chunk_ref("KB-0042#chunk.7") == ("KB-0042", 7)


def test_old_data_without_new_fields_loads() -> None:
    item = SrsItem.model_validate(
        {
            "item_id": "DOC-SRS-0001#item.1",
            "requirement_id": "REQ-0001",
            "kind": "functional",
            "statement": "s",
        }
    )
    assert item.kb_citations == []
    draft = BrdDraft.model_validate(
        {
            "requirements": [
                {
                    "title": "t",
                    "description": "d",
                    "category": "functional",
                    "scope": "in",
                    "start_line": 1,
                    "end_line": 1,
                    "evidence_quote": "q",
                }
            ]
        }
    )
    assert draft.requirements[0].kb_citations == []
    issue = QaIssue.model_validate(
        {"checklist_id": "BRD-1", "severity": "blocking", "message": "m"}
    )
    assert issue.chunk_refs == []
    assert (
        Check.model_validate({"id": "c", "severity": "advisory", "text": "t"}).requires_reference
        is False
    )
    checkpoint = RunCheckpoint.model_validate({"stage": DocType.BRD, "round": 1, "tokens_used": 0})
    assert checkpoint.kb_seen_refs == {}
    assert DrTrigger("knowledge_change") is DrTrigger.KNOWLEDGE_CHANGE
