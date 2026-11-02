"""Retriever protocol, reciprocal rank fusion, the hybrid retriever and its fake (Requirement 7)."""

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from masterba.knowledge.errors import KnowledgeUnavailableError
from masterba.knowledge.indexer import DEFAULT_BACKEND, IndexBackend, open_index
from masterba.knowledge.manifest import load_manifest
from masterba.knowledge.paths import KbPaths
from masterba.knowledge.vectors import VectorStore
from masterba.models import Passage
from masterba.models.ids import chunk_key, parse_chunk_ref
from masterba.trace_store import NotFoundError, ProjectStore

MAX_QUERY_CHARS = 1_000
MAX_K = 50
DEFAULT_K = 5
MAX_FILTERS = 100
CANDIDATES = 50
RRF_K = 60

Mode = Literal["hybrid", "keyword"]
Argument = Literal["query", "k", "filters"]


class SearchArgumentError(ValueError):
    def __init__(self, argument: Argument, message: str) -> None:
        super().__init__(f"invalid {argument}: {message}")
        self.argument: Argument = argument


class Retriever(Protocol):
    mode: Mode  # of the last search

    def search(
        self, query: str, k: int = DEFAULT_K, filters: Sequence[str] | None = None
    ) -> list[Passage]: ...


def validate_search_args(
    query: str, k: int, filters: Sequence[str] | None, known: frozenset[str]
) -> None:
    """Reject bad arguments before any index access (Requirements 7.1, 7.9, 7.10)."""
    if not isinstance(query, str) or not query.strip():
        raise SearchArgumentError("query", "the query is empty")
    if len(query) > MAX_QUERY_CHARS:
        raise SearchArgumentError("query", f"the query is longer than {MAX_QUERY_CHARS} characters")
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise SearchArgumentError("k", f"k must be an integer from 1 to {MAX_K}")
    if filters is None:
        return
    if not 1 <= len(filters) <= MAX_FILTERS:
        raise SearchArgumentError("filters", f"give 1 to {MAX_FILTERS} Source_Ids")
    unknown = sorted(set(filters) - known)
    if unknown:
        raise SearchArgumentError("filters", "unknown Source_Ids: " + ", ".join(unknown))


def rrf_fuse(ranked_lists: Sequence[Sequence[str]], rrf_k: int = RRF_K) -> list[tuple[str, float]]:
    """Sum of 1 / (rrf_k + rank) over the lists holding each ref; descending, ties by chunk_key."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, ref in enumerate(dict.fromkeys(ranked), start=1):
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], chunk_key(item[0])))


def source_of(ref: str) -> str:
    parsed = parse_chunk_ref(ref)
    return parsed[0] if parsed else ""


def active_source_ids(paths: KbPaths) -> frozenset[str]:
    return frozenset(s.id for s in load_manifest(paths).sources if not s.removed)


class HybridRetriever:
    """Keyword (FTS5) plus vector search over the active generation, fused by RRF."""

    def __init__(self, store: ProjectStore, backend: IndexBackend = DEFAULT_BACKEND) -> None:
        if not (store.path / "project.json").is_file():
            raise NotFoundError(f"project {store.project_id} does not exist")
        self.paths = KbPaths(store.path / "knowledge")
        self.backend = backend
        self.mode: Mode = "keyword"

    def _vector_refs(
        self,
        vectors: VectorStore | None,
        embedder_name: str | None,
        query: str,
        allowed: frozenset[str],
    ) -> list[str] | None:
        if vectors is None or embedder_name is None:
            return None
        try:
            vector = self.backend.load(embedder_name).embed_query(query)
        except Exception:  # noqa: BLE001 - fall back to keyword-only (Requirement 7.3)
            return None
        return vectors.search(vector, CANDIDATES, allowed)

    def search(
        self, query: str, k: int = DEFAULT_K, filters: Sequence[str] | None = None
    ) -> list[Passage]:
        active = active_source_ids(self.paths)
        validate_search_args(query, k, filters, active)
        allowed = active & frozenset(filters) if filters is not None else active
        index = open_index(self.paths, self.backend)
        try:
            keyword = index.keyword.search(query, CANDIDATES, allowed)
            vector = self._vector_refs(index.vectors, index.record.embedder, query, allowed)
            if vector is None:
                self.mode = "keyword"
                ranked = [(ref, 1.0 / (RRF_K + rank)) for rank, ref in enumerate(keyword, 1)]
            else:
                self.mode = "hybrid"
                ranked = rrf_fuse([keyword, vector])
            # The index may still hold chunks of a source removed since it was built.
            ranked = [(ref, score) for ref, score in ranked if source_of(ref) in allowed][:k]
            passages = []
            for ref, score in ranked:
                chunk = index.keyword.chunk(ref)
                if chunk is None:
                    raise KnowledgeUnavailableError(
                        f"the knowledge base index lacks {ref}; run `masterba kb reindex`"
                    )
                passages.append(
                    Passage(
                        chunk_ref=ref,
                        text=chunk.text,
                        heading_path=list(chunk.heading_path),
                        sheet=chunk.sheet,
                        rows=chunk.rows,
                        page=chunk.page,
                        score=score,
                    )
                )
            return passages
        finally:
            index.close()


@dataclass
class FakeRetriever:
    """In-memory Retriever for tests (Requirement 7.8).

    A passage matches when its NFKC text and the NFKC query contain one another;
    `match_all=True` returns every passage. Every accepted call is recorded in `calls`.
    """

    passages: Sequence[Passage]
    known_sources: Iterable[str] | None = None
    match_all: bool = False
    mode: Mode = "keyword"
    calls: list[tuple[str, int, tuple[str, ...] | None]] = field(default_factory=list)

    def search(
        self, query: str, k: int = DEFAULT_K, filters: Sequence[str] | None = None
    ) -> list[Passage]:
        known = frozenset(
            self.known_sources
            if self.known_sources is not None
            else (source_of(p.chunk_ref) for p in self.passages)
        )
        validate_search_args(query, k, filters, known)
        self.calls.append((query, k, tuple(filters) if filters is not None else None))
        allowed = frozenset(filters) if filters is not None else known
        q = unicodedata.normalize("NFKC", query)
        unique: dict[str, Passage] = {}
        for passage in self.passages:
            text = unicodedata.normalize("NFKC", passage.text)
            hit = self.match_all or text in q or q in text
            if hit and source_of(passage.chunk_ref) in allowed:
                unique.setdefault(passage.chunk_ref, passage)
        ordered = sorted(unique.values(), key=lambda p: (-p.score, chunk_key(p.chunk_ref)))
        return ordered[:k]
