import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from factories import build_chain, qa_pass
from masterba.change import PatchOp, RevisionPatch
from masterba.cli import main
from masterba.llm import LLM, FakeLLM
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team import Team
from masterba.trace_store import open_project

REPO = Path(__file__).parents[1]
BRD2 = "DOC-BRD-0001#item.2"
EMPTY = RevisionPatch(operations=[], summary="nothing to change")


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(REPO / "templates", git_repo / "templates")
    assert (
        main(["--root", str(git_repo), "init-project", "--project", "PRJ-001", "--language", "en"])
        == 0
    )
    build_chain(open_project(git_repo / "projects", "PRJ-001"), git_repo / "templates")
    return git_repo


def cli(root: Path, *args: str, llm: LLM | None = None) -> int:
    return main(["--root", str(root), *args], llm_factory=lambda model: llm or FakeLLM([]))


def run_json(
    root: Path, capsys: pytest.CaptureFixture[str], *args: str, llm: LLM | None = None
) -> dict[str, Any]:
    capsys.readouterr()
    assert cli(root, *args, llm=llm) == 0
    data: dict[str, Any] = json.loads(capsys.readouterr().out)
    return data


def propose(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    out = run_json(
        root, capsys, "dr", "new", "--project", "PRJ-001", "--trigger", "requirement_change",
        "--description", "Password reset by SMS too.", "--item", "REQ-0002",
    )  # fmt: skip
    return str(out["id"])


def test_the_whole_flow_through_the_cli(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dr_id = propose(root, capsys)
    assert dr_id == "DR-0001"
    listed = run_json(root, capsys, "dr", "list", "--project", "PRJ-001")
    assert [r["id"] for r in listed["decision_records"]] == [dr_id]

    approved = run_json(
        root, capsys, "dr", "approve", dr_id, "--project", "PRJ-001",
        "--approver", "Ms. Sato", "--decision", "Go ahead",
    )  # fmt: skip
    assert approved["dr"]["status"] == "approved"
    assert len(approved["impact"]["documents"]) == 7

    brd_patch = RevisionPatch(
        operations=[
            PatchOp(
                op="update",
                item_id=BRD2,
                fields={"description": "Reset by SMS or email."},
                reason="DR-0001",
            )
        ],
        summary="SMS",
    )
    llm = FakeLLM([brd_patch, qa_pass(), *[EMPTY] * 6])
    capsys.readouterr()
    assert cli(root, "dr", "propagate", dr_id, "--project", "PRJ-001", llm=llm) == 0
    propagated = json.loads(capsys.readouterr().out)
    assert propagated["status"] == "propagated"
    assert [d["outcome"] for d in propagated["documents"]] == ["revised"] + ["unchanged"] * 6
    shown = run_json(root, capsys, "dr", "show", dr_id, "--project", "PRJ-001")
    assert shown["dr"]["status"] == "propagated"
    assert shown["propagation"]["documents"]["DOC-BRD-0001"]["outcome"] == "revised"

    diff = run_json(root, capsys, "dr", "diff", dr_id, "--project", "PRJ-001")
    [doc] = diff["documents"]
    assert (doc["doc_id"], doc["old_version"], doc["new_version"]) == ("DOC-BRD-0001", 1, 2)
    assert doc["rows"][0]["classification"] == "structural_change"
    hidden = run_json(
        root, capsys, "dr", "diff", dr_id, "--project", "PRJ-001", "--structural-only"
    )
    assert hidden["documents"][0]["rows"]

    closed = run_json(root, capsys, "dr", "close", dr_id, "--project", "PRJ-001")
    assert closed["status"] == "closed"


def test_rejecting_through_the_cli(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dr_id = propose(root, capsys)
    out = run_json(
        root, capsys, "dr", "reject", dr_id, "--project", "PRJ-001",
        "--approver", "Ms. Sato", "--decision", "Not funded",
    )  # fmt: skip
    assert (out["status"], out["decision"]) == ("closed", "Not funded")


def test_a_dr_can_be_made_from_an_escalated_run(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = open_project(root / "projects", "PRJ-001")
    team = Team.open(store, DocType.BASIC_DESIGN, 3, None)
    team.escalate(["max rounds reached (3)"])
    team.finish(TeamRunStatus.ESCALATED)
    out = run_json(root, capsys, "dr", "from-run", "--project", "PRJ-001", "--run", team.run_id)
    assert out["trigger"] == "clarification"
    assert team.run_id in str(out["description"])


def test_errors_are_reported_and_exit_with_1(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dr_id = propose(root, capsys)
    capsys.readouterr()
    assert cli(root, "dr", "propagate", dr_id, "--project", "PRJ-001") == 1
    assert "only an approved DR can be propagated" in capsys.readouterr().err
    assert (
        cli(
            root,
            "dr",
            "approve",
            dr_id,
            "--project",
            "PRJ-001",
            "--approver",
            " ",
            "--decision",
            "x",
        )
        == 1
    )
    assert "approver and a decision" in capsys.readouterr().err
    assert (
        cli(root, "dr", "new", "--project", "PRJ-001", "--trigger", "defect", "--description", "d")
        == 1
    )
    assert "at least one --item" in capsys.readouterr().err
    assert cli(root, "dr", "show", "DR-0099", "--project", "PRJ-001") == 1
    assert "DR-0099 does not exist" in capsys.readouterr().err


def test_an_escalation_during_propagation_exits_with_3(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dr_id = propose(root, capsys)
    run_json(
        root, capsys, "dr", "approve", dr_id, "--project", "PRJ-001",
        "--approver", "Ms. Sato", "--decision", "Go ahead",
    )  # fmt: skip
    bad = RevisionPatch(
        operations=[PatchOp(op="update", item_id=BRD2, fields={"colour": "red"}, reason="DR-0001")],
        summary="bad",
    )
    capsys.readouterr()
    code = cli(root, "dr", "propagate", dr_id, "--project", "PRJ-001", llm=FakeLLM([bad] * 3))
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "approved"
    assert out["documents"][0]["outcome"] == "escalated"
