import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI

from api_support import REPO, ClientFor, Script, clients, make_app
from masterba.trace_store import ProjectStore


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    folder = tmp_path / "frontend"
    folder.mkdir()
    (folder / "index.html").write_text("<!doctype html><title>MasterBA test</title>", "utf-8")
    return folder


@pytest.fixture
def empty_root(git_repo: Path) -> Path:
    shutil.copytree(
        REPO / "templates", git_repo / "templates", ignore=shutil.ignore_patterns("companies")
    )
    return git_repo


@pytest.fixture
def seeded_root(chain: ProjectStore) -> Path:
    """A git work tree holding the full demo chain of PRJ-001 and the templates."""
    root = chain.root.parent
    shutil.copytree(
        REPO / "templates", root / "templates", ignore=shutil.ignore_patterns("companies")
    )
    return root


@pytest.fixture
def empty_app(empty_root: Path, script: Script, frontend: Path) -> FastAPI:
    return make_app(empty_root, script, frontend)


@pytest.fixture
def seeded_app(seeded_root: Path, script: Script, frontend: Path) -> FastAPI:
    return make_app(seeded_root, script, frontend)


@pytest.fixture
def empty_client(empty_app: FastAPI) -> ClientFor:
    return clients(empty_app)


@pytest.fixture
def seeded_client(seeded_app: FastAPI) -> ClientFor:
    return clients(seeded_app)
