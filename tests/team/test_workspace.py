import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from factories import draft_for, qa_pass
from masterba.agents import BrdDraft, QaIssue, QaReport
from masterba.llm import FakeLLM
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team import (
    PROGRESS,
    MessageType,
    RecordingLLM,
    SingleWriterError,
    TaskStatus,
    Team,
)
from masterba.trace_store import ProjectStore


def open_team(store: ProjectStore, max_rounds: int = 3, budget: int | None = None) -> Team:
    return Team.open(store, DocType.BRD, max_rounds, budget)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout


def test_open_creates_the_run_folder_with_a_local_only_transcripts_dir(
    store: ProjectStore,
) -> None:
    team = open_team(store)
    assert team.run_id == "RUN-0001"
    assert team.transcripts_dir.is_dir()
    assert (team.run_dir / ".gitignore").read_text() == "transcripts/\ncheckpoint.json\n"


def test_run_numbers_are_sequential_and_never_reused(store: ProjectStore) -> None:
    first = open_team(store)
    first.finish(TeamRunStatus.ESCALATED)
    assert open_team(store).run_id == "RUN-0002"
    assert open_team(store).run_id == "RUN-0003"


def test_finish_commits_summary_tasks_and_mailbox_in_one_commit(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    team = open_team(store)
    team.begin_round()
    task = team.add_task("Draft", "writer")
    team.set_status(task, TaskStatus.DONE)
    team.post("qa", "writer", MessageType.FEEDBACK, "DOC-BRD-0001#item.1", "Split this item.")
    team.charge(150)
    count = len(commit_log())
    run = team.finish(TeamRunStatus.DONE)
    assert commit_log()[0] == "run(PRJ-001): RUN-0001 done"
    assert len(commit_log()) == count + 1
    summary = json.loads((team.run_dir / "team-summary.json").read_text("utf-8"))
    assert summary == run.model_dump(mode="json")
    assert (summary["status"], summary["rounds"], summary["tokens_used"]) == ("done", 1, 150)
    tasks = json.loads((team.run_dir / "team-tasks.json").read_text("utf-8"))
    assert [(t["id"], t["owner"], t["status"]) for t in tasks] == [("T-01", "writer", "done")]
    mailbox = json.loads((team.run_dir / "mailbox.json").read_text("utf-8"))
    assert mailbox[0]["ref"] == "DOC-BRD-0001#item.1"
    assert mailbox[0]["round"] == 1


def test_transcripts_are_written_locally_but_never_committed(
    git_repo: Path, store: ProjectStore
) -> None:
    team = open_team(store)
    team.begin_round()
    team.write("writer", "draft", draft_for("login_system.txt"))
    team.log("note", "raw text")
    team.finish(TeamRunStatus.DONE)
    assert list(team.transcripts_dir.iterdir())
    tracked = git(git_repo, "ls-files").splitlines()
    assert not [path for path in tracked if "transcripts" in path]
    assert any(path.endswith("team-summary.json") for path in tracked)
    assert git(git_repo, "status", "--porcelain") == ""


def test_escalating_blocks_unfinished_tasks(store: ProjectStore) -> None:
    team = open_team(store)
    done = team.add_task("Draft", "writer")
    team.set_status(done, TaskStatus.DONE)
    team.set_status(team.add_task("Review", "qa", (done,)), TaskStatus.IN_PROGRESS)
    team.add_task("Revise", "writer")
    team.escalate(["max rounds reached (3)"])
    run = team.finish(TeamRunStatus.ESCALATED)
    assert [t.status for t in team.tasks] == [
        TaskStatus.DONE,
        TaskStatus.BLOCKED,
        TaskStatus.BLOCKED,
    ]
    assert run.escalations == ["max rounds reached (3)"]


def test_a_team_cannot_finish_done_with_open_tasks(store: ProjectStore) -> None:
    team = open_team(store)
    team.add_task("Draft", "writer")
    with pytest.raises(RuntimeError, match="unfinished tasks"):
        team.finish(TeamRunStatus.DONE)


def test_only_the_owner_may_write_an_artifact(store: ProjectStore) -> None:
    team = open_team(store)
    draft = draft_for("login_system.txt")
    with pytest.raises(SingleWriterError, match="owner: 'writer'"):
        team.write("qa", "draft", draft)
    with pytest.raises(SingleWriterError, match="owner: 'qa'"):
        team.write("writer", "qa-report", QaReport())
    with pytest.raises(SingleWriterError, match="None"):
        team.write("writer", "unknown", draft)
    team.write("writer", "draft", draft)
    team.write("qa", "qa-report", QaReport())


def test_budget_is_exhausted_at_or_above_the_limit_and_unlimited_by_default(
    store: ProjectStore,
) -> None:
    unlimited = open_team(store)
    unlimited.charge(10**9)
    assert not unlimited.budget_exhausted()
    limited = open_team(store, budget=100)
    limited.charge(99)
    assert not limited.budget_exhausted()
    limited.charge(1)
    assert limited.budget_exhausted()


def test_token_budget_warning_is_emitted_once_at_80_percent(store: ProjectStore) -> None:
    lines: list[str] = []
    token = PROGRESS.set(lines.append)
    try:
        team = open_team(store, budget=100)
        team.charge(80)
        team.charge(1)
        assert lines == ["token budget warning: 80/100 tokens used"]
    finally:
        PROGRESS.reset(token)


def test_messages_before_the_first_round_still_get_round_one(store: ProjectStore) -> None:
    message = open_team(store).post("gate", "writer", MessageType.FEEDBACK, None, "bad")
    assert message.round == 1


def test_recording_llm_logs_request_and_response(store: ProjectStore) -> None:
    team = open_team(store)
    team.begin_round()
    fake = FakeLLM([draft_for("login_system.txt")])
    result = RecordingLLM(fake, team).generate(
        system="SYS", user="USER", output=BrdDraft, tool_name="submit_brd"
    )
    assert result.value == draft_for("login_system.txt")
    names = sorted(p.name for p in team.transcripts_dir.iterdir())
    assert names == ["001-round-1-submit_brd-request.txt", "002-round-1-submit_brd-response.txt"]
    request = (team.transcripts_dir / names[0]).read_text("utf-8")
    assert "SYS" in request
    assert "USER" in request


def test_qa_pass_helper_is_an_empty_report() -> None:
    assert qa_pass().passed


def test_design_and_test_drafts_have_their_own_owners(store: ProjectStore) -> None:
    team = open_team(store)
    draft = draft_for("login_system.txt")
    team.write("designer", "design-draft", draft)
    team.write("tester", "test-draft", draft)
    with pytest.raises(SingleWriterError):
        team.write("tester", "design-draft", draft)
    with pytest.raises(SingleWriterError):
        team.write("designer", "test-draft", draft)
    with pytest.raises(SingleWriterError):
        team.write("designer", "draft", draft)


def test_the_blocking_pairs_of_a_run_survive_a_resume(store: ProjectStore) -> None:
    team = open_team(store)
    raised = QaIssue(
        checklist_id="BRD-01",
        severity="blocking",
        ref="DOC-BRD-0001#item.1",
        message="Split it.",
        action_required="Split it.",
    )
    team.settle("draft", [raised])
    team.save_checkpoint({}, {})
    team.finish(TeamRunStatus.ESCALATED)

    reopened, _ = Team.reopen(store, DocType.BRD, team.run_id, 3, None)
    other = raised.model_copy(update={"ref": "DOC-BRD-0001#item.2"})
    settled, notes = reopened.settle("draft", [raised, other])

    assert [i.severity for i in settled] == ["blocking", "advisory"]
    assert notes == ["[BRD-01] DOC-BRD-0001#item.2: downgraded (new after the first review)"]


def test_the_confirmed_block_is_added_to_every_model_call(store: ProjectStore) -> None:
    team = open_team(store)
    team.facts = lambda: "<confirmed>\nDR-0001: x\n</confirmed>"
    fake = FakeLLM([draft_for("login_system.txt")])
    RecordingLLM(fake, team).generate(system="s", user="source", output=BrdDraft, tool_name="t")
    assert fake.calls[0].user == "source\n\n<confirmed>\nDR-0001: x\n</confirmed>"


def test_a_call_is_unchanged_when_there_are_no_facts(store: ProjectStore) -> None:
    team = open_team(store)
    fake = FakeLLM([draft_for("login_system.txt")])
    RecordingLLM(fake, team).generate(system="s", user="source", output=BrdDraft, tool_name="t")
    assert fake.calls[0].user == "source"
