"""Local knowledge base for the generating stages (spec 12)."""

from masterba.knowledge.errors import (
    IndexBuildError,
    KbCommitError,
    KbError,
    KnowledgeUnavailableError,
    UnknownSourceError,
    UploadRefusedError,
)
from masterba.knowledge.indexer import reindex
from masterba.knowledge.retriever import (
    FakeRetriever,
    HybridRetriever,
    Retriever,
    SearchArgumentError,
)
from masterba.knowledge.session import KnowledgeSession, open_session
from masterba.knowledge.store import (
    IncomingFile,
    add_sources,
    list_sources,
    read_manifest,
    remove_source,
    replace_source,
)

__all__ = [
    "FakeRetriever",
    "HybridRetriever",
    "IncomingFile",
    "IndexBuildError",
    "KbCommitError",
    "KbError",
    "KnowledgeSession",
    "KnowledgeUnavailableError",
    "Retriever",
    "SearchArgumentError",
    "UnknownSourceError",
    "UploadRefusedError",
    "add_sources",
    "list_sources",
    "open_session",
    "read_manifest",
    "reindex",
    "remove_source",
    "replace_source",
]
