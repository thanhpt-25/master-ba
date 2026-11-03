"""Minimal git wrapper: one business action equals one commit."""

import fcntl
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from masterba.trace_store.errors import GitError


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


@contextmanager
def _commit_lock(cwd: Path) -> Iterator[None]:
    """One add/commit at a time per repository, across threads and processes.

    A dashboard upload, a stage job and the CLI may commit at the same moment; without this
    two `git commit` runs collide on `.git/index.lock` and one action fails halfway.
    """
    found = _run(["rev-parse", "--git-common-dir"], cwd)
    if found.returncode != 0:
        raise GitError(found.stderr.strip() or f"{cwd} is not inside a git work tree")
    git_dir = Path(found.stdout.strip())
    lock = (git_dir if git_dir.is_absolute() else cwd / git_dir) / "masterba-commit.lock"
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def commit_paths(cwd: Path, paths: list[Path], message: str) -> bool:
    """Commit exactly `paths` as one commit; return False when nothing changed."""
    rels = [str(p) for p in paths]
    with _commit_lock(cwd):
        added = _run(["add", "--", *rels], cwd)
        if added.returncode != 0:
            raise GitError(added.stderr.strip())
        staged = _run(["diff", "--cached", "--quiet", "--", *rels], cwd)
        if staged.returncode == 0:
            return False
        if staged.returncode != 1:
            raise GitError(staged.stderr.strip())
        committed = _run(["commit", "-q", "-m", message, "--", *rels], cwd)
        if committed.returncode != 0:
            raise GitError(committed.stderr.strip() or committed.stdout.strip())
        return True


def ensure_ready(cwd: Path) -> None:
    """Fail early unless `cwd` is in a git work tree that can make commits."""
    inside = _run(["rev-parse", "--is-inside-work-tree"], cwd)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise GitError(f"{cwd} is not inside a git work tree")
    # The container sets the author through GIT_AUTHOR_* variables instead of git config.
    for key, variable in (("user.name", "GIT_AUTHOR_NAME"), ("user.email", "GIT_AUTHOR_EMAIL")):
        if not os.environ.get(variable) and not _run(["config", key], cwd).stdout.strip():
            raise GitError(f"git {key} is not configured")
