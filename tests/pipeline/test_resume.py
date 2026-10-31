"""Resume after escalation (spec 11 section 3)."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from factories import (
    draft_for,
    incomplete_srs_draft,
    intake_path,
    login_design_draft,
    login_srs_draft,
    login_test_draft,
    make_config,
    qa_block,
    qa_pass,
)
from masterba.llm import FakeLLM
from masterba.models.enums import DocType, TeamRunStatus
from masterba.pipeline import (
    IT_DOC_ID,
    SRS_DOC_ID,
    Resume,
    run_basic_design,
    run_brd,
    run_srs,
)
from masterba.team import ResumeError, Team
from masterba.trace_store import DuplicateIdError, ProjectStore, create_project, get_document

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"
BLOCKED = qa_block("SRS-01", f"{SRS_DOC_ID}#item.1", "Two obligations.")


def with_brd(projects_root: Path, max_rounds: int = 1) -> ProjectStore:
    store = create_project(projects_root, make_config(max_rounds=max_rounds))
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    return store


def escalated_srs(store: ProjectStore) -> str:
    result = run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), BLOCKED]))
    assert result.status is TeamRunStatus.ESCALATED
    return result.run_id


def test_an_escalated_srs_run_resumes_from_its_last_draft(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = with_brd(projects_root)
    run_id = escalated_srs(store)
    llm = FakeLLM([login_srs_draft(), qa_pass()])
    result = run_srs(store, TEMPLATES, llm, resume=Resume(run_id))
    assert (result.run_id, result.status, result.rounds) == (run_id, TeamRunStatus.DONE, 2)
    assert "Two obligations." in llm.calls[0].user
    assert commit_log()[0] == f"run(PRJ-001): {run_id} done (resumed)"
    summary = json.loads((store.path / "runs" / run_id / "team-summary.json").read_text("utf-8"))
    assert (summary["resumed"], summary["status"]) == (1, "done")
    get_document(store, SRS_DOC_ID)


def test_the_checkpoint_stays_local(projects_root: Path, git_repo: Path) -> None:
    store = with_brd(projects_root)
    run_id = escalated_srs(store)
    checkpoint = json.loads(
        (store.path / "runs" / run_id / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["upstream"] == {"DOC-BRD-0001": 1}
    assert checkpoint["feedback"]["writer"] == [f"[SRS-01] {SRS_DOC_ID}#item.1: Two obligations."]
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert "checkpoint.json" not in tracked


def test_resume_adds_the_requested_rounds(projects_root: Path) -> None:
    store = with_brd(projects_root)
    run_id = escalated_srs(store)
    llm = FakeLLM([login_srs_draft(), BLOCKED, login_srs_draft(), BLOCKED])
    result = run_srs(store, TEMPLATES, llm, resume=Resume(run_id, rounds=2))
    assert (result.status, result.rounds) == (TeamRunStatus.ESCALATED, 3)
    assert result.escalations[0] == "max rounds reached (3)"


def test_resume_refuses_a_run_that_did_not_escalate(projects_root: Path) -> None:
    store = with_brd(projects_root)
    with pytest.raises(ResumeError, match="BRD stage"):
        run_srs(store, TEMPLATES, FakeLLM([]), resume=Resume("RUN-0001"))
    with pytest.raises(ResumeError, match="ended done"):
        Team.reopen(store, DocType.BRD, "RUN-0001", 1, None)


def test_resume_refuses_an_unknown_run_and_a_run_without_checkpoint(projects_root: Path) -> None:
    store = with_brd(projects_root)
    with pytest.raises(ResumeError, match="does not exist"):
        run_srs(store, TEMPLATES, FakeLLM([]), resume=Resume("RUN-0009"))
    failed = run_srs(store, TEMPLATES, FakeLLM([incomplete_srs_draft()]))
    with pytest.raises(ResumeError, match="no checkpoint"):
        run_srs(store, TEMPLATES, FakeLLM([]), resume=Resume(failed.run_id))


def test_resume_refuses_when_the_upstream_changed(projects_root: Path) -> None:
    store = with_brd(projects_root)
    run_id = escalated_srs(store)
    path = store.path / "runs" / run_id / "checkpoint.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "upstream": {"DOC-BRD-0001": 7}}), encoding="utf-8")
    with pytest.raises(ResumeError, match="changed since it ran"):
        run_srs(store, TEMPLATES, FakeLLM([]), resume=Resume(run_id))


def test_resume_refuses_when_the_document_already_exists(projects_root: Path) -> None:
    store = with_brd(projects_root)
    run_id = escalated_srs(store)
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    with pytest.raises(DuplicateIdError):
        run_srs(store, TEMPLATES, FakeLLM([]), resume=Resume(run_id))


def test_a_brd_run_resumes_with_the_same_intake(projects_root: Path) -> None:
    store = create_project(projects_root, make_config(max_rounds=1))
    blocked = qa_block("BRD-01", "DOC-BRD-0001#item.1", "Split it.")
    first = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), blocked]), intake_path(LOGIN))
    assert first.status is TeamRunStatus.ESCALATED
    llm = FakeLLM([draft_for(LOGIN), qa_pass()])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN), resume=Resume(first.run_id))
    assert (result.run_id, result.status) == (first.run_id, TeamRunStatus.DONE)


def test_a_basic_design_run_resumes_with_design_and_tests(projects_root: Path) -> None:
    store = with_brd(projects_root)
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    blocked = qa_block("TS-01", f"{IT_DOC_ID}#item.1", "Vague.")
    first = run_basic_design(
        store,
        TEMPLATES,
        FakeLLM([login_design_draft()]),
        tester_llm=FakeLLM([login_test_draft()]),
        qa_llm=FakeLLM([qa_pass(), blocked]),
    )
    assert first.status is TeamRunStatus.ESCALATED
    designer, tester = FakeLLM([]), FakeLLM([login_test_draft()])
    result = run_basic_design(
        store,
        TEMPLATES,
        designer,
        tester_llm=tester,
        qa_llm=FakeLLM([qa_pass(), qa_pass()]),
        resume=Resume(first.run_id),
    )
    assert (result.run_id, result.status) == (first.run_id, TeamRunStatus.DONE)
    assert designer.calls == []
    assert "Vague." in tester.calls[0].user
