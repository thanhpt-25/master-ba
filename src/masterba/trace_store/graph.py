"""Trace graph, impact queries and RTM (specs/01-data-contracts.md section 4).

Convention: a trace link always points from the upstream artifact to the
downstream one, whatever its ``link_type`` (requirement -> design -> test).
Test case ids (``TC-...``) are canonicalised to their test item ref.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

import networkx as nx

from masterba.models import TestSpecContent
from masterba.trace_store.errors import NotFoundError
from masterba.trace_store.store import (
    ProjectStore,
    get_trace_links,
    known_nodes,
    latest_documents,
)

Direction = Literal["downstream", "upstream", "both"]
Step = Literal["downstream", "upstream"]


@dataclass(frozen=True)
class ImpactNode:
    node_id: str
    depth: int
    link_type: str
    direction: Step


def _aliases(store: ProjectStore) -> dict[str, str]:
    """Map each test id (TC-...) to the item ref of its test case."""
    aliases: dict[str, str] = {}
    for _, content in latest_documents(store):
        if isinstance(content, TestSpecContent):
            aliases.update({case.test_id: case.item_id for case in content.items})
    return aliases


def build_graph(store: ProjectStore) -> nx.DiGraph[str]:
    graph: nx.DiGraph[str] = nx.DiGraph()
    for node_id, kind in known_nodes(store).items():
        if kind != "test_id":
            graph.add_node(node_id, kind=kind)
    for doc, content in latest_documents(store):
        for item in content.items:
            graph.add_edge(doc.id, item.item_id, kind="contains", link_type="contains")
    aliases = _aliases(store)
    for link in get_trace_links(store):
        graph.add_edge(
            aliases.get(link.from_id, link.from_id),
            aliases.get(link.to_id, link.to_id),
            kind="trace",
            link_type=link.link_type.value,
        )
    return graph


def _trace_view(graph: nx.DiGraph[str]) -> nx.DiGraph[str]:
    return nx.subgraph_view(  # type: ignore[no-any-return]
        graph, filter_edge=lambda u, v: bool(graph.edges[u, v]["kind"] == "trace")
    )


def _walk(graph: nx.DiGraph[str], start: str, direction: Step) -> list[ImpactNode]:
    forward = direction == "downstream"
    seen = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    found: list[ImpactNode] = []
    while queue:
        node, depth = queue.popleft()
        neighbours = graph.successors(node) if forward else graph.predecessors(node)
        for other in sorted(neighbours):
            if other in seen:
                continue
            seen.add(other)
            edge = graph.edges[node, other] if forward else graph.edges[other, node]
            found.append(ImpactNode(other, depth + 1, str(edge["link_type"]), direction))
            queue.append((other, depth + 1))
    return found


def query_impact(
    store: ProjectStore, node_id: str, direction: Direction = "downstream"
) -> list[ImpactNode]:
    graph = build_graph(store)
    start = _aliases(store).get(node_id, node_id)
    if start not in graph:
        raise NotFoundError(f"{node_id} is not a known trace node")
    view = _trace_view(graph)
    found: list[ImpactNode] = []
    if direction in ("downstream", "both"):
        found += _walk(view, start, "downstream")
    if direction in ("upstream", "both"):
        found += _walk(view, start, "upstream")
    return found


def rtm(store: ProjectStore, req_id: str) -> list[list[str]]:
    """All trace paths from a requirement down to test cases."""
    graph = build_graph(store)
    if req_id not in graph:
        raise NotFoundError(f"{req_id} is not a known trace node")
    view = _trace_view(graph)
    targets = sorted(
        n
        for n, data in graph.nodes(data=True)
        if data.get("kind") == "test_case" and nx.has_path(view, req_id, n)
    )
    paths = [list(p) for t in targets for p in nx.all_simple_paths(view, req_id, t)]
    return sorted(paths)
