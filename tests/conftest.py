import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import settings

from factories import build_chain, make_config
from masterba.trace_store import ProjectStore, create_project

# Property tests run at least 100 examples; no deadline because many of them touch the file system.
settings.register_profile("masterba", max_examples=100, deadline=None)
settings.load_profile("masterba")


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    # git 2.55 runs maintenance in the background after a commit; a test that deletes its
    # repo while that still writes objects fails with "Directory not empty".
    _git(tmp_path, "config", "maintenance.auto", "false")
    _git(tmp_path, "config", "gc.auto", "0")
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


TEMPLATES = Path(__file__).parents[1] / "templates"


def _init_repo(path: Path) -> None:
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "commit.gpgsign", "false")
    _git(path, "commit", "-q", "--allow-empty", "-m", "init")


@pytest.fixture(scope="session")
def chain_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A git repo holding the whole demo chain, built once per test session."""
    repo = tmp_path_factory.mktemp("chain")
    _init_repo(repo)
    store = create_project(repo / "projects", make_config())
    build_chain(store, TEMPLATES)
    return repo


@pytest.fixture
def chain(chain_source: Path, tmp_path: Path) -> ProjectStore:
    """A private copy of the demo chain: BRD, SRS, Basic Design, Detail Design and all tests."""
    target = tmp_path / "chain"
    shutil.copytree(chain_source, target)
    return ProjectStore(target / "projects", "PRJ-001")


@pytest.fixture
def chain_commits(chain: ProjectStore) -> Callable[[], list[str]]:
    """Commit subjects of the chain project's repository, newest first."""

    def _log() -> list[str]:
        return _git(chain.root, "log", "--format=%s").splitlines()

    return _log


# Measured with `pytest --durations` (spec 11 section 4): these modules build whole stage chains
# through git and hold most of the suite's time, so the quick CI job skips them.
SLOW_MODULES = (
    "tests/pipeline/",
    "tests/change/test_propagate.py",
    "tests/test_cli.py",
    "tests/test_cli_dr.py",
    "tests/api/test_flow.py",
    "tests/calibration/test_calibrate.py",
    "tests/calibration/test_sier_samples.py",
    "tests/api/test_permissions.py",
    "tests/api/test_security.py",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    root = Path(str(config.rootpath))
    for item in items:
        if Path(str(item.path)).relative_to(root).as_posix().startswith(SLOW_MODULES):
            item.add_marker(pytest.mark.slow)
