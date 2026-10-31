"""Shared helpers for the dashboard API tests (kept out of conftest so tests can import them)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from masterba.api import Settings, create_app
from masterba.api.deps import AppState
from masterba.llm import LLM, FakeLLM

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
