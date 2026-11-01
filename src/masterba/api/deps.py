"""Shared request dependencies: state, current user, role checks, project lookup."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request

from masterba.api.auth import RANK, LoginThrottle, SessionSigner, User, UserStore
from masterba.api.jobs import JobManager
from masterba.api.schemas import DOC_ID, DR_ID, PROJECT_ID, QUESTION_ID, RUN_ID
from masterba.api.settings import Settings
from masterba.trace_store import NotFoundError, ProjectStore, open_project

COOKIE = "masterba_session"


@dataclass
class AppState:
    settings: Settings
    users: UserStore
    signer: SessionSigner
    throttle: LoginThrottle
    jobs: JobManager


def state_of(request: Request) -> AppState:
    app_state: AppState = request.app.state.masterba
    return app_state


def current_user(request: Request) -> User:
    """The signed-in user; the role is read from the users file on every request."""
    app = state_of(request)
    token = request.cookies.get(COOKIE)
    name = app.signer.verify(token) if token else None
    user = app.users.get(name) if name else None
    if user is None:
        raise HTTPException(status_code=401, detail="sign in first")
    return user


def require_role(minimum: str) -> Callable[[Request], User]:
    def dependency(request: Request) -> User:
        user = current_user(request)
        if RANK[user.role] < RANK[minimum]:
            raise HTTPException(status_code=403, detail="your role may not do this")
        return user

    return dependency


def project_store(request: Request, pid: str) -> ProjectStore:
    if not PROJECT_ID.match(pid):
        raise HTTPException(status_code=404, detail="no such project")
    try:
        return open_project(state_of(request).settings.projects, pid)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such project") from exc


def checked(pattern_name: str, value: str) -> str:
    """Validate an id taken from a path or query before it touches the file system."""
    pattern = {"doc": DOC_ID, "dr": DR_ID, "run": RUN_ID, "question": QUESTION_ID}[pattern_name]
    if not pattern.match(value):
        raise HTTPException(status_code=404, detail=f"no such {pattern_name}")
    return value
