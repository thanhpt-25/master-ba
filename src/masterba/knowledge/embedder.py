"""Optional local embedding model (spec 12, Requirement 6).

`sentence_transformers` and `huggingface_hub` come from the `rag` extra and are imported only
inside functions, so every module imports without the extra (Requirement 15.3).
"""

import datetime as dt
import functools
import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
import queue
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

# Chosen in spec 12 section 19: ties e5 on the evaluation set; no prefixes, 8,192-token inputs.
DEFAULT_EMBED_MODEL = "BAAI/bge-m3"
EMBED_MODEL_ENV = "MASTERBA_EMBED_MODEL"
SETUP_TIMEOUT_S = 1800
BATCH_SIZE = 32
# sentence-transformers needs none of these; multilingual-e5-large ships several GB of them.
SKIP_FILES = ("onnx/*", "openvino/*", "*.onnx", "*.h5", "*.msgpack", "*.ot", "imgs/*")
_RAG_PACKAGES = ("sentence_transformers", "lancedb", "huggingface_hub")

SetupCause = Literal["network unreachable", "model not found", "timeout"]


class Embedder(Protocol):
    name: str

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


EmbedderFactory = Callable[[], "Embedder | None"]


class RagUnavailableError(Exception):
    """The `rag` extra is not installed."""


class ModelSetupError(Exception):
    def __init__(self, model: str, cause: SetupCause, detail: str = "") -> None:
        extra = f" ({detail})" if detail else ""
        super().__init__(f"cannot set up model {model!r}: {cause}{extra}")
        self.model = model
        self.cause = cause


@dataclass(frozen=True)
class SetupResult:
    model: str
    cache_path: Path
    downloaded: bool


def rag_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in _RAG_PACKAGES)


def configured_model() -> str:
    return os.environ.get(EMBED_MODEL_ENV, "").strip() or DEFAULT_EMBED_MODEL


def hf_home() -> Path:
    default = Path.home() / ".cache" / "huggingface"
    return Path(os.environ.get("HF_HOME") or default).resolve()


def marker_path(name: str) -> Path:
    return hf_home() / "masterba" / (name.replace("/", "__") + ".ready.json")


def _offline_snapshot(name: str) -> Path | None:
    """The cached snapshot path, resolved without network access, or None."""
    from huggingface_hub import snapshot_download

    try:
        # Same skip list as the download, or a snapshot without ONNX files reads as incomplete.
        return Path(
            snapshot_download(name, local_files_only=True, ignore_patterns=list(SKIP_FILES))
        )
    except Exception:  # noqa: BLE001 - any failure means "not in the cache"
        return None


def model_present(name: str) -> bool:
    """True when `kb setup` finished for this model and its snapshot resolves offline."""
    if not name or not rag_available() or not marker_path(name).is_file():
        return False
    return _offline_snapshot(name) is not None


class SentenceTransformerEmbedder:
    def __init__(self, name: str, model: Any) -> None:
        self.name = name
        self._model = model
        # multilingual-e5 expects `query: ` / `passage: ` prefixes; bge-m3 needs none.
        self._e5 = "e5" in name.lower()

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts), batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(x) for x in v] for v in vectors]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" if self._e5 else t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}" if self._e5 else text])[0]


@functools.lru_cache(maxsize=2)
def load_embedder(name: str) -> Embedder:
    """Load a cached model with network access disabled.

    Kept per process: a writer call searches up to 32 segments, and loading a model
    such as bge-m3 from disk takes seconds and gigabytes each time.
    """
    if not rag_available():
        raise RagUnavailableError("the rag extra is not installed")
    os.environ["HF_HUB_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer

    return SentenceTransformerEmbedder(name, SentenceTransformer(name, local_files_only=True))


def default_factory() -> Embedder | None:
    """The configured embedder when the extra and the model are present, else None."""
    name = configured_model()
    if not model_present(name):
        return None
    return load_embedder(name)


def _classify(text: str) -> SetupCause:
    lowered = text.lower()
    missing = "repositorynotfound" in lowered or "404" in lowered or "not found" in lowered
    return "model not found" if missing else "network unreachable"


def _download_child(name: str, out: Any) -> None:
    try:
        from huggingface_hub import snapshot_download

        out.put(("ok", snapshot_download(name, ignore_patterns=list(SKIP_FILES))))
    except Exception as exc:  # noqa: BLE001 - reported to the parent process
        text = f"{type(exc).__name__}: {exc}".splitlines()[0]
        out.put((_classify(text), text))


def _run_download(name: str, timeout_s: int) -> Path:
    """Download in a spawned child process, killed after `timeout_s`."""
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    child = ctx.Process(target=_download_child, args=(name, out), daemon=True)
    child.start()
    try:
        status, value = out.get(timeout=timeout_s)
    except queue.Empty:
        child.kill()
        child.join()
        raise ModelSetupError(name, "timeout") from None
    child.join()
    if status != "ok":
        raise ModelSetupError(name, status, value)
    return Path(value)


def _delete_partial(name: str) -> None:
    from huggingface_hub import scan_cache_dir

    try:
        cache = scan_cache_dir()
    except Exception:  # noqa: BLE001 - no cache folder yet
        return
    revisions = [
        rev.commit_hash for repo in cache.repos if repo.repo_id == name for rev in repo.revisions
    ]
    if revisions:
        cache.delete_revisions(*revisions).execute()


def setup_model(name: str, timeout_s: int = SETUP_TIMEOUT_S) -> SetupResult:
    """Download the model once, verify an offline load, then write the completion marker.

    On any failure the marker and the partial snapshot are removed (Requirement 6.3).
    """
    name = name.strip()
    if not name:
        raise ModelSetupError(name, "model not found", "empty model name")
    if not rag_available():
        raise RagUnavailableError("the rag extra is not installed")
    if model_present(name):
        return SetupResult(name, hf_home(), downloaded=False)
    marker = marker_path(name)
    marker.unlink(missing_ok=True)
    try:
        snapshot = _run_download(name, timeout_s)
        load_embedder(name).embed_query("check")
    except Exception as exc:
        _delete_partial(name)
        marker.unlink(missing_ok=True)
        if isinstance(exc, ModelSetupError):
            raise
        raise ModelSetupError(name, "model not found", str(exc).splitlines()[0]) from exc
    marker.parent.mkdir(parents=True, exist_ok=True)
    date = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    marker.write_text(
        json.dumps({"model": name, "revision": snapshot.name, "date": date}), encoding="utf-8"
    )
    return SetupResult(name, hf_home(), downloaded=True)


class HashEmbedder:
    """Deterministic offline embedder for tests: hashed character bigrams, normalised."""

    def __init__(self, dimensions: int = 64, name: str = "hash-embedder") -> None:
        self.name = name
        self._dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for i in range(max(len(text) - 1, 1)):
            digest = hashlib.sha256(text[i : i + 2].encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self._dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
