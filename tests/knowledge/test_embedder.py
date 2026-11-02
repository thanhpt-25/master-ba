"""Model setup with the download and loader patched (Requirements 6.2, 6.3, 6.6, 6.8)."""

from pathlib import Path
from typing import Any

import pytest

from masterba.knowledge import embedder as emb
from masterba.knowledge.embedder import (
    HashEmbedder,
    ModelSetupError,
    RagUnavailableError,
    setup_model,
)


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.setattr(emb, "rag_available", lambda: True)
    monkeypatch.setattr(emb, "_delete_partial", lambda name: None)
    return tmp_path


def test_setup_without_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emb, "rag_available", lambda: False)
    with pytest.raises(RagUnavailableError):
        setup_model("BAAI/bge-m3")


def test_empty_model_name(cache: Path) -> None:
    with pytest.raises(ModelSetupError) as info:
        setup_model("  ")
    assert info.value.cause == "model not found"


def test_already_present_downloads_nothing(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emb, "model_present", lambda name: True)

    def fail(*args: Any) -> Path:
        raise AssertionError("downloaded")

    monkeypatch.setattr(emb, "_run_download", fail)
    assert setup_model("m").downloaded is False


def test_success_writes_marker(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emb, "model_present", lambda name: False)
    monkeypatch.setattr(emb, "_run_download", lambda name, t: cache / "snapshots" / "abc123")
    monkeypatch.setattr(emb, "load_embedder", lambda name: HashEmbedder(name=name))
    result = setup_model("org/model")
    assert result.downloaded and result.cache_path == cache.resolve()
    assert '"revision": "abc123"' in emb.marker_path("org/model").read_text()


@pytest.mark.parametrize("cause", ["network unreachable", "model not found", "timeout"])
def test_failures_leave_no_marker(
    cache: Path, monkeypatch: pytest.MonkeyPatch, cause: emb.SetupCause
) -> None:
    marker = emb.marker_path("org/model")
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    deleted: list[str] = []
    monkeypatch.setattr(emb, "model_present", lambda name: False)
    monkeypatch.setattr(emb, "_delete_partial", deleted.append)

    def boom(name: str, timeout: int) -> Path:
        raise ModelSetupError(name, cause)

    monkeypatch.setattr(emb, "_run_download", boom)
    with pytest.raises(ModelSetupError) as info:
        setup_model("org/model")
    assert info.value.cause == cause
    assert not marker.exists() and deleted == ["org/model"]


def test_load_failure_after_download_cleans_up(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emb, "model_present", lambda name: False)
    monkeypatch.setattr(emb, "_run_download", lambda name, t: cache / "x")

    def bad_load(name: str) -> HashEmbedder:
        raise OSError("weights missing")

    monkeypatch.setattr(emb, "load_embedder", bad_load)
    with pytest.raises(ModelSetupError, match="weights missing"):
        setup_model("org/model")
    assert not emb.marker_path("org/model").exists()


def test_classify_and_config(monkeypatch: pytest.MonkeyPatch) -> None:
    assert emb._classify("RepositoryNotFoundError: 404") == "model not found"
    assert emb._classify("ConnectionError: refused") == "network unreachable"
    monkeypatch.setenv(emb.EMBED_MODEL_ENV, "intfloat/multilingual-e5-large")
    assert emb.configured_model() == "intfloat/multilingual-e5-large"
    monkeypatch.delenv(emb.EMBED_MODEL_ENV)
    assert emb.configured_model() == emb.DEFAULT_EMBED_MODEL


def test_model_absent_without_marker(cache: Path) -> None:
    assert emb.model_present("org/model") is False
    assert emb.model_present("") is False


def test_e5_prefixes() -> None:
    seen: list[list[str]] = []

    class Model:
        def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            seen.append(texts)
            return [[1.0] for _ in texts]

    e5 = emb.SentenceTransformerEmbedder("intfloat/multilingual-e5-large", Model())
    e5.embed_passages(["a"])
    e5.embed_query("b")
    emb.SentenceTransformerEmbedder("BAAI/bge-m3", Model()).embed_query("c")
    assert seen == [["passage: a"], ["query: b"], ["c"]]


def test_hash_embedder_is_deterministic_and_normalised() -> None:
    a, b = HashEmbedder().embed_passages(["受注登録", "受注登録"])
    assert a == b and abs(sum(x * x for x in a) - 1.0) < 1e-9
