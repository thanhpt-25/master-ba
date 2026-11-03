# Feature: local-rag, Property 4: A refused file changes nothing
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kbhelpers import fresh_project, head, keyword_backend, md
from masterba.knowledge.errors import UploadRefusedError
from masterba.knowledge.indexer import current_generation
from masterba.knowledge.store import IncomingFile, add_sources, kb_paths, replace_source

_refused = st.one_of(
    st.builds(
        IncomingFile,
        st.sampled_from(["a.csv", "a.zip", "a/b.md", "..", "x.exe"]),
        st.binary(min_size=1, max_size=20),
    ),
    st.builds(IncomingFile, st.just("e.md"), st.just(b"")),
    st.builds(IncomingFile, st.just("bad.pdf"), st.binary(max_size=20).map(lambda b: b"X" + b)),
    st.builds(IncomingFile, st.just("bad.txt"), st.just(b"\xff\xfe\xfa")),
    st.builds(IncomingFile, st.just("bad.docx"), st.binary(min_size=1, max_size=20)),
)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@given(_refused)
def test_refused_file_changes_nothing(file: IncomingFile) -> None:
    with TemporaryDirectory() as tmp:
        store = fresh_project(Path(tmp))
        add_sources(store, [md("a.md", "受注")], "u", backend=keyword_backend())
        paths = kb_paths(store)
        before = (_snapshot(paths.root), head(store.root), current_generation(paths))
        report = add_sources(store, [file], "u", backend=keyword_backend())
        assert report.added == () and [n for n, _ in report.refused] == [file.name]
        with pytest.raises(UploadRefusedError):
            replace_source(store, "KB-0001", file, "u", backend=keyword_backend())
        after = (_snapshot(paths.root), head(store.root), current_generation(paths))
    assert after == before
