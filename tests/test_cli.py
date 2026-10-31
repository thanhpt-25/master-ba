import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factories import (
    bad_draft,
    draft_for,
    intake_path,
    login_design_draft,
    login_detail_draft,
    login_srs_draft,
    login_test_draft,
    login_unit_draft,
    qa_block,
    qa_pass,
)
from masterba.agents import QaIssue, QaReport
from masterba.cli import main
from masterba.llm import LLM, FakeLLM

REPO = Path(__file__).parents[1]
LOGIN = "login_system.txt"
BRD_ARGS = ("run", "brd", "--project", "PRJ-001", "--input", str(intake_path(LOGIN)))


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(REPO / "templates", git_repo / "templates")
    return git_repo


def run_cli(
    root: Path,
    *args: str,
    llm: LLM | None = None,
    qa: LLM | None = None,
    models: list[str] | None = None,
) -> int:
    """Run the CLI; model `qa-model` maps to `qa`, every other model to `llm`."""

    def factory(model: str) -> LLM:
        if models is not None:
            models.append(model)
        chosen = qa if model == "qa-model" else llm
        assert chosen is not None
        return chosen

    return main(["--root", str(root), *args], llm_factory=factory)


def init(root: Path, language: str = "en", *extra: str) -> None:
    done = run_cli(root, "init-project", "--project", "PRJ-001", "--language", language, *extra)
    assert done == 0


def test_init_project_creates_the_project(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    assert json.loads(capsys.readouterr().out)["project_id"] == "PRJ-001"
    assert (root / "projects" / "PRJ-001" / "project.json").exists()


def test_run_brd_prints_a_json_summary(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    capsys.readouterr()
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), qa_pass()])) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["stage"], summary["status"], summary["run_id"]) == ("BRD", "done", "RUN-0001")
    assert summary["document_id"] == "DOC-BRD-0001"
    assert summary["requirement_ids"][0] == "REQ-0001"
    assert summary["open_questions"] == ["L8-L8: What response time counts as fast?"]
    assert (summary["rounds"], summary["issues_raised"], summary["escalations"]) == (1, 0, [])
    assert Path(summary["xlsx"]).exists()


def test_brd_then_srs_through_the_cli_with_a_separate_qa_model(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root)
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), qa_pass()])) == 0
    capsys.readouterr()
    writer, reviewer = FakeLLM([login_srs_draft()]), FakeLLM([qa_pass()])
    srs_args = ("run", "srs", "--project", "PRJ-001", "--qa-model", "qa-model")
    assert run_cli(root, *srs_args, llm=writer, qa=reviewer) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["stage"], summary["status"], summary["run_id"]) == ("SRS", "done", "RUN-0002")
    assert summary["document_id"] == "DOC-SRS-0001"
    assert [c.tool_name for c in writer.calls] == ["submit_srs"]
    assert [c.tool_name for c in reviewer.calls] == ["submit_qa_report"]


def test_advisory_issues_are_reported_but_do_not_block(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root)
    advisory = QaReport(
        issues=[QaIssue(checklist_id="BRD-04", severity="advisory", ref=None, message="Vague.")]
    )
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), advisory])) == 0
    capsys.readouterr()
    summary_run = json.loads(
        (root / "projects" / "PRJ-001" / "runs" / "RUN-0001" / "mailbox.json").read_text("utf-8")
    )
    assert summary_run[0]["body"] == "[BRD-04] document: Vague."


def test_an_escalated_run_exits_3_and_lists_the_reasons(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root, "en", "--team-max-rounds", "1")
    capsys.readouterr()
    blocked = qa_block("BRD-01", "DOC-BRD-0001#item.1", "Split it.")
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), blocked])) == 3
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "escalated"
    assert summary["escalations"][0] == "max rounds reached (1)"
    assert summary["document_id"] is None
    assert not (root / "projects" / "PRJ-001" / "requirements").exists()


def test_the_token_budget_option_stops_the_run(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root, "en", "--team-token-budget", "100")
    capsys.readouterr()
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), qa_pass()])) == 3
    assert "token budget exhausted (150/100)" in capsys.readouterr().out


