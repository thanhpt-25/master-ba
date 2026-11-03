"""Concurrent commits in one repository (review finding: `.git/index.lock` collisions)."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from masterba.trace_store.git import commit_paths

WRITERS = 8


def test_concurrent_commits_all_land(git_repo: Path) -> None:
    def write(n: int) -> bool:
        path = git_repo / f"file-{n}.txt"
        path.write_text(f"content {n}\n", encoding="utf-8")
        return commit_paths(git_repo, [path], f"test: commit {n}")

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(pool.map(write, range(WRITERS)))
    assert results == [True] * WRITERS
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert sorted(s for s in log if s.startswith("test: commit")) == sorted(
        f"test: commit {n}" for n in range(WRITERS)
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert status == ""  # the lock file lives in .git, not in the work tree
