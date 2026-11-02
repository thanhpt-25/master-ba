# Feature: local-rag, Property 13: Reciprocal rank fusion
from hypothesis import given
from hypothesis import strategies as st

from masterba.knowledge.retriever import rrf_fuse
from masterba.models.ids import chunk_key

_pool = [f"KB-000{s}#chunk.{n}" for s in (1, 2) for n in (1, 2, 10)]
_lists = st.lists(
    st.permutations(_pool).flatmap(lambda p: st.integers(0, 6).map(lambda n: p[:n])), max_size=3
)


@given(_lists)
def test_rrf_fuse(lists: list[list[str]]) -> None:
    fused = rrf_fuse(lists)
    refs = [r for r, _ in fused]
    assert len(refs) == len(set(refs)) == len({r for lst in lists for r in lst})
    for ref, score in fused:
        expected = sum(1 / (60 + lst.index(ref) + 1) for lst in lists if ref in lst)
        assert abs(score - expected) < 1e-12
    keys = [(-s, chunk_key(r)) for r, s in fused]
    assert keys == sorted(keys)
