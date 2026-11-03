"""KB_Store: add, replace, remove and list knowledge sources (spec 12, Requirements 1 and 3).

Every mutation holds the lock and writes in the order sources -> new generation -> Manifest
-> commit -> activate, so any failure before the commit restores the earlier state.
"""

import hashlib
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from masterba.knowledge.errors import (
    KbCommitError,
    KbError,
    UnknownSourceError,
    UploadRefusedError,
)
from masterba.knowledge.indexer import (
    DEFAULT_BACKEND,
    BuildOutcome,
    Clock,
    IndexBackend,
    IndexIdentity,
    activate,
    build_generation,
    clean_generations,
    current_generation,
    discard,
    expected_identity,
    read_record,
    utc_now,
)
from masterba.knowledge.manifest import load_manifest, manifest_bytes
from masterba.knowledge.paths import KbPaths, ensure_ignored, locked, staging_file
from masterba.knowledge.safety import SUPPORTED_TYPES, check_upload
from masterba.models import KbManifest, KbSource, ReindexRecord, SourceIndexState
from masterba.trace_store import NotFoundError, ProjectStore
from masterba.trace_store.git import commit_paths

MAX_FILES_PER_ADD = 100
MAX_SOURCE_NUMBER = 9999
Status = Literal["indexed", "failed", "stale", "missing"]
SourceSuffix = Literal[".md", ".txt", ".xlsx", ".docx", ".pdf"]


@dataclass(frozen=True)
class IncomingFile:
    name: str  # display name, checked by check_upload
    data: bytes


@dataclass(frozen=True)
class AddReport:
    added: tuple[KbSource, ...]
    skipped: tuple[tuple[str, str], ...]  # (file name, matching Source_Id or earlier name)
    refused: tuple[tuple[str, str], ...]  # (file name, reason)
    statuses: Mapping[str, SourceIndexState]
    keyword_only: bool
    notice: str | None


@dataclass(frozen=True)
class ReplaceReport:
    before: KbSource
    after: KbSource
    status: SourceIndexState
    notice: str | None


@dataclass(frozen=True)
class SourceView:
    source: KbSource
    status: Status
    reason: str | None


def kb_paths(store: ProjectStore) -> KbPaths:
    return KbPaths(store.path / "knowledge")


def _require_project(store: ProjectStore) -> None:
    if not (store.path / "project.json").is_file():
        raise NotFoundError(f"project {store.project_id} does not exist")


def read_manifest(store: ProjectStore) -> KbManifest:
    return load_manifest(kb_paths(store))


def next_source_number(manifest: KbManifest) -> int:
    """Highest number ever assigned (removed entries included) plus one."""
    return max((int(s.id[3:]) for s in manifest.sources), default=0) + 1


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _suffix(name: str) -> SourceSuffix:
    suffix = name[name.rfind(".") :].lower()
    assert suffix in SUPPORTED_TYPES  # check_upload already accepted the name
    return cast(SourceSuffix, suffix)


def source_status(
    paths: KbPaths, entry: KbSource, record: ReindexRecord | None, expected: IndexIdentity
) -> SourceView:
    """`missing` > `stale` > the recorded result (Requirements 3.3, 3.4, 5.12, 5.13)."""
    path = paths.source_file(entry.id, entry.suffix)
    if not path.is_file():
        return SourceView(entry, "missing", None)
    state = record.sources.get(entry.id) if record is not None else None
    if (
        state is None
        or record is None
        or _sha(path.read_bytes()) != entry.sha256
        or state.sha256 != entry.sha256
        or IndexIdentity(record.format_version, record.embedder) != expected
    ):
        return SourceView(entry, "stale", None)
    return SourceView(entry, state.status, state.reason)


def list_sources(store: ProjectStore, backend: IndexBackend = DEFAULT_BACKEND) -> list[SourceView]:
    """Active entries in ascending id order, with their status."""
    _require_project(store)
    paths = kb_paths(store)
    manifest = load_manifest(paths)
    record = read_record(paths, current_generation(paths))
    expected = expected_identity(backend)
    return [source_status(paths, s, record, expected) for s in manifest.sources if not s.removed]


def _unstage(store: ProjectStore, path: Path) -> None:
    subprocess.run(
        ["git", "reset", "-q", "--", str(path)], cwd=store.root, capture_output=True, check=False
    )


