# Feature: local-rag, Property 1: Source_Ids increase and are never reused
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st

from kbhelpers import fresh_project, keyword_backend, md
from masterba.knowledge.store import add_sources, read_manifest, remove_source

# Each op adds n new distinct files, or removes the i-th active source.
_ops = st.lists(st.tuples(st.sampled_from(["add", "remove"]), st.integers(1, 3)), max_size=6)


@settings(max_examples=100)
@given(_ops)
def test_ids_increase_and_are_never_reused(ops: list[tuple[str, int]]) -> None:
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        assigned: list[str] = []
        counter = 0
        for op, n in ops:
            active = [s.id for s in read_manifest(store).sources if not s.removed]
            if op == "remove" and active:
                remove_source(store, active[(n - 1) % len(active)], backend=keyword_backend())
                continue
            if op == "remove":
                continue
            files = [md(f"f{counter + i}.md", f"content {counter + i}") for i in range(n)]
            counter += n
            report = add_sources(store, files, "u", backend=keyword_backend())
            assigned.extend(s.id for s in report.added)
    expected = [f"KB-{i:04d}" for i in range(1, len(assigned) + 1)]
    assert assigned == expected
