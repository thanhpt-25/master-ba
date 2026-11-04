import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from factories import build_chain
from masterba.cli import main
from masterba.llm import FakeLLM
from masterba.models import QuestionDraft
from masterba.models.enums import DocType
from masterba.questions import record_questions
from masterba.trace_store import open_project

REPO = Path(__file__).parents[1]


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(
        REPO / "templates", git_repo / "templates", ignore=shutil.ignore_patterns("companies")
    )
    assert (
        main(
            ["--root", str(git_repo), "init-project", "--project", "PRJ-001", "--language", "en"]
            + ["--no-review-gates"]  # the chain runs stages back to back
        )
        == 0
    )
    store = open_project(git_repo / "projects", "PRJ-001")
    build_chain(store, git_repo / "templates")
    record_questions(
        store,
        "RUN-0009",
        DocType.SRS,
        [
            QuestionDraft(refs=["REQ-0002"], text="Does the limit count business days?"),
            QuestionDraft(refs=[], text="Is deleting an employee in scope?"),
        ],
    )
    return git_repo


def cli(root: Path, *args: str) -> int:
    return main(["--root", str(root), *args], llm_factory=lambda model: FakeLLM([]))


def run_json(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    capsys.readouterr()
    assert cli(root, *args) == 0
    data: dict[str, Any] = json.loads(capsys.readouterr().out)
    return data


def test_list_show_answer_and_withdraw_through_the_cli(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = run_json(root, capsys, "question", "list", "--project", "PRJ-001")
    assert [q["id"] for q in listed["questions"]] == [
        "Q-0001",
        "Q-0002",
        "Q-0003",
    ]  # Q-0001 is the BRD draft's own

    shown = run_json(root, capsys, "question", "show", "Q-0002", "--project", "PRJ-001")
    assert shown["question"]["text"] == "Does the limit count business days?"

    answered = run_json(
        root, capsys, "question", "answer", "Q-0002", "--project", "PRJ-001",
        "--by", "alice", "--text", "Business days only.", "--source", "Tanaka, meeting",
    )  # fmt: skip
    assert (answered["question"]["status"], answered["question"]["dr_id"]) == (
        "answered",
        "DR-0001",
    )
    assert answered["dr"]["status"] == "approved"
    assert answered["dr"]["decision"] == "Business days only."

    withdrawn = run_json(root, capsys, "question", "withdraw", "Q-0003", "--project", "PRJ-001")
    assert withdrawn["question"]["status"] == "withdrawn"

    still_open = run_json(
        root, capsys, "question", "list", "--project", "PRJ-001", "--status", "open"
    )
    assert [q["id"] for q in still_open["questions"]] == ["Q-0001"]


def test_answering_twice_is_an_error_with_exit_code_one(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("question", "answer", "Q-0002", "--project", "PRJ-001", "--by", "a", "--text", "Yes.")
    assert cli(root, *args) == 0
    capsys.readouterr()
    assert cli(root, *args) == 1
    assert "only an open question" in capsys.readouterr().err
