# Feature: local-rag, Property 24: Knowledge trace links are unique and idempotent
from hypothesis import given
from hypothesis import strategies as st

from factories import make_srs_item
from masterba.knowledge.trace import knowledge_links
from masterba.models import KbCitation, SrsContent

_refs = st.sampled_from(["KB-0001#chunk.1", "KB-0001#chunk.2", "KB-0002#chunk.5", "bad"])


@given(st.lists(st.lists(_refs, max_size=4), min_size=1, max_size=4))
def test_knowledge_links(per_item: list[list[str]]) -> None:
    items = [
        make_srs_item("DOC-SRS-0001", n).model_copy(
            update={"kb_citations": [KbCitation(chunk_ref=r) for r in refs]}
        )
        for n, refs in enumerate(per_item, start=1)
    ]
    nodes, links = knowledge_links(SrsContent(items=items))
    expected = {
        (r.split("#")[0], f"DOC-SRS-0001#item.{n}")
        for n, refs in enumerate(per_item, start=1)
        for r in refs
        if r != "bad"
    }
    assert nodes == sorted({s for s, _ in expected})
    assert [(x.from_id, x.to_id) for x in links] == sorted(expected)
    assert {x.link_type.value for x in links} <= {"derives_from"}
    merged = set(links)
    assert merged | set(knowledge_links(SrsContent(items=items))[1]) == merged