def test_model_option_beats_environment_beats_default(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init(root, "en", "--team-max-rounds", "1")
    seen: list[str] = []
    monkeypatch.delenv("MASTERBA_MODEL", raising=False)
    run_cli(root, *BRD_ARGS, llm=FakeLLM([bad_draft()]), models=seen)
    monkeypatch.setenv("MASTERBA_MODEL", "from-env")
    run_cli(root, *BRD_ARGS, "--reuse-intake", llm=FakeLLM([bad_draft()]), models=seen)
    run_cli(
        root, *BRD_ARGS, "--reuse-intake", "--model", "from-flag",
        llm=FakeLLM([bad_draft()]), models=seen,
    )  # fmt: skip
    assert seen == ["claude-sonnet-5-5", "from-env", "from-flag"]


def test_invalid_project_id_is_a_usage_error(root: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        run_cli(root, "init-project", "--project", "demo")
    assert caught.value.code == 2


def test_unknown_project_exits_1(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ("run", "brd", "--project", "PRJ-404", "--input", str(intake_path(LOGIN)))
    assert run_cli(root, *args, llm=FakeLLM([])) == 1
    assert "PRJ-404 does not exist" in capsys.readouterr().err


def test_srs_without_a_brd_exits_1(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    assert run_cli(root, "run", "srs", "--project", "PRJ-001", llm=FakeLLM([])) == 1
    assert "run the brd stage first" in capsys.readouterr().err


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
    assert main(["--root", str(root), *BRD_ARGS]) == 1
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_git_without_identity_is_reported(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "config", "--unset", "user.email"], cwd=root, check=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(root / "empty-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
    assert run_cli(root, "init-project", "--project", "PRJ-001") == 1
    assert "user.email is not configured" in capsys.readouterr().err
    # A container passes the author as environment variables instead (spec 11 section 5.2).
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "masterba@localhost")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "masterba@localhost")
    assert run_cli(root, "init-project", "--project", "PRJ-001") == 0


def test_module_entry_point_prints_help() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "masterba", "--help"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0
    assert "init-project" in done.stdout


def test_init_project_stores_the_chosen_settings(root: Path) -> None:
    init(root, "en", "--team-max-rounds", "5", "--team-token-budget", "9000")
    config = json.loads((root / "projects" / "PRJ-001" / "project.json").read_text("utf-8"))
    assert config["document_language"] == "en"
    assert (config["team_max_rounds"], config["team_token_budget"]) == (5, 9000)


def test_init_project_sets_round_limits_per_stage(root: Path) -> None:
    init(root, "en", "--rounds", "basic=6", "--rounds", "SRS=4")
    config = json.loads((root / "projects" / "PRJ-001" / "project.json").read_text("utf-8"))
    assert config["team_max_rounds_by_stage"] == {"BASIC_DESIGN": 6, "SRS": 4}


@pytest.mark.parametrize("value", ["basic", "basic=0", "nope=3", "basic=x"])
def test_init_project_rejects_a_bad_round_limit(root: Path, value: str) -> None:
    with pytest.raises(SystemExit):
        run_cli(root, "init-project", "--project", "PRJ-001", "--rounds", value)


def test_init_project_defaults_to_japanese(root: Path) -> None:
    assert run_cli(root, "init-project", "--project", "PRJ-001") == 0
    config = json.loads((root / "projects" / "PRJ-001" / "project.json").read_text("utf-8"))
    assert config["document_language"] == "ja"
    assert config["team_max_rounds"] == 3


def test_a_japanese_project_rejects_english_drafts_until_rounds_run_out(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root, "ja", "--team-max-rounds", "2")
    capsys.readouterr()
    llm = FakeLLM([draft_for(LOGIN), draft_for(LOGIN)])
    assert run_cli(root, *BRD_ARGS, llm=llm) == 3
    assert "no Japanese characters" in capsys.readouterr().out
    assert [c.tool_name for c in llm.calls] == ["submit_brd", "submit_brd"]


def test_basic_stage_through_the_cli_with_separate_models(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root)
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), qa_pass()])) == 0
    assert (
        run_cli(
            root, "run", "srs", "--project", "PRJ-001", llm=FakeLLM([login_srs_draft(), qa_pass()])
        )
        == 0
    )
    capsys.readouterr()
    designer = FakeLLM([login_design_draft()])
    tester = FakeLLM([login_test_draft()])
    reviewer = FakeLLM([qa_pass(), qa_pass()])

    def factory(model: str) -> LLM:
        return {"d": designer, "t": tester, "q": reviewer}[model]

    args = ["--root", str(root), "run", "basic", "--project", "PRJ-001"]
    code = main(
        [*args, "--model", "d", "--test-model", "t", "--qa-model", "q"], llm_factory=factory
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["stage"], summary["status"], summary["run_id"]) == (
        "BASIC_DESIGN",
        "done",
        "RUN-0003",
    )
    assert summary["document_ids"] == [
        "DOC-BASIC_DESIGN-0001",
        "DOC-TEST_IT-0001",
        "DOC-TEST_ST-0001",
    ]
    assert summary["exchanges"] == 0
    assert [c.tool_name for c in designer.calls] == ["submit_basic_design"]
    assert [c.tool_name for c in tester.calls] == ["submit_tests"]
    assert [c.tool_name for c in reviewer.calls] == ["submit_qa_report"] * 2


def test_basic_stage_without_an_srs_exits_1(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    assert run_cli(root, "run", "basic", "--project", "PRJ-001", llm=FakeLLM([])) == 1
    assert "run the srs stage first" in capsys.readouterr().err


def test_detail_stage_through_the_cli(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(root)
    assert run_cli(root, *BRD_ARGS, llm=FakeLLM([draft_for(LOGIN), qa_pass()])) == 0
    srs = FakeLLM([login_srs_draft(), qa_pass()])
    assert run_cli(root, "run", "srs", "--project", "PRJ-001", llm=srs) == 0
    basic = FakeLLM([login_design_draft(), login_test_draft(), qa_pass(), qa_pass()])
    assert run_cli(root, "run", "basic", "--project", "PRJ-001", llm=basic) == 0
    capsys.readouterr()
    detail = FakeLLM([login_detail_draft(), login_unit_draft(), qa_pass(), qa_pass()])
    assert run_cli(root, "run", "detail", "--project", "PRJ-001", llm=detail) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["stage"], summary["status"], summary["run_id"]) == (
        "DETAIL_DESIGN",
        "done",
        "RUN-0004",
    )
    assert summary["document_ids"] == ["DOC-DETAIL_DESIGN-0001", "DOC-TEST_UT-0001"]


def test_detail_stage_without_a_basic_design_exits_1(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(root)
    assert run_cli(root, "run", "detail", "--project", "PRJ-001", llm=FakeLLM([])) == 1
    assert "run the basic stage first" in capsys.readouterr().err
