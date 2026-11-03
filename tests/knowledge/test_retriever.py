from pathlib import Path

import pytest

from kbhelpers import hash_backend, keyword_backend, md
from masterba.knowledge.errors import KnowledgeUnavailableError
from masterba.knowledge.indexer import IndexBackend
from masterba.knowledge.retriever import HybridRetriever
from masterba.knowledge.store import add_sources
from masterba.trace_store import NotFoundError, ProjectStore


def test_unknown_project_and_missing_index(store: ProjectStore, projects_root: Path) -> None:
    with pytest.raises(NotFoundError):
        HybridRetriever(ProjectStore(projects_root, "PRJ-404"))
    with pytest.raises(KnowledgeUnavailableError, match="kb reindex"):
        HybridRetriever(store, keyword_backend()).search("受注")


def test_embedder_failure_falls_back_to_keyword(store: ProjectStore) -> None:
    backend = hash_backend()
    add_sources(store, [md("a.md", "受注の登録")], "u", backend=backend)

    def broken(name: str) -> object:
        raise OSError("model gone")

    failing = IndexBackend(backend.probe, broken, backend.vectors)  # type: ignore[arg-type]
    retriever = HybridRetriever(store, failing)
    [passage] = retriever.search("受注")
    assert retriever.mode == "keyword" and passage.chunk_ref == "KB-0001#chunk.1"
    hybrid = HybridRetriever(store, backend)
    hybrid.search("受注")
    assert hybrid.mode == "hybrid"
