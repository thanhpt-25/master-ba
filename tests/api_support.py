"""Shared helpers for the dashboard API tests (kept out of conftest so tests can import them)."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from factories import intake_path
from masterba.api import Settings, create_app
from masterba.api.deps import AppState
from masterba.llm import LLM, FakeLLM, LLMResult
from masterba.llm.base import T

REPO = Path(__file__).parents[1]
PASSWORD = "correct horse battery"
ROLE_NAMES = {"viewer": "vera", "approver": "alice", "admin": "root"}

ClientFor = Callable[[str | None], TestClient]


class Script:
    """One scripted model shared by every role; tests append the answers a run will need."""

    def __init__(self) -> None:
        self.responses: list[BaseModel | Exception] = []
        self.llm = FakeLLM(self.responses)

    def add(self, *items: BaseModel | Exception) -> None:
        self.responses.extend(items)

    def factory(self, model: str) -> LLM:
        return self.llm


def make_app(root: Path, script: Script, frontend: Path) -> FastAPI:
    settings = Settings(root=root, llm_factory=script.factory, hash_iterations=1000)
    app = create_app(settings, frontend)
    users = app.state.masterba.users
    for role, name in ROLE_NAMES.items():
        users.add(name, role, PASSWORD)
    return app


def clients(app: FastAPI) -> ClientFor:
    def client_for(role: str | None) -> TestClient:
        client = TestClient(app, headers={"X-MasterBA": "1"})
        if role is not None:
            reply = client.post("/api/login", json={"name": ROLE_NAMES[role], "password": PASSWORD})
            assert reply.status_code == 200, reply.text
        return client

    return client_for


def wait_for(app: FastAPI, client: TestClient, job_id: str) -> dict[str, Any]:
    state: AppState = app.state.masterba
    state.jobs.wait(job_id)
    reply = client.get(f"/api/jobs/{job_id}")
    assert reply.status_code == 200
    job: dict[str, Any] = reply.json()
    return job


class BlockingLLM:
    """A model that waits until released, to keep a job running."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        self.started.set()
        self.release.wait(10)
        raise RuntimeError("released")


def new_project(admin: TestClient, body: dict[str, Any]) -> Any:
    """Create a project as the admin and share it with the viewer and approver (spec 23)."""
    created = admin.post("/api/projects", json=body)
    if created.status_code == 201:
        pid = body["project_id"]
        for role in ("viewer", "approver"):
            member = {"name": ROLE_NAMES[role], "role": role}
            shared = admin.post(f"/api/projects/{pid}/members", json=member)
            assert shared.status_code == 200, shared.text
    return created


# Spec 23/24 account tests: one project PRJ-001 with an uploaded intake.
LOGIN = "login_system.txt"
P = "/api/projects/PRJ-001"


def sign_in(app: FastAPI, name: str) -> TestClient:
    client = TestClient(app, headers={"X-MasterBA": "1"})
    assert client.post("/api/login", json={"name": name, "password": PASSWORD}).status_code == 200
    return client


def brd_project(client: ClientFor) -> tuple[TestClient, TestClient]:
    admin, approver = client("admin"), client("approver")
    assert new_project(admin, {"project_id": "PRJ-001", "document_language": "en"}).is_success
    upload = approver.post(f"{P}/intake", files={"file": (LOGIN, intake_path(LOGIN).read_bytes())})
    assert upload.status_code == 201
    return admin, approver


def start_brd(client: TestClient) -> Any:
    return client.post(f"{P}/stages/brd/run", json={"intake": LOGIN})
