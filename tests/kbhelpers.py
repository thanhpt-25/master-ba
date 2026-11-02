"""Offline index backends and helpers for knowledge base tests."""

import subprocess
from pathlib import Path

from masterba.knowledge.embedder import Embedder, HashEmbedder
from masterba.knowledge.indexer import IndexBackend
from masterba.knowledge.store import IncomingFile
from masterba.knowledge.vectors import InMemoryVectorStore, VectorStore


class MemoryVectors:
    """In-memory vector stores keyed by generation path; a base is copied like a directory."""

    def __init__(self) -> None:
        self.stores: dict[Path, InMemoryVectorStore] = {}

    def __call__(self, path: Path, base: Path | None) -> VectorStore:
        if path not in self.stores:
            store = InMemoryVectorStore()
            if base is not None and base in self.stores:
                store._rows = dict(self.stores[base]._rows)
            self.stores[path] = store
        return self.stores[path]


def hash_backend(vectors: MemoryVectors | None = None) -> IndexBackend:
    memory = vectors or MemoryVectors()

    def load(name: str) -> Embedder:
        return HashEmbedder(name=name)

    return IndexBackend(lambda: ("hash-embedder", None), load, memory)


def keyword_backend() -> IndexBackend:
    def load(name: str) -> Embedder:
        raise AssertionError("no embedder in keyword-only mode")

    return IndexBackend(
        lambda: (None, "vector search is unavailable: the rag extra is not installed"),
        load,
        MemoryVectors(),
    )


def md(name: str, text: str) -> IncomingFile:
    return IncomingFile(name, text.encode("utf-8"))


def head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def last_commit(repo: Path) -> tuple[str, list[str]]:
    out = subprocess.run(
        ["git", "show", "--name-only", "--format=%s", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return out[0], [line for line in out[1:] if line]