def _commit_manifest(
    store: ProjectStore, paths: KbPaths, manifest: KbManifest, subject: str
) -> None:
    """Write and commit the Manifest; on failure restore its earlier bytes and raise."""
    previous = paths.manifest.read_bytes() if paths.manifest.exists() else None
    try:
        paths.manifest.write_bytes(manifest_bytes(manifest))
        commit_paths(store.root, [paths.manifest], subject)
    except Exception as exc:
        if previous is None:
            paths.manifest.unlink(missing_ok=True)
        else:
            paths.manifest.write_bytes(previous)
        _unstage(store, paths.manifest)
        raise KbCommitError(f"committing knowledge/manifest.json failed: {exc}") from exc


def _accept(
    files: Sequence[IncomingFile], manifest: KbManifest
) -> tuple[list[IncomingFile], list[tuple[str, str]], list[tuple[str, str]]]:
    accepted: list[IncomingFile] = []
    skipped: list[tuple[str, str]] = []
    refused: list[tuple[str, str]] = []
    seen = {s.sha256: s.id for s in manifest.sources if not s.removed}
    for file in files:
        refusals = check_upload(file.name, file.data)
        if refusals:
            refused.append((file.name, refusals[0].message))
            continue
        sha = _sha(file.data)
        if sha in seen:
            skipped.append((file.name, seen[sha]))
            continue
        seen[sha] = file.name
        accepted.append(file)
    return accepted, skipped, refused


def add_sources(
    store: ProjectStore,
    files: Sequence[IncomingFile],
    added_by: str,
    *,
    backend: IndexBackend = DEFAULT_BACKEND,
    now: Clock = utc_now,
) -> AddReport:
    """Add files as new sources in one commit (Requirements 1.1-1.9)."""
    _require_project(store)
    if len(files) > MAX_FILES_PER_ADD:
        raise KbError(f"too many files: {len(files)}; at most {MAX_FILES_PER_ADD} per command")
    if not added_by.strip():
        raise KbError("the name of the acting user is empty")
    paths = kb_paths(store)
    with locked(paths):
        manifest = load_manifest(paths)
        accepted, skipped, refused = _accept(files, manifest)
        first = next_source_number(manifest)
        if first + len(accepted) - 1 > MAX_SOURCE_NUMBER:
            raise KbError("the knowledge base would pass KB-9999; no file was added")
        if not accepted:
            return AddReport((), tuple(skipped), tuple(refused), {}, False, None)
        ensure_ignored(paths)
        clean_generations(paths)
        stamp = now()
        new = [
            KbSource(
                id=f"KB-{first + i:04d}",
                file_name=file.name,
                suffix=_suffix(file.name),
                sha256=_sha(file.data),
                added_by=added_by,
                added_at=stamp,
            )
            for i, file in enumerate(accepted)
        ]
        copies: list[Path] = []
        outcome: BuildOutcome | None = None
        try:
            paths.sources.mkdir(parents=True, exist_ok=True)
            for source, file in zip(new, accepted, strict=True):
                target = paths.source_file(source.id, source.suffix)
                with target.open("xb") as handle:  # never overwrite an existing source file
                    copies.append(target)
                    handle.write(file.data)
            after = KbManifest(sources=[*manifest.sources, *new])
            outcome = build_generation(
                paths,
                after,
                base=current_generation(paths),
                add=[(s, paths.source_file(s.id, s.suffix)) for s in new],
                backend=backend,
                now=now,
            )
            ids = ", ".join(s.id for s in new)
            _commit_manifest(store, paths, after, f"kb({store.project_id}): add {ids}")
        except Exception as exc:
            for copy in copies:
                copy.unlink(missing_ok=True)
            if outcome is not None:
                discard(paths, outcome.generation)
            if isinstance(exc, KbError):
                raise
            raise KbCommitError(f"copying the files failed: {exc}") from exc
        activate(paths, outcome.generation)
    statuses = {s.id: outcome.record.sources[s.id] for s in new}
    return AddReport(
        tuple(new), tuple(skipped), tuple(refused), statuses, outcome.keyword_only, outcome.notice
    )


