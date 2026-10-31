"""Minimal git wrapper: one business action equals one commit."""

import os
import subprocess
from pathlib import Path

from masterba.trace_store.errors import GitError


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def commit_paths(cwd: Path, paths: list[Path], message: str) -> bool:
    """Commit exactly `paths` as one commit; return False when nothing changed."""
    rels = [str(p) for p in paths]
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
