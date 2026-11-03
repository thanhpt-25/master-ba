from pathlib import Path

import pytest

from masterba.knowledge.vectors import InMemoryVectorStore, LanceVectorStore, VectorStore

_ROWS = [
    ("KB-0001#chunk.10", "KB-0001", [1.0, 0.0]),
    ("KB-0001#chunk.2", "KB-0001", [1.0, 0.0]),
    ("KB-0002#chunk.1", "KB-0002", [0.0, 1.0]),
]


def _check(store: VectorStore) -> None:
    store.add(_ROWS)
    assert store.search([1.0, 0.0], 3, None) == [
        "KB-0001#chunk.2",
        "KB-0001#chunk.10",
        "KB-0002#chunk.1",
    ]
    assert store.search([1.0, 0.0], 5, frozenset({"KB-0002"})) == ["KB-0002#chunk.1"]
    store.delete_source("KB-0001")
    assert store.refs() == frozenset({"KB-0002#chunk.1"})


def test_in_memory_store() -> None:
    _check(InMemoryVectorStore())


def test_lance_store(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    _check(LanceVectorStore(tmp_path / "vectors.lance"))
