# Feature: local-rag, Property 10: Rebuilding the index is a round trip
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from kbhelpers import fresh_project, keyword_backend, md
from masterba.knowledge.indexer import open_index, reindex
from masterba.knowledge.store import add_sources, kb_paths
from masterba.trace_store import ProjectStore

_texts = st.lists(
    st.text(st.sampled_from(list("受注出荷ab #\n。")), min_size=1, max_size=80),
    min_size=1,
    max_size=4,
)
_queries = st.lists(
    st.text(st.sampled_from(list("受注出荷ab")), min_size=1, max_size=3), max_size=4
)


State = tuple[list[str], list[tuple[str, tuple[str, ...]]], list[list[str]]]


def _state(store: ProjectStore, queries: list[str]) -> State:
    index = open_index(kb_paths(store), keyword_backend())
    try:
        refs = index.keyword.chunk_refs()
        chunks = [index.keyword.chunk(r) for r in refs]
        results = [index.keyword.search(q, 50, None) for q in queries]
    finally:
        index.close()
    return refs, [(c.text, c.heading_path) for c in chunks if c], results


@given(_texts, _queries)
def test_rebuild_round_trip(texts: list[str], queries: list[str]) -> None:
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        files = [md(f"s{i}.md", t) for i, t in enumerate(dict.fromkeys(texts))]
        add_sources(store, files, "u", backend=keyword_backend())
        reindex(store, backend=keyword_backend())
        first = _state(store, queries)
        shutil.rmtree(kb_paths(store).index)
        reindex(store, backend=keyword_backend())
        assert _state(store, queries) == first
