"""`masterba review ...` (spec 15 section 7)."""

import json
import shutil
from pathlib import Path

import pytest

from factories import draft_for, intake_path, login_srs_draft, qa_pass
from masterba.change import PatchOp, RevisionPatch
from masterba.cli import main
from masterba.llm import LLM, FakeLLM

REPO = Path(__file__).parents[1]
LOGIN = "login_system.txt"
SRS = "DOC-SRS-0001"


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(
        REPO / "templates", git_repo / "templates", ignore=shutil.ignore_patterns("companies")
    )
    args = ["--root", str(git_repo), "init-project", "--project", "PRJ-001", "--language", "en"]
    assert main(args) == 0  # review gates are on by default
    return git_repo


def cli(root: Path, *args: str, llm: LLM | None = None) -> int:
    return main(["--root", str(root), *args], llm_factory=lambda model: llm or FakeLLM([]))


def out(capsys: pytest.CaptureFixture[str]) -> object:
    return json.loads(capsys.readouterr().out)


def test_init_project_turns_gates_on_unless_asked(root: Path, git_repo: Path) -> None:
    config = json.loads((root / "projects" / "PRJ-001" / "project.json").read_text("utf-8"))
    assert config["review_gates"] is True
    assert cli(root, "init-project", "--project", "PRJ-002", "--no-review-gates") == 0
    other = json.loads((root / "projects" / "PRJ-002" / "project.json").read_text("utf-8"))
    assert other["review_gates"] is False


def test_the_gate_then_approve_then_reject(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    brd = FakeLLM([draft_for(LOGIN), qa_pass()])
    assert (
        cli(root, "run", "brd", "--project", "PRJ-001", "--input", str(intake_path(LOGIN)), llm=brd)
        == 0
    )
    capsys.readouterr()
    assert cli(root, "run", "srs", "--project", "PRJ-001") == 1
    assert "approve the brd phase first" in capsys.readouterr().err
    assert cli(root, "review", "status", "--project", "PRJ-001") == 0
    phases = {p["stage"]: p["state"] for p in out(capsys)["phases"]}  # type: ignore[index]
    assert phases == {
        "brd": "in_review",
        "srs": "not_started",
        "basic": "not_started",
        "detail": "not_started",
    }

    assert (
        cli(root, "review", "approve", "--project", "PRJ-001", "--stage", "brd", "--by", "alice")
        == 0
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["decision"] == "approved"
    assert "customer question(s) are still open" in captured.err

    srs = FakeLLM([login_srs_draft(), qa_pass()])
    assert cli(root, "run", "srs", "--project", "PRJ-001", llm=srs) == 0
    capsys.readouterr()
    op = PatchOp(
        op="update",
        item_id=f"{SRS}#item.1",
        fields={"statement": "The system shall log in by e-mail."},
        reason="review",
    )
    reviser = FakeLLM([RevisionPatch(operations=[op], summary="fixed"), qa_pass()])
    code = cli(
        root,
        "review",
        "reject",
        "--project",
        "PRJ-001",
        "--stage",
        "srs",
        "--by",
        "bob",
        "--comment",
        f"{SRS}#item.1: Name the identifier.",
        llm=reviser,
    )
    assert code == 0
    result = out(capsys)
    assert result["review"]["decision"] == "rejected"  # type: ignore[index]
    assert result["revision"]["documents"][0]["version"] == 2  # type: ignore[index]

    assert cli(root, "review", "list", "--project", "PRJ-001") == 0
    assert [r["id"] for r in out(capsys)["reviews"]] == ["REV-0001", "REV-0002"]  # type: ignore[index]


def test_errors_exit_with_1(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        cli(root, "review", "approve", "--project", "PRJ-001", "--stage", "brd", "--by", "a") == 1
    )
    assert "no DOC-BRD-0001" in capsys.readouterr().err
