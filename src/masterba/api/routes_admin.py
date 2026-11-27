"""The admin console: dashboard, all projects, account life cycle, audit log, prices (spec 24)."""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from masterba.accounts import AuditFilter, PriceTable
from masterba.api.admin_dashboard import DAY, dashboard, project_rows
from masterba.api.auth import User
from masterba.api.deps import audit, require_role, state_of
from masterba.api.routes_accounts import _known, _user_json
from masterba.api.schemas import PricesBody

router = APIRouter(prefix="/api/admin")
AdminUser = Annotated[User, Depends(require_role("admin"))]
PERIODS = (7, 30, 90)


@router.get("/dashboard")
def admin_dashboard(
    request: Request,
    _: AdminUser,
    days: int = 30,
    tz: Annotated[int, Query(ge=-840, le=840)] = 0,
) -> dict[str, Any]:
    if days not in PERIODS:
        raise HTTPException(status_code=400, detail="days is 7, 30 or 90")
    return dashboard(state_of(request), days, tz)


@router.get("/projects")
def admin_projects(request: Request, _: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    return {
        "projects": project_rows(app),
        "users": [
            {"name": u.name, "role": u.role, "disabled": u.disabled} for u in app.users.list()
        ],
    }


# -- account life cycle -----------------------------------------------------------


def _not_yourself(name: str, admin: User, what: str) -> None:
    if name == admin.name:
        raise HTTPException(status_code=400, detail=f"you cannot {what} yourself")


@router.post("/users/{name}/disable")
def disable_user(request: Request, name: str, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    _known(app, name)
    _not_yourself(name, admin, "disable")
    user = app.users.set_disabled(name, True)
    audit(request, admin.name, "user.disable", target=name)
    return _user_json(app, user)


@router.post("/users/{name}/enable")
def enable_user(request: Request, name: str, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    _known(app, name)
    user = app.users.set_disabled(name, False)
    audit(request, admin.name, "user.enable", target=name)
    return _user_json(app, user)


@router.post("/users/{name}/signout")
def sign_out_user(request: Request, name: str, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    _known(app, name)
    _not_yourself(name, admin, "sign out")
    user = app.users.end_sessions(name)
    audit(request, admin.name, "user.signout", target=name)
    return _user_json(app, user)


# -- audit log ----------------------------------------------------------------------


def _filter(
    actor: str | None, action: str | None, target: str | None, days: int | None
) -> AuditFilter:
    since = time.time() - days * DAY if days else None
    return AuditFilter(
        actor=actor or None, action=action or None, target=target or None, since=since
    )


Text = Annotated[str | None, Query(max_length=100)]
Days = Annotated[int | None, Query(ge=1, le=3660)]


@router.get("/audit")
def audit_events(
    request: Request,
    _: AdminUser,
    actor: Text = None,
    action: Text = None,
    target: Text = None,
    days: Days = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    log = state_of(request).audit
    events, cursor = log.query(_filter(actor, action, target, days), before, limit)
    return {"events": events, "next": cursor}


@router.get("/audit.csv")
def audit_csv(
    request: Request,
    _: AdminUser,
    actor: Text = None,
    action: Text = None,
    target: Text = None,
    days: Days = None,
) -> Response:
    text = state_of(request).audit.csv(_filter(actor, action, target, days))
    return Response(
        "﻿" + text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="masterba-audit.csv"'},
    )


# -- prices -------------------------------------------------------------------------


@router.get("/prices")
def get_prices(request: Request, _: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    seen = sorted({m for m in app.usage.models() if m})
    return {**app.prices.get().to_json(), "seen_models": seen}


@router.put("/prices")
def set_prices(request: Request, body: PricesBody, admin: AdminUser) -> dict[str, Any]:
    app = state_of(request)
    try:
        table = PriceTable.from_json(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    app.prices.set(table)
    audit(request, admin.name, "prices.set", **table.to_json())
    return get_prices(request, admin)
