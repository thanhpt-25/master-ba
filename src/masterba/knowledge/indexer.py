"""Index generations: build, activate, open and rebuild (spec 12, Requirement 5).

Each mutation builds `index/gen-####/` next to the active one and switches `index/CURRENT`
with `os.replace`, so a failed build leaves the previous generation usable.
"""

import datetime as dt
import hashlib
import os
import re
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from masterba.knowledge.embedder import (
    Embedder,
    configured_model,
    load_embedder,
    model_present,
    rag_available,
)
from masterba.knowledge.errors import IndexBuildError, KbError, KnowledgeUnavailableError
from masterba.knowledge.extract import EXTRACTOR_VERSION, ExtractionError, extract_source
from masterba.knowledge.keyword import KeywordIndex
from masterba.knowledge.manifest import load_manifest
from masterba.knowledge.paths import KbPaths, clean_staging, ensure_ignored, locked
from masterba.knowledge.vectors import LanceVectorStore, VectorStore
from masterba.models import KbManifest, KbSource, ReindexRecord, SourceIndexState
from masterba.trace_store import NotFoundError, ProjectStore

INDEX_FORMAT_VERSION = 1
FORMAT_VERSION = INDEX_FORMAT_VERSION * 1000 + EXTRACTOR_VERSION
_GEN = re.compile(r"^gen-(\d{4,})$")
Clock = Callable[[], dt.datetime]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class IndexIdentity:
    format_version: int
    embedder: str | None  # effective model name; None when vectors are unavailable


@dataclass(frozen=True)
class IndexBackend:
    """The replaceable parts of indexing; tests swap in a hash embedder and memory vectors."""

    probe: Callable[[], tuple[str | None, str | None]]  # (effective embedder name, notice)
    load: Callable[[str], Embedder]
    vectors: Callable[[Path, Path | None], VectorStore]  # (generation path, base path)


def default_probe() -> tuple[str | None, str | None]:
    in_container = bool(os.environ.get("MASTERBA_IN_CONTAINER"))
    if not rag_available():
        fix = (
            "rebuild the image with --build-arg EXTRAS=rag"
            if in_container
            else "run `uv sync --extra rag`"
        )
        return None, f"vector search is unavailable: the rag extra is not installed; {fix}"
    name = configured_model()
    if not model_present(name):
        fix = (
            "run `docker compose run --rm masterba kb setup`"
            if in_container
            else "run `masterba kb setup`"
        )
        return None, f"vector search is unavailable: model {name} is not set up; {fix}"
    return name, None


def lance_vectors(path: Path, base: Path | None) -> VectorStore:
    if base is not None and base.exists() and not path.exists():
        shutil.copytree(base, path)
    return LanceVectorStore(path)


DEFAULT_BACKEND = IndexBackend(default_probe, load_embedder, lance_vectors)


def expected_identity(backend: IndexBackend) -> IndexIdentity:
    return IndexIdentity(FORMAT_VERSION, backend.probe()[0])


@dataclass(frozen=True)
class BuildOutcome:
    generation: str
    record: ReindexRecord
    chunk_count: int
    keyword_only: bool
    notice: str | None


def current_generation(paths: KbPaths) -> str | None:
    try:
        name = (paths.index / "CURRENT").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return name if _GEN.match(name) and (paths.index / name).is_dir() else None


def read_record(paths: KbPaths, generation: str | None) -> ReindexRecord | None:
    if generation is None:
        return None
    try:
        return ReindexRecord.model_validate_json(
            (paths.index / generation / "record.json").read_bytes()
        )
    except (OSError, ValueError):
        return None


def activate(paths: KbPaths, generation: str) -> None:
    pointer = paths.index / "CURRENT.tmp"
    pointer.write_text(generation + "\n", encoding="utf-8")
    os.replace(pointer, paths.index / "CURRENT")


def discard(paths: KbPaths, generation: str) -> None:
    shutil.rmtree(paths.index / generation, ignore_errors=True)


def clean_generations(paths: KbPaths) -> None:
    """Delete old and unfinished generations; run at the start of every mutation."""
    current = current_generation(paths)
    if paths.index.is_dir():
        for child in paths.index.iterdir():
            if _GEN.match(child.name) and child.name != current:
                shutil.rmtree(child, ignore_errors=True)
    clean_staging(paths)


def _new_generation(paths: KbPaths) -> str:
    existing = list(paths.index.iterdir()) if paths.index.is_dir() else []
    numbers = [int(m.group(1)) for c in existing if (m := _GEN.match(c.name))]
    return f"gen-{max(numbers, default=0) + 1:04d}"


def _copy_sqlite(source: Path, target: Path) -> None:
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def _index_source(
    source: KbSource,
    path: Path,
    keyword: KeywordIndex,
    vectors: VectorStore | None,
    embedder: Embedder | None,
) -> SourceIndexState:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        chunks = extract_source(source.id, path, source.suffix)
    except ExtractionError as exc:
        return SourceIndexState(sha256=sha, status="failed", reason=str(exc), chunks=0)
    keyword.add(chunks, source.id)
    if vectors is not None and embedder is not None:
        embedded = embedder.embed_passages([c.index_text for c in chunks])
        vectors.add([(c.ref, source.id, v) for c, v in zip(chunks, embedded, strict=True)])
    return SourceIndexState(sha256=sha, status="indexed", chunks=len(chunks))


