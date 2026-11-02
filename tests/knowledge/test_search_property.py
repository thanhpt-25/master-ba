# Feature: local-rag, Property 14: Search contract
# Feature: local-rag, Property 15: Only active sources are returned
# Feature: local-rag, Property 16: Keyword-only mode equals keyword ranking
# Feature: local-rag, Property 17: Invalid search arguments are rejected
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kbhelpers import fresh_project, hash_backend, keyword_backend, md
from masterba.knowledge.indexer import open_index
from masterba.knowledge.manifest import manifest_bytes
from masterba.knowledge.retriever import (
    FakeRetriever,
    HybridRetriever,
    SearchArgumentError,
    source_of,
)
from masterba.knowledge.store import add_sources, kb_paths, read_manifest, remove_source
from masterba.models import KbManifest, Passage
from masterba.models.ids import chunk_key

_chars = st.sampled_from(list("受注出荷請求ab "))
_docs = st.lists(st.text(_chars, min_size=2, max_size=40), min_size=1, max_size=4)
_queries = st.text(_chars, min_size=1, max_size=4).filter(str.strip)


def _check_contract(passages: list[Passage], k: int, filters: list[str] | None) -> None:
    refs = [p.chunk_ref for p in passages]
    assert len(passages) <= k and len(refs) == len(set(refs))
    keys = [(-p.score, chunk_key(p.chunk_ref)) for p in passages]
    assert keys == sorted(keys)
    if filters is not None:
        assert {source_of(r) for r in refs} <= set(filters)


@given(_docs, _queries, st.integers(1, 50), st.booleans(), st.booleans())
def test_hybrid_search_contract(
    docs: list[str], query: str, k: int, use_filter: bool, vectors: bool
) -> None:
    backend = hash_backend() if vectors else keyword_backend()
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        files = [md(f"d{i}.md", d) for i, d in enumerate(dict.fromkeys(docs))]
        add_sources(store, files, "u", backend=backend)
        filters = ["KB-0001"] if use_filter else None
        retriever = HybridRetriever(store, backend)
        first = retriever.search(query, k, filters)
        assert retriever.search(query, k, filters) == first
        _check_contract(first, k, filters)
        if not vectors:  # Property 16
            assert retriever.mode == "keyword"
            index = open_index(kb_paths(store), backend)
            expected = index.keyword.search(query, 50, None)[:k]
            index.close()
            if not use_filter:
                assert [p.chunk_ref for p in first] == expected
        else:
            assert retriever.mode == "hybrid"


@given(_docs, _queries)
def test_only_active_sources(docs: list[str], query: str) -> None:
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        files = [md(f"d{i}.md", d) for i, d in enumerate(dict.fromkeys(docs))]
        add_sources(store, files, "u", backend=keyword_backend())
        retriever = HybridRetriever(store, keyword_backend())
        remove_source(store, "KB-0001", backend=keyword_backend())
        assert all(source_of(p.chunk_ref) != "KB-0001" for p in retriever.search(query, 50))
        # Manifest edited after the build: the index still holds KB-0002's chunks.
        paths = kb_paths(store)
        manifest = read_manifest(store)
        kept = [s for s in manifest.sources if s.id != "KB-0002"]
        paths.manifest.write_bytes(manifest_bytes(KbManifest(sources=kept)))
        assert all(
            source_of(p.chunk_ref) not in {"KB-0001", "KB-0002"}
            for p in retriever.search(query, 50)
        )


_bad = st.one_of(
    st.tuples(st.sampled_from(["", "   ", "\n", "a" * 1001]), st.just(5), st.none()).map(
        lambda t: (*t, "query")
    ),
    st.tuples(st.just("受注"), st.sampled_from([0, -1, 51, 100]), st.none()).map(
        lambda t: (*t, "k")
    ),
    st.tuples(
        st.just("受注"),
        st.just(5),
        st.sampled_from([["KB-0099"], [], ["KB-0001", "KB-0042"], ["x"] * 101]),
    ).map(lambda t: (*t, "filters")),
)


@given(_bad)
def test_invalid_arguments(bad: tuple[str, int, list[str] | None, str]) -> None:
    query, k, filters, argument = bad
    fake = FakeRetriever([Passage(chunk_ref="KB-0001#chunk.1", text="受注", score=1.0)])
    with pytest.raises(SearchArgumentError) as info:
        fake.search(query, k, filters)
    assert info.value.argument == argument and fake.calls == []
    if filters and argument == "filters" and len(filters) <= 100:
        unknown = sorted(set(filters) - {"KB-0001"})
        assert str(info.value).endswith(", ".join(unknown))


@given(
    st.lists(
        st.builds(
            Passage,
            chunk_ref=st.sampled_from([f"KB-000{s}#chunk.{n}" for s in (1, 2) for n in (1, 2, 10)]),
            text=st.sampled_from(["受注", "受注登録", "出荷"]),
            score=st.sampled_from([0.1, 0.5, 0.5, 1.0]),
        ),
        max_size=8,
    ),
    st.integers(1, 50),
    st.sampled_from([None, ["KB-0001"], ["KB-0002"]]),
)
def test_fake_retriever_contract(
    passages: list[Passage], k: int, filters: list[str] | None
) -> None:
    fake = FakeRetriever(passages, known_sources=["KB-0001", "KB-0002"])
    result = fake.search("受注", k, filters)
    _check_contract(result, k, filters)
    assert all("受注" in p.text for p in result)
