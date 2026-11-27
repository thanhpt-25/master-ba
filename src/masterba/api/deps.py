"""Shared request dependencies: state, current user, role checks, project lookup."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request

from masterba.accounts import AuditLog, PriceStore, ProjectAccess, UsageLedger, UserMeter
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
    audit: AuditLog
    prices: PriceStore


def state_of(request: Request) -> AppState:
    app_state: AppState = request.app.state.masterba
    return app_state


def current_user(request: Request) -> User:
    """The signed-in user; the role is read from the users file on every request.

    A disabled account and a cookie issued before the user's sessions were ended answer 401
    (spec 24 section 1).
    """
    app = state_of(request)
    token = request.cookies.get(COOKIE)
    session = app.signer.session(token) if token else None
    user = app.users.get(session.name) if session else None
    if session is None or user is None or user.disabled:
        raise HTTPException(status_code=401, detail="sign in first")
    if user.sessions_after is not None:
        issued = session.issued
        if issued is None:
            issued = session.expiry - app.settings.session_hours * 3600
        if issued < user.sessions_after:
            raise HTTPException(status_code=401, detail="sign in first")
    return user


def audit(
    request: Request,
    actor: str,
    action: str,
    *,
    target: str | None = None,
    project: str | None = None,
    **detail: object,
) -> None:
    """One audit row for an action taken through the API (spec 24 section 2)."""
    client = request.client.host if request.client else None
    state_of(request).audit.record(
        actor,
        action,
        target=target,
        project=project,
        detail=detail,
        source=f"api {client}" if client else "api",
    )


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


def limit_detail(
    app: AppState, user: User, context: str = "auto_propagation"
) -> dict[str, object] | None:
    """The 429 detail when a usage window of `user` is used up (spec 23 section 7).

    A reached limit is also recorded as a limit event under `context` (spec 24 section 3).
    """
    reached = app.usage.blocking(user.name)
    if reached is None:
        return None
    app.usage.limit_hit(user.name, reached, context)
    return {"code": "usage_limit", "message": reached.message(), **reached.to_json()}


def require_quota(app: AppState, user: User) -> None:
    detail = limit_detail(app, user, "job_start")
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