def build_generation(
    paths: KbPaths,
    manifest: KbManifest,
    *,
    base: str | None,
    add: Sequence[tuple[KbSource, Path]] = (),
    drop: Sequence[str] = (),
    backend: IndexBackend = DEFAULT_BACKEND,
    now: Clock = utc_now,
) -> BuildOutcome:
    """Build a new, inactive generation for `manifest` (the Manifest after the action).

    `add` gives each new or replaced source with the path to read it from. With a base whose
    identity matches, the base is copied and only `drop` and `add` change; otherwise every
    active source is extracted again. A single source that cannot be read is `failed`;
    any other error removes the generation and raises IndexBuildError.
    """
    name, notice = backend.probe()
    base_record = read_record(paths, base)
    incremental = base_record is not None and (
        IndexIdentity(base_record.format_version, base_record.embedder)
        == IndexIdentity(FORMAT_VERSION, name)
    )
    base_dir = paths.index / base if (incremental and base) else None
    overrides = {source.id: path for source, path in add}
    generation = _new_generation(paths)
    gen_dir = paths.index / generation
    keyword: KeywordIndex | None = None
    try:
        gen_dir.mkdir(parents=True)
        if base_dir is not None:
            _copy_sqlite(base_dir / "keyword.sqlite", gen_dir / "keyword.sqlite")
        keyword = KeywordIndex(gen_dir / "keyword.sqlite")
        embedder = backend.load(name) if name else None
        vectors = (
            backend.vectors(
                gen_dir / "vectors.lance", base_dir / "vectors.lance" if base_dir else None
            )
            if embedder
            else None
        )
        if base_record is not None and incremental:
            states = dict(base_record.sources)
            for source_id in {*drop, *overrides}:
                keyword.delete_source(source_id)
                if vectors is not None:
                    vectors.delete_source(source_id)
                states.pop(source_id, None)
            targets = list(add)
        else:
            states = {}
            active = [s for s in manifest.sources if not s.removed and s.id not in drop]
            targets = [(s, overrides.get(s.id, paths.source_file(s.id, s.suffix))) for s in active]
            targets = [(s, p) for s, p in targets if p.is_file()]  # missing files stay missing
        for source, path in targets:
            states[source.id] = _index_source(source, path, keyword, vectors, embedder)
        record = ReindexRecord(
            format_version=FORMAT_VERSION,
            embedder=name if embedder else None,
            built_at=now(),
            sources=dict(sorted(states.items())),
        )
        (gen_dir / "record.json").write_text(record.model_dump_json(indent=2) + "\n", "utf-8")
    except Exception as exc:
        if keyword is not None:
            keyword.close()
            keyword = None
        discard(paths, generation)
        raise IndexBuildError(f"building the index failed: {exc}") from exc
    finally:
        if keyword is not None:
            keyword.close()
    chunks = sum(state.chunks for state in record.sources.values())
    return BuildOutcome(generation, record, chunks, keyword_only=embedder is None, notice=notice)


@dataclass
class OpenIndex:
    generation: str
    keyword: KeywordIndex
    vectors: VectorStore | None
    record: ReindexRecord

    def close(self) -> None:
        self.keyword.close()


def open_index(paths: KbPaths, backend: IndexBackend = DEFAULT_BACKEND) -> OpenIndex:
    """Open the active generation for reading; vectors are None when they cannot be opened."""
    hint = "run `masterba kb reindex`"
    generation = current_generation(paths)
    record = read_record(paths, generation)
    keyword_path = paths.index / str(generation) / "keyword.sqlite"
    if generation is None or record is None or not keyword_path.is_file():
        raise KnowledgeUnavailableError(f"the knowledge base index is missing; {hint}")
    try:
        keyword = KeywordIndex(keyword_path)
        keyword.sources()
    except sqlite3.Error as exc:
        message = f"the knowledge base index is unreadable ({exc}); {hint}"
        raise KnowledgeUnavailableError(message) from exc
    vectors: VectorStore | None = None
    if record.embedder is not None:
        try:
            vectors = backend.vectors(paths.index / generation / "vectors.lance", None)
        except Exception:  # noqa: BLE001 - fall back to keyword-only search (Requirement 7.3)
            vectors = None
    return OpenIndex(generation, keyword, vectors, record)


def reindex(
    store: ProjectStore, *, backend: IndexBackend = DEFAULT_BACKEND, now: Clock = utc_now
) -> BuildOutcome:
    """Rebuild the whole index from the active Manifest entries (Requirements 5.1-5.7)."""
    if not (store.path / "project.json").is_file():
        raise NotFoundError(f"project {store.project_id} does not exist")
    paths = KbPaths(store.path / "knowledge")
    manifest = load_manifest(paths)
    missing = [
        s.id
        for s in manifest.sources
        if not s.removed and not paths.source_file(s.id, s.suffix).is_file()
    ]
    if missing:
        raise KbError("cannot reindex; these sources are missing: " + ", ".join(missing))
    with locked(paths):
        ensure_ignored(paths)
        clean_generations(paths)
        outcome = build_generation(paths, manifest, base=None, backend=backend, now=now)
        activate(paths, outcome.generation)
    return outcome
