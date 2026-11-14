"""Background jobs: one per project at a time (spec 08 section 3.1).

Each job is also written to `<folder>/<project_id>/<job_id>.json`, so a restart keeps the list
(spec 11 section 8).
"""

import json
import logging
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from masterba.team import PROGRESS

logger = logging.getLogger(__name__)
MAX_LOG_LINES = 200
KEEP_PER_PROJECT = 50
_FIELDS = ("id", "project_id", "kind", "status", "started", "finished", "result", "error", "log")
Work = Callable[[], dict[str, Any]]


class JobBusyError(Exception):
    """A job is already running for the project."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    project_id: str
    kind: str
    status: str = "queued"
    started: str = field(default_factory=_now)
    finished: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)
    thread: threading.Thread | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "status": self.status,
            "started": self.started,
            "finished": self.finished,
            "result": self.result,
            "error": self.error,
            "log": self.log[-MAX_LOG_LINES:],
        }


class JobManager:
    def __init__(self, folder: Path | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._busy: set[str] = set()
        self._lock = threading.Lock()
        self._folder = folder
        if folder is not None:
            self._load(folder)

    def _load(self, folder: Path) -> None:
        """Read past jobs; a job the last server left queued or running is now interrupted."""
        for project in (p for p in folder.glob("*") if p.is_dir()):
            loaded = []
            for path in project.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    loaded.append((Job(**{k: data[k] for k in _FIELDS}), path))
                except (OSError, ValueError, KeyError, TypeError):
                    logger.warning("skipping unreadable job file %s", path)
            loaded.sort(key=lambda pair: (pair[0].started, pair[0].id), reverse=True)
            for _, path in loaded[KEEP_PER_PROJECT:]:
                path.unlink(missing_ok=True)
            for job, _ in loaded[:KEEP_PER_PROJECT]:
                if job.status in {"queued", "running"}:
                    job.status = "interrupted"
                    job.finished = job.finished or _now()
                    job.log.append("server restarted")
                    self._save(job)
                self._jobs[job.id] = job

    def _save(self, job: Job) -> None:
        if self._folder is None:
            return
        path = self._folder / job.project_id / f"{job.id}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(job.to_json(), ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            # The job record is a convenience; results already live in git, so the job goes on.
            logger.exception("could not save job %s", job.id)

    def _log(self, job: Job, line: str) -> None:
        job.log.append(line)
        self._save(job)

    def submit(self, project_id: str, kind: str, work: Work) -> Job:
        with self._lock:
            if project_id in self._busy:
                raise JobBusyError(f"a job is already running for {project_id}")
            self._busy.add(project_id)
            job = Job(id=uuid.uuid4().hex[:12], project_id=project_id, kind=kind)
            self._jobs[job.id] = job
        self._save(job)
        job.thread = threading.Thread(target=self._run, args=(job, work), daemon=True)
        job.thread.start()
        return job

    def _run(self, job: Job, work: Work) -> None:
        job.status = "running"
        self._save(job)
        token = PROGRESS.set(lambda line: self._log(job, line))
        try:
            result = work()
            job.result = result
            result_status = result.get("status")
            job.status = (
                result_status
                if isinstance(result_status, str)
                and result_status in {"escalated", "waiting_for_input"}
                else "done"
            )
        except Exception as exc:  # the worker must never die silently; the error is reported
            logger.exception("job %s failed", job.id)
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            PROGRESS.reset(token)
            job.finished = _now()
            self._save(job)
            with self._lock:
                self._busy.discard(job.project_id)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def for_project(self, project_id: str) -> list[Job]:
        jobs = [j for j in self._jobs.values() if j.project_id == project_id]
        return sorted(jobs, key=lambda j: (j.started, j.id), reverse=True)

    def running(self, project_id: str) -> Job | None:
        return next(
            (j for j in self.for_project(project_id) if j.status in {"queued", "running"}), None
        )

    def wait(self, job_id: str, timeout: float = 60.0) -> Job:
        """Block until the job ends (used by tests and shutdown)."""
        job = self._jobs[job_id]
        if job.thread is not None:
            job.thread.join(timeout)
        return job
