"""Minimal git wrapper: one business action equals one commit."""

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
