"""Requirements, the traceability matrix and impact queries (spec 08 section 3)."""

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from masterba.api.deps import project_store, require_role
from masterba.models import (
    BasicDesignItem,
    BrdItem,
    DetailDesignItem,
    SrsItem,
    TestCaseItem,
    payload_items,
)
from masterba.models.ids import NODE_ID_PATTERN, REQ_ID_PATTERN
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    get_trace_links,
    latest_documents,
    list_requirements,
    query_impact,
    rtm,
)

router = APIRouter(prefix="/api/projects/{pid}")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
_NODE = re.compile(NODE_ID_PATTERN)
_REQ = re.compile(REQ_ID_PATTERN)


def _label(item: object) -> str:
    if isinstance(item, BrdItem):
        return item.title
    if isinstance(item, SrsItem):
        return item.statement
    if isinstance(item, BasicDesignItem | DetailDesignItem):
        return item.name
    if isinstance(item, TestCaseItem):
        return f"{item.test_id}: {item.expected}"
    return ""


def node_labels(store: ProjectStore) -> dict[str, dict[str, str]]:
    """Every traceable node with a short text, for display."""
    labels = {
        r.id: {"kind": "requirement", "text": r.text, "status": r.status.value}
        for r in list_requirements(store)
    }
    for _, content in latest_documents(store):
        for item in payload_items(content):
            labels[item.item_id] = {
                "kind": "item",
                "text": _label(item),
                "status": item.status.value,
            }
    return labels


@router.get("/requirements", dependencies=[Viewer])
def requirements(store: Store) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in list_requirements(store)]


@router.get("/rtm/{req_id}", dependencies=[Viewer])
def trace_matrix(store: Store, req_id: str) -> dict[str, Any]:
    if not _REQ.match(req_id):
        raise HTTPException(status_code=404, detail="no such requirement")
    try:
        paths = rtm(store, req_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such requirement") from exc
    labels = node_labels(store)
    nodes = {
        n: labels.get(n, {"kind": "item", "text": "", "status": "active"}) for p in paths for n in p
    }
    return {"requirement": req_id, "paths": paths, "nodes": nodes}


@router.get("/links", dependencies=[Viewer])
def links(store: Store) -> list[dict[str, str]]:
    return [link.model_dump(mode="json") for link in get_trace_links(store)]


@router.get("/impact", dependencies=[Viewer])
def impact(
    store: Store,
    node: str,
    direction: Literal["downstream", "upstream", "both"] = "downstream",
) -> list[dict[str, Any]]:
    if not _NODE.match(node):
        raise HTTPException(status_code=404, detail="no such node")
    try:
        found = query_impact(store, node, direction)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such node") from exc
    labels = node_labels(store)
    return [
        {
            "node_id": n.node_id,
            "depth": n.depth,
            "link_type": n.link_type,
            "direction": n.direction,
            "text": labels.get(n.node_id, {}).get("text", ""),
        }
        for n in found
    ]
