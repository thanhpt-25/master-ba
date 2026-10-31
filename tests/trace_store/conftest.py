import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from factories import make_config
from masterba.trace_store import ProjectStore, create_project


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "init")
    return tmp_path


@pytest.fixture
def projects_root(git_repo: Path) -> Path:
    return git_repo / "projects"


@pytest.fixture
def store(projects_root: Path) -> ProjectStore:
    return create_project(projects_root, make_config())


@pytest.fixture
def commit_log(git_repo: Path) -> Callable[[], list[str]]:
    """Commit subjects, newest first."""

    def _log() -> list[str]:
        return _git(git_repo, "log", "--format=%s").splitlines()

    return _log
