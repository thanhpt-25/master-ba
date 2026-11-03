"""Per-stage knowledge retrieval: blocks for writers and QA, and the citation gate (Req. 9, 10).

A pipeline opens one session before `Team.open`. Each writer role gets a block built from
its own input; QA reuses that exact block without a new search (Requirement 9.6).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from masterba.knowledge.citations import validate_kb_citations
from masterba.knowledge.errors import KnowledgeUnavailableError
from masterba.knowledge.indexer import (
    DEFAULT_BACKEND,
    IndexBackend,
    current_generation,
    open_index,
    read_record,
)
from masterba.knowledge.keyword import KeywordIndex
from masterba.knowledge.reference import (
    STAGE_K,
    RenderedBlock,
    build_queries,
    render_reference_block,
)
from masterba.knowledge.retriever import (
    MAX_FILTERS,
    MAX_K,
    HybridRetriever,
    Retriever,
    rrf_fuse,
    source_of,
)
from masterba.knowledge.store import kb_paths, list_sources, read_manifest
from masterba.models import KbCitation, Passage
from masterba.trace_store import ProjectStore

__all__ = ["KnowledgeSession", "KnowledgeUnavailableError", "open_session"]


@dataclass
class KnowledgeSession:
    retriever: Retriever
    indexed: frozenset[str]  # Source_Ids with status `indexed` at session start
    manifest_ids: frozenset[str]  # active Manifest ids
    chunk_text: Callable[[str], str | None]  # original text of a ref in the active index
    covers_manifest: Callable[[], bool]  # does the index hold every active source?
    seen_refs: dict[str, set[str]] = field(default_factory=dict)  # per writer role
    blocks: dict[str, RenderedBlock] = field(default_factory=dict)  # last block per role
    # Active Manifest ids right now; a source removed during the stage drops out of filters.
    active_ids: Callable[[], frozenset[str]] | None = None

    def _search(self, query: str) -> list[Passage]:
        ids = self.indexed & self.active_ids() if self.active_ids else self.indexed
        if not ids:
            return []
        if len(ids) <= MAX_FILTERS:
            return self.retriever.search(query, STAGE_K, sorted(ids))
        # Too many ids for one filter: search everything and drop the other sources.
        found = self.retriever.search(query, MAX_K, None)
        return [p for p in found if source_of(p.chunk_ref) in ids]

    def references_for(self, role: str, writer_input: str) -> str:
        """Search once per query segment, fuse, render and remember the block for `role`.

        A retriever failure becomes KnowledgeUnavailableError and stops the stage.
        """
        by_ref: dict[str, Passage] = {}
        ranked: list[list[str]] = []
        try:
            for query in build_queries(writer_input):
                passages = self._search(query)
                ranked.append([p.chunk_ref for p in passages])
                for passage in passages:
                    by_ref.setdefault(passage.chunk_ref, passage)
        except KnowledgeUnavailableError:
            raise
        except Exception as exc:
            raise KnowledgeUnavailableError(
                f"knowledge search failed ({exc}); run `masterba kb reindex`"
            ) from exc
        fused = [by_ref[ref].model_copy(update={"score": s}) for ref, s in rrf_fuse(ranked)]
        block = render_reference_block(fused)
        self.blocks[role] = block
        self.seen_refs.setdefault(role, set()).update(block.refs)
        return block.text

    def block_for_review(self, role: str) -> RenderedBlock:
        return self.blocks.get(role, RenderedBlock("", frozenset()))

    def gate(self, role: str, citations: Sequence[tuple[str, KbCitation]]) -> list[str]:
        if not citations:
            return []
        return validate_kb_citations(
            citations,
            manifest_ids=self.manifest_ids,
            chunk_text=self.chunk_text,
            index_covers_manifest=self.covers_manifest(),
            seen_refs=frozenset(self.seen_refs.get(role, set())),
        )


def _active_ids(store: ProjectStore) -> frozenset[str]:
    return frozenset(s.id for s in read_manifest(store).sources if not s.removed)


def _index_reader(
    store: ProjectStore,
) -> tuple[Callable[[str], str | None], Callable[[], bool]]:
    paths = kb_paths(store)
    opened: dict[str, KeywordIndex] = {}  # one connection per generation, reused by the gate

    def keyword() -> KeywordIndex:
        generation = current_generation(paths)
        path = paths.index / str(generation) / "keyword.sqlite"
        if generation is None or not path.is_file():
            raise KnowledgeUnavailableError(
                f"project {store.project_id}: the knowledge base index is missing; "
                "run `masterba kb reindex`"
            )
        if generation not in opened:
            opened[generation] = KeywordIndex(path)
        return opened[generation]

    def chunk_text(ref: str) -> str | None:
        chunk = keyword().chunk(ref)
        return chunk.text if chunk is not None else None

    def covers() -> bool:
        record = read_record(paths, current_generation(paths))
        return record is not None and _active_ids(store) <= set(record.sources)

    return chunk_text, covers


def open_session(
    store: ProjectStore,
    retriever_factory: Callable[[ProjectStore], Retriever] = HybridRetriever,
    backend: IndexBackend = DEFAULT_BACKEND,
) -> KnowledgeSession | None:
    """None when there is no knowledge base or no `indexed` source (prompts stay unchanged).

    Raises KnowledgeUnavailableError when the Manifest lists sources but the index cannot
    be opened, so the stage stops before any model call or commit (Requirement 9.8).
    """
    paths = kb_paths(store)
    if not paths.manifest.is_file():
        return None
    views = list_sources(store, backend)
    if not views:
        return None
    try:
        open_index(paths, backend).close()
    except KnowledgeUnavailableError as exc:
        raise KnowledgeUnavailableError(f"project {store.project_id}: {exc}") from exc
    indexed = frozenset(v.source.id for v in views if v.status == "indexed")
    if not indexed:
        return None
    chunk_text, covers = _index_reader(store)
    return KnowledgeSession(
        retriever=retriever_factory(store),
        indexed=indexed,
        manifest_ids=frozenset(v.source.id for v in views),
        chunk_text=chunk_text,
        covers_manifest=covers,
        active_ids=lambda: _active_ids(store),
    )
