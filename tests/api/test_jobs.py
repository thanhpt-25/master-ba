"""Dashboard jobs survive a server restart (spec 11 section 8)."""

import json
from pathlib import Path

from masterba.api.jobs import KEEP_PER_PROJECT, JobManager
from masterba.team import PROGRESS


def record(job_id: str, status: str, started: str) -> dict[str, object]:
    return {
        "id": job_id,
        "project_id": "PRJ-001",
        "kind": "stage:basic",
        "status": status,
        "started": started,
        "finished": None,
        "result": None,
        "error": None,
        "log": [],
    }


def test_a_finished_job_is_listed_again_after_a_restart(tmp_path: Path) -> None:
    def work() -> dict[str, str]:
        listener = PROGRESS.get()
        assert listener is not None
        listener("round 1 started")
        return {"status": "done"}

    jobs = JobManager(tmp_path)
    job = jobs.wait(jobs.submit("PRJ-001", "stage:srs", work).id)
    assert job.status == "done"
    [again] = JobManager(tmp_path).for_project("PRJ-001")
    assert (again.id, again.status, again.log) == (job.id, "done", ["round 1 started"])


def test_a_job_left_running_becomes_interrupted_and_does_not_block(tmp_path: Path) -> None:
    folder = tmp_path / "PRJ-001"
    folder.mkdir()
    running = record("abc", "running", "2026-10-31T10:00:00+00:00")
    (folder / "abc.json").write_text(json.dumps(running), encoding="utf-8")
    (folder / "broken.json").write_text("{", encoding="utf-8")
    jobs = JobManager(tmp_path)
    old = jobs.get("abc")
    assert old is not None
    assert (old.status, old.log) == ("interrupted", ["server restarted"])
    assert json.loads((folder / "abc.json").read_text("utf-8"))["status"] == "interrupted"
    assert jobs.running("PRJ-001") is None
    jobs.wait(jobs.submit("PRJ-001", "stage:basic", lambda: {"status": "done"}).id)


def test_only_the_newest_jobs_are_kept(tmp_path: Path) -> None:
    folder = tmp_path / "PRJ-001"
    folder.mkdir()
    for n in range(KEEP_PER_PROJECT + 3):
        started = f"2026-10-31T10:{n // 60:02d}:{n % 60:02d}+00:00"
        (folder / f"j{n:03d}.json").write_text(
            json.dumps(record(f"j{n:03d}", "done", started)), encoding="utf-8"
        )
    jobs = JobManager(tmp_path)
    assert len(jobs.for_project("PRJ-001")) == KEEP_PER_PROJECT
    assert not (folder / "j000.json").exists()
    assert (folder / f"j{KEEP_PER_PROJECT + 2:03d}.json").exists()
