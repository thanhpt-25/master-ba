"""Impact analysis: a pure trace-graph query, no LLM (spec 07 section 3)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from masterba.models.enums import DocType, DrTrigger
from masterba.models.ids import TC_ID_PATTERN, doc_id_of
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    known_nodes,
    latest_documents,
    query_impact,
)

V_ORDER: tuple[DocType, ...] = (
    DocType.BRD,
    DocType.SRS,
    DocType.BASIC_DESIGN,
    DocType.TEST_IT,
    DocType.TEST_ST,
    DocType.DETAIL_DESIGN,
    DocType.TEST_UT,
)
_TC = re.compile(TC_ID_PATTERN)


@dataclass(frozen=True)
class ImpactEntry:
    node_id: str
    doc_id: str | None
    depth: int
    link_type: str
    direction: str


@dataclass(frozen=True)
class Impact:
    entries: tuple[ImpactEntry, ...]
    documents: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "entries": [
                {
                    "node_id": e.node_id,
                    "doc_id": e.doc_id,
                    "depth": e.depth,
                    "link_type": e.link_type,
                    "direction": e.direction,
                }
                for e in self.entries
            ],
            "documents": list(self.documents),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Impact":
        entries = tuple(ImpactEntry(**e) for e in data["entries"])
        return cls(entries, tuple(data["documents"]))


def resolve_node(store: ProjectStore, node_id: str) -> str:
    """Return the graph node for an id; test case ids become their item refs."""
    if _TC.match(node_id):
        for _, content in latest_documents(store):
            for item in getattr(content, "items", []):
                if getattr(item, "test_id", None) == node_id:
                    return str(item.item_id)
        raise NotFoundError(f"{node_id} is not a known test case")
    if node_id not in known_nodes(store):
        raise NotFoundError(f"{node_id} is not a known trace node")
    return node_id


def _doc_of(node_id: str) -> str | None:
    return doc_id_of(node_id) if node_id.startswith("DOC-") else None


def _ordered(doc_ids: set[str]) -> tuple[str, ...]:
    def key(doc_id: str) -> tuple[int, str]:
        doc_type = doc_id.split("-", 1)[1].rsplit("-", 1)[0]
        return (V_ORDER.index(DocType(doc_type)), doc_id)

    return tuple(sorted(doc_ids, key=key))


def analyse_impact(
    store: ProjectStore, impacted_items: Sequence[str], trigger: DrTrigger
) -> Impact:
    """Items and documents affected by changing `impacted_items`, documents in V order."""
    direction = "both" if trigger is DrTrigger.DEFECT else "downstream"
    entries: list[ImpactEntry] = []
    docs: set[str] = set()
    seen: set[str] = set()
    for raw in impacted_items:
        node = resolve_node(store, raw)
        if (doc := _doc_of(node)) is not None:
            docs.add(doc)
        for found in query_impact(store, node, direction):  # type: ignore[arg-type]
            if found.node_id in seen:
                continue
            seen.add(found.node_id)
            doc = _doc_of(found.node_id)
            if doc is not None:
                docs.add(doc)
            entries.append(
                ImpactEntry(found.node_id, doc, found.depth, found.link_type, found.direction)
            )
    return Impact(tuple(entries), _ordered(docs))
