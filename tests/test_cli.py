import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factories import bad_draft, draft_for, intake_path
from masterba.cli import main
from masterba.llm import LLM, FakeLLM

REPO = Path(__file__).parents[1]
LOGIN = "login_system.txt"


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(REPO / "templates", git_repo / "templates")
    return git_repo


def run_cli(root: Path, *args: str, llm: LLM | None = None, models: list[str] | None = None) -> int:
    def factory(model: str) -> LLM:
        if models is not None:
            models.append(model)
        assert llm is not None
        return llm

    return main(["--root", str(root), *args], llm_factory=factory)


def init(root: Path) -> None:
    assert run_cli(root, "init-project", "--project", "PRJ-001") == 0


def test_init_project_creates_the_project(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    assert json.loads(capsys.readouterr().out)["project_id"] == "PRJ-001"
    assert (root / "projects" / "PRJ-001" / "project.json").exists()


def test_run_brd_prints_a_json_summary(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    capsys.readouterr()
    args = ("run", "brd", "--project", "PRJ-001", "--input", str(intake_path(LOGIN)))
    assert run_cli(root, *args, llm=FakeLLM([draft_for(LOGIN)])) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["document_id"] == "DOC-BRD-0001"
    assert summary["requirement_ids"][0] == "REQ-0001"
    assert summary["open_questions"] == ["L8-L8: What response time counts as fast?"]
    assert Path(summary["xlsx"]).exists()


def test_model_option_beats_environment_beats_default(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init(root)
    base = ("run", "brd", "--project", "PRJ-001", "--input", str(intake_path(LOGIN)))
    seen: list[str] = []
    monkeypatch.delenv("MASTERBA_MODEL", raising=False)
    run_cli(root, *base, llm=FakeLLM([bad_draft(), bad_draft()]), models=seen)
    monkeypatch.setenv("MASTERBA_MODEL", "from-env")
    run_cli(root, *base, "--reuse-intake", llm=FakeLLM([bad_draft(), bad_draft()]), models=seen)
    run_cli(
        root, *base, "--reuse-intake", "--model", "from-flag",
        llm=FakeLLM([bad_draft(), bad_draft()]), models=seen,
    )  # fmt: skip
    assert seen == ["claude-sonnet-5-5", "from-env", "from-flag"]


def test_a_rejected_draft_exits_1_and_stores_no_requirements(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root)
    args = ("run", "brd", "--project", "PRJ-001", "--input", str(intake_path(LOGIN)))
    assert run_cli(root, *args, llm=FakeLLM([bad_draft(), bad_draft()])) == 1
    assert "draft rejected" in capsys.readouterr().err
    assert not (root / "projects" / "PRJ-001" / "requirements").exists()


def test_invalid_project_id_is_a_usage_error(root: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        run_cli(root, "init-project", "--project", "demo")
    assert caught.value.code == 2


def test_unknown_project_exits_1(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ("run", "brd", "--project", "PRJ-404", "--input", str(intake_path(LOGIN)))
    assert run_cli(root, *args, llm=FakeLLM([])) == 1
    assert "PRJ-404 does not exist" in capsys.readouterr().err


def test_missing_input_file_exits_1(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    args = ("run", "brd", "--project", "PRJ-001", "--input", str(root / "nope.txt"))
    assert run_cli(root, *args, llm=FakeLLM([])) == 1
    assert "nope.txt" in capsys.readouterr().err


def test_outside_a_git_work_tree_fails_before_doing_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(tmp_path, "init-project", "--project", "PRJ-001") == 1
    assert "not inside a git work tree" in capsys.readouterr().err
    assert not (tmp_path / "projects").exists()


def test_missing_api_key_exits_1_with_a_clear_message(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = ["--root", str(root), "run", "brd", "--project", "PRJ-001"]
    assert main([*args, "--input", str(intake_path(LOGIN))]) == 1
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_git_without_identity_is_reported(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "config", "--unset", "user.email"], cwd=root, check=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(root / "empty-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    assert run_cli(root, "init-project", "--project", "PRJ-001") == 1
    assert "user.email is not configured" in capsys.readouterr().err


def test_module_entry_point_prints_help() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "masterba", "--help"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0
    assert "init-project" in done.stdout