def _active_entry(manifest: KbManifest, source_id: str) -> KbSource:
    entry = next((s for s in manifest.sources if s.id == source_id), None)
    if entry is None:
        raise UnknownSourceError(source_id, "unknown")
    if entry.removed:
        raise UnknownSourceError(source_id, "already removed")
    return entry


def _with_entry(manifest: KbManifest, entry: KbSource) -> KbManifest:
    return KbManifest(sources=[entry if s.id == entry.id else s for s in manifest.sources])


def replace_source(
    store: ProjectStore,
    source_id: str,
    file: IncomingFile,
    added_by: str,
    *,
    backend: IndexBackend = DEFAULT_BACKEND,
    now: Clock = utc_now,
    before_commit: Callable[[KbSource, KbSource], None] | None = None,
) -> ReplaceReport:
    """Replace a source's file, keeping its id (Requirements 3.7-3.9).

    `before_commit(before, after)` runs once the new generation is built and before any
    source file or the Manifest changes; if it raises, nothing is changed.
    """
    _require_project(store)
    paths = kb_paths(store)
    with locked(paths):
        manifest = load_manifest(paths)
        before = _active_entry(manifest, source_id)
        refusals = check_upload(file.name, file.data)
        if refusals:
            raise UploadRefusedError(f"{file.name}: {refusals[0].message}")
        sha = _sha(file.data)
        twin = next((s.id for s in manifest.sources if not s.removed and s.sha256 == sha), None)
        if twin is not None:
            raise UploadRefusedError(f"{file.name}: the same content is already stored as {twin}")
        ensure_ignored(paths)
        clean_generations(paths)
        after = KbSource.model_validate(
            {
                **before.model_dump(),
                "file_name": file.name,
                "suffix": _suffix(file.name),
                "sha256": sha,
                "added_by": added_by,
                "added_at": now(),
            }
        )
        new_manifest = _with_entry(manifest, after)
        staged = staging_file(paths, source_id, after.suffix)
        backup = staging_file(paths, source_id, before.suffix + ".old")
        old_path = paths.source_file(source_id, before.suffix)
        new_path = paths.source_file(source_id, after.suffix)
        outcome: BuildOutcome | None = None
        moved = False
        try:
            paths.sources.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(file.data)
            outcome = build_generation(
                paths,
                new_manifest,
                base=current_generation(paths),
                add=[(after, staged)],
                backend=backend,
                now=now,
            )
            if before_commit is not None:
                before_commit(before, after)
            moved = True
            if old_path.exists():  # keep the old bytes until the commit succeeds
                shutil.move(old_path, backup)
            shutil.move(staged, new_path)
            subject = f"kb({store.project_id}): replace {source_id}"
            _commit_manifest(store, paths, new_manifest, subject)
        except Exception:
            if moved:
                new_path.unlink(missing_ok=True)
                if backup.exists():
                    shutil.move(backup, old_path)
            staged.unlink(missing_ok=True)
            if outcome is not None:
                discard(paths, outcome.generation)
            raise
        backup.unlink(missing_ok=True)
        activate(paths, outcome.generation)
    return ReplaceReport(before, after, outcome.record.sources[source_id], outcome.notice)


def remove_source(
    store: ProjectStore,
    source_id: str,
    *,
    backend: IndexBackend = DEFAULT_BACKEND,
    now: Clock = utc_now,
    before_commit: Callable[[KbSource], None] | None = None,
) -> KbSource:
    """Mark a source removed, drop its chunks and delete its file (Requirement 3.5)."""
    _require_project(store)
    paths = kb_paths(store)
    with locked(paths):
        manifest = load_manifest(paths)
        entry = _active_entry(manifest, source_id)
        ensure_ignored(paths)
        clean_generations(paths)
        removed = KbSource.model_validate(
            {**entry.model_dump(), "removed": True, "removed_at": now()}
        )
        new_manifest = _with_entry(manifest, removed)
        outcome = build_generation(
            paths,
            new_manifest,
            base=current_generation(paths),
            drop=[source_id],
            backend=backend,
            now=now,
        )
        try:
            if before_commit is not None:
                before_commit(entry)
            subject = f"kb({store.project_id}): remove {source_id}"
            _commit_manifest(store, paths, new_manifest, subject)
        except Exception:
            discard(paths, outcome.generation)
            raise
        activate(paths, outcome.generation)
        paths.source_file(source_id, entry.suffix).unlink(missing_ok=True)
    return removed
