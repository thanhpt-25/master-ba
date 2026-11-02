# Feature: local-rag, Property 2: Added sources are recorded faithfully and duplicates are skipped
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from kbhelpers import fresh_project, keyword_backend
from masterba.knowledge.store import IncomingFile, add_sources, kb_paths, read_manifest

_texts = st.text(st.sampled_from(list("受注ab ")), min_size=1, max_size=6)


@given(st.lists(_texts, min_size=1, max_size=4), st.lists(st.integers(0, 10), max_size=6))
def test_recorded_faithfully(existing: list[str], picks: list[int]) -> None:
    pool = list(dict.fromkeys(existing))
    # The batch repeats contents already stored and contents earlier in the batch.
    batch_texts = [pool[i % len(pool)] for i in picks] + ["new-" + t for t in pool[:2]]
    batch = [IncomingFile(f"b{i}.md", t.encode()) for i, t in enumerate(batch_texts)]
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        first = add_sources(
            store,
            [IncomingFile(f"e{i}.md", t.encode()) for i, t in enumerate(pool)],
            "u",
            backend=keyword_backend(),
        )
        by_sha = {s.sha256: s.id for s in first.added}
        report = add_sources(store, batch, "tester", backend=keyword_backend())
        paths = kb_paths(store)
        manifest = read_manifest(store)
        stored = {s.id: paths.source_file(s.id, s.suffix).read_bytes() for s in manifest.sources}
    distinct_new = list(dict.fromkeys(t for t in batch_texts if t not in pool))
    assert [stored[s.id].decode() for s in report.added] == distinct_new
    names = {f.name: f for f in batch}
    for source in report.added:
        data = names[source.file_name].data
        assert (
            source.sha256
            == hashlib.sha256(data).hexdigest()
            == hashlib.sha256(stored[source.id]).hexdigest()
        )
        assert source.added_by == "tester"
    seen: dict[str, str] = dict(by_sha)
    for f in batch:
        sha = hashlib.sha256(f.data).hexdigest()
        if sha in seen and seen[sha] != f.name:
            assert (f.name, seen[sha]) in report.skipped
        seen.setdefault(sha, f.name)
