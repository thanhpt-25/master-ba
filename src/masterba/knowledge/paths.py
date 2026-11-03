"""Knowledge base layout, the mutation lock and the ignore rules (spec 12, Requirement 1.6)."""

import fcntl
import subprocess
from collections.abc import Iterator
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


def clean_staging(paths: KbPaths) -> None:
    if paths.sources.is_dir():
        for leftover in paths.sources.glob(".staging-*"):
            leftover.unlink(missing_ok=True)
