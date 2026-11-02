"""Retrieval evaluation (spec 12, Requirement 8)."""

import socket
from pathlib import Path

import pytest

from kbhelpers import MemoryVectors, hash_backend
from masterba.knowledge.embedder import (
    HashEmbedder,
    configured_model,
    load_embedder,
    model_present,
    rag_available,
)
from masterba.knowledge.evaluation import (
    EVAL_DIR,
    MODES,
    build_eval_index,
    evaluate,
    format_table,
    load_questions,
)


def test_the_set_has_twenty_questions_per_language_with_existing_refs(tmp_path: Path) -> None:
    questions = load_questions()
    assert sum(q.lang == "ja" for q in questions) >= 20
    assert sum(q.lang == "en" for q in questions) >= 20
    vectors = MemoryVectors()
    backend = hash_backend(vectors)
    paths = build_eval_index(tmp_path, HashEmbedder(), backend=backend)
    results = evaluate(paths, questions, HashEmbedder(), backend=backend)
    assert {(r.lang, r.mode) for r in results} == {
        (lang, m) for lang in ("en", "ja") for m in MODES
    }
    table = format_table("hash-embedder", results)
    assert "hits/questions" in table and "/20" in table


def _real_model() -> str:
    if not rag_available():
        pytest.skip("the rag extra is not installed (uv sync --extra rag)")
    name = configured_model()
    if not model_present(name):
        pytest.skip(f"model {name} is not set up (masterba kb setup)")
    return name


@pytest.mark.rag_eval
def test_hybrid_is_at_least_as_good_as_each_mode(tmp_path: Path) -> None:
    embedder = load_embedder(_real_model())
    paths = build_eval_index(tmp_path, embedder)
    results = {(r.lang, r.mode): r for r in evaluate(paths, load_questions(), embedder)}
    print("\n" + format_table(embedder.name, list(results.values())))
    for lang in ("en", "ja"):
        hybrid = results[(lang, "hybrid")].value
        assert hybrid >= results[(lang, "keyword")].value
        assert hybrid >= results[(lang, "vector")].value


@pytest.mark.rag_eval
def test_cached_model_works_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name = _real_model()

    def refuse(self: socket.socket, address: object) -> None:
        raise AssertionError(f"network access with a cached model: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    embedder = load_embedder(name)
    paths = build_eval_index(tmp_path, embedder)
    assert EVAL_DIR.is_dir() and paths.index.is_dir()
    assert evaluate(paths, load_questions()[:2], embedder)
