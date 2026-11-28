"""Spec 29 section 6.2: template sets and a project's set from the command line."""

import json
import shutil
from pathlib import Path

import pytest

from masterba.api.auth import UserStore
from masterba.cli import main
from masterba.llm import FakeLLM
from masterba.trace_store import ProjectStore, get_config

REPO = Path(__file__).parents[1]


@pytest.fixture
def root(chain: ProjectStore) -> Path:
    work = chain.root.parent
    shutil.copytree(REPO / "templates", work / "templates")
    users = UserStore(work / ".masterba" / "users.json", 1000)
    users.add("root", "admin", "a long password")
    users.add("anna", "approver", "a long password")
    return work


def cli(root: Path, *args: str) -> int:
    return main(["--root", str(root), *args], llm_factory=lambda model: FakeLLM([]))


def out(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    data: dict[str, object] = json.loads(capsys.readouterr().out)
    return data


def test_sets_share_and_clone(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(root, "template", "sets") == 0
    sets = {s["id"]: s for s in out(capsys)["sets"]}  # type: ignore[attr-defined]
    assert sets["sample-sier"]["visibility"] == "public"
    assert sets["default"]["owner"] is None

    assert cli(root, "template", "clone", "--company", "sample-sier", "--to", "anna-co",
               "--owner", "anna") == 0  # fmt: skip
    assert out(capsys)["owner"] == "anna"
    assert cli(root, "template", "share", "--company", "anna-co", "--visibility", "shared",
               "--users", "root") == 0  # fmt: skip
    assert out(capsys)["shared_with"] == ["root"]
    assert cli(root, "template", "share", "--company", "ghost", "--visibility", "public") == 1
    assert cli(root, "template", "clone", "--company", "anna-co", "--to", "x",
               "--owner", "nobody") == 1  # fmt: skip


def test_a_project_switches_only_with_consent(
    root: Path, chain: ProjectStore, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ("project", "set-template", "--project", "PRJ-001", "--template", "sample-sier")
    assert cli(root, "project", "coverage", "--project", "PRJ-001", "--template", "default") == 0
    assert out(capsys)["gaps"] == 0

    assert cli(root, *base) == 1
    assert out(capsys)["coverage"]["gaps"] > 0  # type: ignore[index]
    assert get_config(chain).company_id == "default"

    assert cli(root, *base, "--accept-gaps") == 0
    assert out(capsys)["rendered"]
    assert get_config(chain).company_id == "sample-sier"
    assert cli(root, "project", "reissue", "--project", "PRJ-001", "--doc", "DOC-BRD-0001") == 0
    assert out(capsys)["set"] == "sample-sier"
