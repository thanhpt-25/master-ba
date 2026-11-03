"""Knowledge_Nodes and `derives_from` links for stored documents (spec 12, Requirement 13)."""

from masterba.models import Payload, TraceLink, payload_items
from masterba.models.enums import LinkType
from masterba.models.ids import parse_chunk_ref
from masterba.trace_store import ProjectStore, get_trace_links, latest_documents


def knowledge_links(content: Payload) -> tuple[list[str], list[TraceLink]]:
    """Cited Source_Ids (once each) and one link per (source, citing item) pair."""
    pairs: dict[tuple[str, str], None] = {}
    for item in payload_items(content):
        for citation in item.kb_citations:
            parsed = parse_chunk_ref(citation.chunk_ref)
            if parsed is not None:  # the gate already refused malformed refs
                pairs[(parsed[0], item.item_id)] = None
    sources = sorted({source for source, _ in pairs})
    links = [
        TraceLink(from_id=source, to_id=item, link_type=LinkType.DERIVES_FROM)
        for source, item in sorted(pairs)
    ]
    return sources, links


def citing_items(store: ProjectStore, source_id: str) -> list[str]:
    """Items of the latest document versions that a source's links point to."""
    current = {
        item.item_id for _, content in latest_documents(store) for item in payload_items(content)
    }
    return sorted(
        {link.to_id for link in get_trace_links(store) if link.from_id == source_id} & current
    )
