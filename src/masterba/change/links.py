"""Trace links implied by a document's content (spec 07 section 4.1).

The stage pipelines of Phases 3 to 6 write these links when they create a document; a revision
uses the same rules to add the links that a new version needs. Links are never deleted.
"""

from collections.abc import Sequence

from masterba.models import (
    BasicDesignItem,
    BrdItem,
    DetailDesignItem,
    Payload,
    SrsItem,
    TestCaseItem,
    TraceLink,
    payload_items,
)
from masterba.models.enums import ItemStatus, LinkType


def links_for_document(content: Payload) -> list[TraceLink]:
    """Links implied by the active items of `content`, in item order, without repeats."""
    links: list[TraceLink] = []
    for item in payload_items(content):
        if item.status is not ItemStatus.ACTIVE:
            continue
        if isinstance(item, BrdItem):
            links.append(_link(item.requirement_id, item.item_id, LinkType.REALIZES))
        elif isinstance(item, SrsItem):
            sources = list(dict.fromkeys(item.derives_from)) or [item.requirement_id]
            links.extend(_link(src, item.item_id, LinkType.REALIZES) for src in sources)
        elif isinstance(item, BasicDesignItem):
            links.extend(_link(ref, item.item_id, LinkType.REALIZES) for ref in item.realizes)
        elif isinstance(item, DetailDesignItem):
            links.extend(_link(ref, item.item_id, LinkType.REALIZES) for ref in item.refines)
        elif isinstance(item, TestCaseItem):
            links.extend(_link(ref, item.test_id, LinkType.TESTS) for ref in item.verifies)
    return list(dict.fromkeys(links))


def missing_links(existing: Sequence[TraceLink], wanted: Sequence[TraceLink]) -> list[TraceLink]:
    """The wanted links that are not yet stored, keeping their order."""
    have = set(existing)
    return [link for link in wanted if link not in have]


def _link(from_id: str, to_id: str, link_type: LinkType) -> TraceLink:
    return TraceLink(from_id=from_id, to_id=to_id, link_type=link_type)
