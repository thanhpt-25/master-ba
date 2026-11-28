import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

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


def test_export_writes_the_qa_and_change_registers(
    root: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    run_json(
        root, capsys, "question", "answer", "Q-0002", "--project", "PRJ-001",
        "--by", "alice", "--text", "Business days only.",
    )  # fmt: skip
    out = tmp_path / "qa.xlsx"
    exported = run_json(
        root, capsys, "export", "questions", "--project", "PRJ-001", "--out", str(out)
    )
    assert exported == {"register": "questions", "path": str(out)}
    ws = load_workbook(out)["QA管理表"]
    rows = list(ws.iter_rows(min_row=5, max_col=12, values_only=True))
    assert [r[1] for r in rows] == ["Q-0001", "Q-0002", "Q-0003"]
    answered = rows[1]
    assert answered[2] == "システム要件定義書" and answered[4] == "作成担当"
    assert answered[7:] == ("Business days only.", "alice", answered[9], "回答済", "DR-0001")
    assert rows[2][10] == "未回答"

    changes = tmp_path / "changes.xlsx"
    run_json(root, capsys, "export", "changes", "--project", "PRJ-001", "--out", str(changes))
    wb = load_workbook(changes)
    assert wb.sheetnames == ["変更管理台帳", "DR-0001"]
    entry = next(wb["変更管理台帳"].iter_rows(min_row=5, max_col=8, values_only=True))
    assert entry[1:4] == ("DR-0001", entry[2], "顧客回答反映")
    assert entry[5:7] == ("承認", "alice")
    form = {r[0]: r[1] for r in wb["DR-0001"].iter_rows(min_row=4, max_col=2, values_only=True)}
    assert form["変更管理番号"] == "DR-0001"
    assert form["判断"] == "Business days only."
    assert form["工数・納期への影響"] == "（手入力）"
    first = changes.read_bytes()
    run_json(root, capsys, "export", "changes", "--project", "PRJ-001", "--out", str(changes))
    assert changes.read_bytes() == first  # byte-deterministic
