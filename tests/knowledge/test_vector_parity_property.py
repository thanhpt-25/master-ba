# Feature: local-rag, Property 12: Keyword and vector indexes hold the same refs
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from kbhelpers import MemoryVectors, fresh_project, hash_backend, md
from masterba.knowledge.indexer import open_index
from masterba.knowledge.store import (
    add_sources,
    kb_paths,
    read_manifest,
    remove_source,
    replace_source,
)

_ops = st.lists(
    st.tuples(st.sampled_from(["add", "replace", "remove"]), st.integers(0, 5)),
    min_size=1,
    max_size=5,
)


@given(_ops)
def test_vector_and_keyword_refs_match(ops: list[tuple[str, int]]) -> None:
    vectors = MemoryVectors()
    backend = hash_backend(vectors)
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        for counter, (op, n) in enumerate(ops, start=1):
            text = f"受注 {counter}\n\n出荷 {counter} " + "a" * n
            active = [s.id for s in read_manifest(store).sources if not s.removed]
            if op == "add" or not active:
                add_sources(store, [md(f"f{counter}.md", text)], "u", backend=backend)
            elif op == "replace":
                replace_source(
                    store, active[n % len(active)], md(f"r{counter}.md", text), "u", backend=backend
                )
            else:
                remove_source(store, active[n % len(active)], backend=backend)
            index = open_index(kb_paths(store), backend)
            try:
                assert index.vectors is not None
                assert index.vectors.refs() == set(index.keyword.chunk_refs())
            finally:
                index.close()
