"""Usage, user administration, limits and project sharing (spec 23)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from masterba.accounts import Limits
from masterba.api.auth import User
from masterba.api.deps import (
    AppState,
    audit,
    current_user,
    project_role,
    require_role,
    state_of,
)
from masterba.api.schemas import LimitsBody, MemberBody, NewUserBody, OwnerBody, UserChangeBody

router = APIRouter(prefix="/api")
Me = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_role("admin"))]
ProjectViewer = Annotated[User, Depends(require_role("viewer"))]
ProjectAdmin = Annotated[User, Depends(require_role("admin"))]


def _limits(body: LimitsBody) -> Limits:
    return Limits(session=body.session, weekly=body.weekly)


def _usage_json(app: AppState, name: str) -> list[dict[str, Any]]:
    return [w.to_json() for w in app.usage.status(name)]


@router.get("/me/usage")
def my_usage(request: Request, user: Me) -> dict[str, Any]:
    app = state_of(request)
    return {
        "windows": _usage_json(app, user.name),
        "limits": app.usage.limits.effective(user.name).to_json(),
        "by_project": app.usage.by_project(user.name),
        "recent": app.usage.recent(user.name),
    }


# -- administration ------------------------------------------------------------


def _user_json(app: AppState, user: User) -> dict[str, Any]:
    override = app.usage.limits.override(user.name)
    return {
        "name": user.name,
        "role": user.role,
        "disabled": user.disabled,
        **app.users.details(user.name),
        "usage": _usage_json(app, user.name),
        "limits": app.usage.limits.effective(user.name).to_json(),
        "custom_limits": override is not None,
        "projects": sum(
            1 for pid in app.access.visible(user) if app.access.role_of(pid, user) == "admin"
        )
        if user.role != "admin"
        else None,
    }


def _known(app: AppState, name: str) -> User:
    found = app.users.get(name)
    if found is None:
        raise HTTPException(status_code=404, detail="no such user")
    return found


@router.get("/admin/users")
def list_users(request: Request, _: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    return {
        "users": [_user_json(app, u) for u in app.users.list()],
        "default_limits": app.usage.limits.default().to_json(),
    }


@router.post("/admin/users", status_code=201)
def add_user(request: Request, body: NewUserBody, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    user = app.users.add(body.name, body.role, body.password)
    audit(request, admin.name, "user.create", target=user.name, role=user.role)
    return _user_json(app, user)


@router.patch("/admin/users/{name}")
def change_user(
    request: Request, name: str, body: UserChangeBody, admin: AdminUser
) -> dict[str, Any]:
    app = state_of(request)
    user = _known(app, name)
    if body.role is not None and body.role != user.role:
        if name == admin.name and body.role != "admin":
            raise HTTPException(status_code=400, detail="you cannot take away your own admin role")
        previous = user.role
        user = app.users.set_role(name, body.role)
        audit(request, admin.name, "user.role", target=name, old=previous, new=body.role)
    if body.password is not None:
        app.users.set_password(name, body.password)
        if name != admin.name:
            user = app.users.end_sessions(name)  # spec 24 section 1
        audit(request, admin.name, "user.password", target=name)
    if "limits" in body.model_fields_set:
        limits = _limits(body.limits) if body.limits else None
        app.usage.limits.set_override(name, limits)
        audit(
            request,
            admin.name,
            "user.limits",
            target=name,
            limits=limits.to_json() if limits else "default",
        )
    return _user_json(app, user)


@router.post("/admin/users/{name}/reset-usage")
def reset_usage(request: Request, name: str, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    user = _known(app, name)
    app.usage.reset(name)
    audit(request, admin.name, "user.usage_reset", target=name)
    return _user_json(app, user)


@router.delete("/admin/users/{name}")
def remove_user(request: Request, name: str, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    _known(app, name)
    if name == admin.name:
        raise HTTPException(status_code=400, detail="you cannot remove yourself")
    app.access.forget_user(name, admin.name)
    app.usage.limits.set_override(name, None)
    app.users.remove(name)
    audit(request, admin.name, "user.remove", target=name, projects_to=admin.name)
    return {"removed": name, "projects_to": admin.name}


@router.get("/admin/limits")
def default_limits(request: Request, _: AdminUser) -> dict[str, Any]:
    return state_of(request).usage.limits.default().to_json()


@router.put("/admin/limits")
def set_default_limits(request: Request, body: LimitsBody, admin: AdminUser) -> dict[str, Any]:
    limits = state_of(request).usage.limits
    limits.set_default(_limits(body))
    audit(request, admin.name, "limits.default", limits=_limits(body).to_json())
    return limits.default().to_json()


# -- project sharing -------------------------------------------------------------


def _access_json(app: AppState, request: Request, pid: str, user: User) -> dict[str, Any]:
    entry = app.access.entry(pid) or {}
    members = entry.get("members", {})
    return {
        "project_id": pid,
        "owner": entry.get("owner"),
        "members": [{"name": n, "role": r} for n, r in sorted(members.items())],
        "my_role": project_role(request, user, pid),
    }


@router.get("/projects/{pid}/access")
def project_access(request: Request, pid: str, user: ProjectViewer) -> dict[str, Any]:
    return _access_json(state_of(request), request, pid, user)


@router.post("/projects/{pid}/members")
def add_member(request: Request, pid: str, body: MemberBody, user: ProjectAdmin) -> dict[str, Any]:
    app = state_of(request)
    app.access.set_member(pid, body.name, body.role)
    audit(request, user.name, "project.member_set", target=body.name, project=pid, role=body.role)
    return _access_json(app, request, pid, user)


@router.delete("/projects/{pid}/members/{name}")
def remove_member(request: Request, pid: str, name: str, user: ProjectAdmin) -> dict[str, Any]:
    app = state_of(request)
    app.access.remove_member(pid, name)
    audit(request, user.name, "project.member_remove", target=name, project=pid)
    return _access_json(app, request, pid, user)


@router.post("/projects/{pid}/owner")
def hand_over(request: Request, pid: str, body: OwnerBody, user: ProjectAdmin) -> dict[str, Any]:
    app = state_of(request)
    previous = (app.access.entry(pid) or {}).get("owner")
    app.access.set_owner(pid, body.name)
    audit(request, user.name, "project.owner", target=body.name, project=pid, previous=previous)
    return _access_json(app, request, pid, user)
