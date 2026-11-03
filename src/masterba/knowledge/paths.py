"""Knowledge base layout, the mutation lock and the ignore rules (spec 12, Requirement 1.6)."""

import fcntl
import hashlib
import os
import re
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Knowledge base files that stay out of git; only knowledge/manifest.json is committed.
KNOWLEDGE_IGNORES = (
    "projects/*/knowledge/sources/",
    "projects/*/knowledge/index/",
    "projects/*/knowledge/.lock",
)


@dataclass(frozen=True)
class KbPaths:
    root: Path  # projects/<project_id>/knowledge

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def index(self) -> Path:
        return self.root / "index"

    @property
    def lock(self) -> Path:
        return self.root / ".lock"

    def source_file(self, source_id: str, suffix: str) -> Path:
        return self.sources / f"{source_id}{suffix}"


@contextmanager
def locked(paths: KbPaths) -> Iterator[None]:
    """Hold an exclusive flock on `knowledge/.lock` for a mutating action."""
    paths.root.mkdir(parents=True, exist_ok=True)
    with paths.lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def ensure_ignored(paths: KbPaths) -> None:
    """Make sure sources, index and lock are git-ignored; otherwise add the patterns to the
    repository's local `info/exclude`, which needs no commit."""
    probes = [str(paths.sources / "probe"), str(paths.index / "probe"), str(paths.lock)]
    cwd = paths.root.parent
    paths.root.mkdir(parents=True, exist_ok=True)
    ignored = _git(cwd, "check-ignore", "--no-index", *probes).stdout.splitlines()
    if len(ignored) == len(probes):
        return
    top = _git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
    exclude = _git(cwd, "rev-parse", "--git-path", "info/exclude").stdout.strip()
    if not top or not exclude:
        return
    exclude_path = Path(exclude) if Path(exclude).is_absolute() else Path(cwd) / exclude
    # Patterns relative to the work tree top, for this project's knowledge folder.
    rel = paths.root.resolve().relative_to(Path(top).resolve()).as_posix()
    wanted = [f"/{rel}/sources/", f"/{rel}/index/", f"/{rel}/.lock"]
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    missing = [p for p in wanted if p not in existing.splitlines()]
    if missing:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        exclude_path.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")


def staging_file(paths: KbPaths, source_id: str, suffix: str) -> Path:
    """Where a replacement waits until its commit succeeds (inside the ignored `sources/`)."""
    return paths.sources / f".staging-{source_id}{suffix}"


_SOURCE_FILE = re.compile(r"^(KB-\d{4})(\.[a-z]+)$")
_BACKUP_FILE = re.compile(r"^\.staging-(KB-\d{4})(\.[a-z]+)\.old$")


def recover_interrupted(paths: KbPaths, active: Mapping[str, tuple[str, str]]) -> None:
    """Repair what an action killed before its commit left behind.

    `active` maps each active Source_Id to its (suffix, sha256) in the Manifest.

    - A replace keeps the old bytes as `.staging-KB-####<ext>.old` until its commit. When
      the backup still matches the Manifest's sha256 the commit never happened: the backup
      goes back in place (the new file may already sit there). Otherwise it is dropped.
    - A source file whose id is not active (an add that never committed) is deleted, so its
      id can be assigned again without `FileExistsError`.
    """
    if not paths.sources.is_dir():
        return
    for leftover in sorted(paths.sources.iterdir()):
        backup = _BACKUP_FILE.match(leftover.name)
        if backup is not None:
            source_id, suffix = backup.groups()
            sha = hashlib.sha256(leftover.read_bytes()).hexdigest()
            if active.get(source_id) == (suffix, sha):
                os.replace(leftover, paths.source_file(source_id, suffix))
            else:
                leftover.unlink(missing_ok=True)
        elif leftover.name.startswith(".staging-"):
            leftover.unlink(missing_ok=True)
    for leftover in paths.sources.iterdir():
        source = _SOURCE_FILE.match(leftover.name)
        entry = active.get(source.group(1)) if source is not None else None
        if source is not None and (entry is None or entry[0] != source.group(2)):
            leftover.unlink(missing_ok=True)
