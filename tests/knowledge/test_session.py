"""KnowledgeSession and open_session (Requirements 9.1, 9.6-9.8, 10.5)."""

import pytest

from kbhelpers import keyword_backend, md
from masterba.knowledge import FakeRetriever, KnowledgeUnavailableError, add_sources, open_session
from masterba.knowledge.indexer import current_generation
from masterba.knowledge.store import kb_paths
from masterba.models import KbCitation, Passage
from masterba.trace_store import ProjectStore


def test_no_knowledge_base_means_no_session(store: ProjectStore) -> None:
    assert open_session(store, backend=keyword_backend()) is None


def test_only_failed_sources_means_no_session(store: ProjectStore) -> None:
    from masterba.knowledge.store import IncomingFile

    add_sources(store, [IncomingFile("a.pdf", b"%PDF-1.4 x")], "u", backend=keyword_backend())
    assert open_session(store, backend=keyword_backend()) is None


def test_broken_index_raises(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "受注")], "u", backend=keyword_backend())
    paths = kb_paths(store)
    (paths.index / str(current_generation(paths)) / "keyword.sqlite").unlink()
    with pytest.raises(KnowledgeUnavailableError, match="PRJ-001.*kb reindex"):
        open_session(store, backend=keyword_backend())


def test_session_blocks_and_gate(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "受注とは注文を受けること。")], "u", backend=keyword_backend())
    session = open_session(store, backend=keyword_backend())
    assert session is not None
    text = session.references_for("writer", "受注")
    assert '<reference ref="KB-0001#chunk.1">' in text
    assert session.block_for_review("writer").text == text
    assert session.block_for_review("tester").text == ""
    ok = KbCitation(chunk_ref="KB-0001#chunk.1", quote="注文を受ける")
    assert session.gate("writer", [("DOC-BRD-0001#item.1", ok)]) == []
    assert session.gate("tester", [("DOC-BRD-0001#item.1", ok)]) == [
        "KB-0001#chunk.1 in DOC-BRD-0001#item.1: was not in any knowledge block of this run"
    ]
    assert session.references_for("writer", "関係ない") == ""
    assert session.seen_refs["writer"] == {"KB-0001#chunk.1"}  # earlier refs stay seen


def test_fake_retriever_filters_and_k(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "受注")], "u", backend=keyword_backend())
    fake = FakeRetriever([Passage(chunk_ref="KB-0001#chunk.1", text="受注", score=1.0)])
    session = open_session(store, lambda s: fake, backend=keyword_backend())
    assert session is not None
    session.references_for("writer", "受注\n出荷")
    assert fake.calls == [("受注\n出荷", 12, ("KB-0001",))]


def test_retriever_failure_becomes_unavailable(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "受注")], "u", backend=keyword_backend())

    class Broken:
        mode = "keyword"

        def search(self, query: str, k: int = 5, filters: object = None) -> list[Passage]:
            raise OSError("disk")

    session = open_session(store, lambda s: Broken(), backend=keyword_backend())  # type: ignore[arg-type,return-value]
    assert session is not None
    with pytest.raises(KnowledgeUnavailableError, match="kb reindex"):
        session.references_for("writer", "受注")
