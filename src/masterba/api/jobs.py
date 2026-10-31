"""Background jobs: one per project at a time, state kept in memory (spec 08 section 3.1)."""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from masterba.team import PROGRESS

logger = logging.getLogger(__name__)
MAX_LOG_LINES = 200
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
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._busy: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, project_id: str, kind: str, work: Work) -> Job:
        with self._lock:
            if project_id in self._busy:
                raise JobBusyError(f"a job is already running for {project_id}")
            self._busy.add(project_id)
            job = Job(id=uuid.uuid4().hex[:12], project_id=project_id, kind=kind)
            self._jobs[job.id] = job
        job.thread = threading.Thread(target=self._run, args=(job, work), daemon=True)
        job.thread.start()
        return job

    def _run(self, job: Job, work: Work) -> None:
        job.status = "running"
        token = PROGRESS.set(job.log.append)
        try:
            result = work()
            job.result = result
            job.status = "escalated" if result.get("status") == "escalated" else "done"
        except Exception as exc:  # the worker must never die silently; the error is reported
            logger.exception("job %s failed", job.id)
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            PROGRESS.reset(token)
            job.finished = _now()
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
