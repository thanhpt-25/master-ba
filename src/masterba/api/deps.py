"""Shared request dependencies: state, current user, role checks, project lookup."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request

from masterba.accounts import ProjectAccess, UsageLedger, UserMeter
from masterba.api.auth import RANK, LoginThrottle, SessionSigner, User, UserStore
from masterba.api.jobs import JobManager
from masterba.api.schemas import DOC_ID, DR_ID, PROJECT_ID, QUESTION_ID, RUN_ID, SOURCE_ID
from masterba.api.settings import Settings
from masterba.llm import LLM, MeteredLLM
from masterba.trace_store import NotFoundError, ProjectStore, open_project

COOKIE = "masterba_session"


@dataclass
class AppState:
    settings: Settings
    users: UserStore
    signer: SessionSigner
    throttle: LoginThrottle
    jobs: JobManager
    access: ProjectAccess
    usage: UsageLedger


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


def project_role(request: Request, user: User, pid: str) -> str:
    """The user's role in project `pid` (spec 23 section 2); 404 when they may not open it."""
    if not PROJECT_ID.match(pid):
        raise HTTPException(status_code=404, detail="no such project")
    role = state_of(request).access.role_of(pid, user)
    if role is None:
        raise HTTPException(status_code=404, detail="no such project")
    return role


def require_role(minimum: str) -> Callable[[Request], User]:
    """Under `/api/projects/{pid}` the project role counts, elsewhere the global role."""

    def dependency(request: Request) -> User:
        user = current_user(request)
        pid = request.path_params.get("pid")
        role = project_role(request, user, pid) if isinstance(pid, str) else user.role
        if RANK[role] < RANK[minimum]:
            raise HTTPException(status_code=403, detail="your role may not do this")
        return user

    return dependency


def project_store(request: Request, pid: str) -> ProjectStore:
    project_role(request, current_user(request), pid)
    try:
        return open_project(state_of(request).settings.projects, pid)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such project") from exc


def limit_detail(app: AppState, user: User) -> dict[str, object] | None:
    """The 429 detail when a usage window of `user` is used up (spec 23 section 7)."""
    reached = app.usage.blocking(user.name)
    if reached is None:
        return None
    return {"code": "usage_limit", "message": reached.message(), **reached.to_json()}


def require_quota(app: AppState, user: User) -> None:
    detail = limit_detail(app, user)
    if detail is not None:
        raise HTTPException(status_code=429, detail=detail)


def metered(app: AppState, user: User, project_id: str, kind: str) -> Callable[[str], LLM]:
    """An LLM factory whose models check and charge `user` on every call (spec 23 section 5)."""
    meter = UserMeter(app.usage, user.name, project_id, kind)

    def factory(model: str) -> LLM:
        return MeteredLLM(app.settings.llm_factory(model), meter, model)

    return factory


def checked(pattern_name: str, value: str) -> str:
    """Validate an id taken from a path or query before it touches the file system."""
    pattern = {
        "doc": DOC_ID,
        "dr": DR_ID,
        "run": RUN_ID,
        "question": QUESTION_ID,
        "source": SOURCE_ID,
    }[pattern_name]
    if not pattern.match(value):
        raise HTTPException(status_code=404, detail=f"no such {pattern_name}")
    return value
