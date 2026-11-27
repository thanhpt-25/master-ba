"""Figures for the admin console (spec 24 sections 5 and 6), all read from recorded data."""

import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from masterba.accounts.usage import iso
from masterba.api.deps import AppState
from masterba.api.jobs import Job
from masterba.api.routes_projects import stage_status
from masterba.api.schemas import STAGES
from masterba.models.enums import DrStatus, QuestionStatus
from masterba.trace_store import (
    ProjectStore,
    get_config,
    latest_documents,
    list_decision_records,
    list_questions,
)

DAY = 86400
JOB_ENDS = ("done", "escalated", "waiting_for_input", "failed", "interrupted")
ATTENTION = {"failed", "escalated", "interrupted", "waiting_for_input"}
TOP = 10
DOC_STATES = ("draft", "in_review", "approved", "superseded")


def _ts(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def period(days: int, tz_offset_minutes: int, now: float) -> tuple[float, list[str]]:
    """The start of the first local day of the period and every local date in it."""
    shift = -tz_offset_minutes * 60
    today = int((now + shift) // DAY) * DAY
    first = today - (days - 1) * DAY
    dates = [datetime.fromtimestamp(first + n * DAY, UTC).date().isoformat() for n in range(days)]
    return first - shift, dates


class Costing:
    """Cost of grouped call rows with the admin's price table, or None when no price is set."""

    def __init__(self, app: AppState) -> None:
        self.table = app.prices.get()

    def of(self, rows: Iterable[dict[str, Any]]) -> tuple[float | None, int]:
        total = 0.0
        unpriced = 0
        for row in rows:
            cost = self.table.cost(row["model"], row["input"], row["output"])
            if cost is None:
                unpriced += row["input"] + row["output"]
            else:
                total += cost
        return (None if self.table.empty else round(total, 4)), unpriced


def _sum(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    found = {"input": 0, "output": 0, "calls": 0}
    for row in rows:
        for key in found:
            found[key] += row[key]
    found["tokens"] = found["input"] + found["output"]
    return found


def _grouped(
    rows: list[dict[str, Any]], key: str, costing: Costing, limit: int | None = TOP
) -> list[dict[str, Any]]:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    out = []
    for name, members in groups.items():
        cost, unpriced = costing.of(members)
        out.append({key: name, **_sum(members), "cost": cost, "unpriced_tokens": unpriced})
    out.sort(key=lambda g: (-g["tokens"], str(g[key])))
    return out[:limit] if limit else out


def _kind(kind: str | None) -> str | None:
    """`propagate:DR-0003` counts as `propagate`; stage runs and rejections keep their stage."""
    if kind and kind.startswith("propagate:"):
        return "propagate"
    return kind


def _renamed(groups: list[dict[str, Any]], old: str, new: str) -> list[dict[str, Any]]:
    return [{new: g[old], **{k: v for k, v in g.items() if k != old}} for g in groups]


def _job_json(job: Job) -> dict[str, Any]:
    data = job.to_json()
    data.pop("log", None)
    data.pop("result", None)
    return data


def project_rows(app: AppState, since: float | None = None) -> list[dict[str, Any]]:
    """Every project with owner, members, stages, review state, tokens and last activity."""
    now = time.time()
    since = since if since is not None else now - 30 * DAY
    calls = app.usage.call_rows(since)
    by_project: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for row in calls:
        by_project[row["project"]].append(row)
    last_call = app.usage.last_call()
    out = []
    for pid in app.access.projects():
        store = ProjectStore(app.settings.projects, pid)
        config = get_config(store)
        entry = app.access.entry(pid) or {}
        running = app.jobs.running(pid)
        jobs = app.jobs.for_project(pid)
        stages = [
            stage_status(store, stage, running is not None and running.kind == f"stage:{stage}")
            for stage in STAGES
        ]
        documents: dict[str, int] = defaultdict(int)
        for doc, _ in latest_documents(store):
            documents[doc.status.value] += 1
        activity = [last_call.get(pid), _ts(jobs[0].started) if jobs else None]
        last = max((a for a in activity if a is not None), default=None)
        usage = _sum(by_project.get(pid, []))
        out.append(
            {
                "project_id": pid,
                "company_id": config.company_id,
                "document_language": config.document_language.value,
                "review_gates": config.review_gates,
                "owner": entry.get("owner"),
                "members": [
                    {"name": n, "role": r} for n, r in sorted(entry.get("members", {}).items())
                ],
                "stages": [
                    {
                        "stage": s["stage"],
                        "status": s["status"],
                        "review": s["review"],
                        "open_questions": s["open_questions"],
                    }
                    for s in stages
                ],
                "documents": dict(documents),
                "open_questions": sum(
                    1 for q in list_questions(store) if q.status is QuestionStatus.OPEN
                ),
                "open_drs": sum(
                    1 for d in list_decision_records(store) if d.status is not DrStatus.CLOSED
                ),
                "tokens_30d": usage["tokens"],
                "calls_30d": usage["calls"],
                "last_activity": iso(last),
                "job": _job_json(running) if running else None,
            }
        )
    return out


def _delivery(projects: list[dict[str, Any]]) -> dict[str, Any]:
    documents: dict[str, int] = defaultdict(int)
    stages: dict[str, dict[str, int]] = {s: defaultdict(int) for s in STAGES}
    waiting = []
    for project in projects:
        for status, n in project["documents"].items():
            documents[status] += n
        for stage in project["stages"]:
            stages[stage["stage"]][stage["status"]] += 1
            if stage["review"] == "in_review":
                waiting.append({"project_id": project["project_id"], "stage": stage["stage"]})
    return {
        "documents": {k: documents.get(k, 0) for k in DOC_STATES},
        "stages": {s: dict(v) for s, v in stages.items()},
        "waiting_reviews": waiting,
        "open_questions": sum(p["open_questions"] for p in projects),
        "open_drs": sum(p["open_drs"] for p in projects),
    }


def dashboard(app: AppState, days: int, tz_offset_minutes: int) -> dict[str, Any]:
    now = time.time()
    since, dates = period(days, tz_offset_minutes, now)
    previous_since = since - days * DAY
    rows = app.usage.call_rows(since, None, tz_offset_minutes)
    previous = app.usage.call_rows(previous_since, since, tz_offset_minutes)
    costing = Costing(app)

    # Tokens per day: every day present, zero when nothing was called.
    per_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_day[row["day"]].append(row)
    daily = []
    for date in dates:
        members = per_day.get(date, [])
        daily.append({"date": date, **_sum(members), "users": len({r["user"] for r in members})})

    totals = _sum(rows)
    cost, unpriced = costing.of(rows)
    previous_totals = _sum(previous)
    previous_cost, _ = costing.of(previous)

    users = app.users.list()
    signed_in = app.audit.actors("auth.login", since)
    callers = {r["user"] for r in rows}
    windows = {u.name: app.usage.status(u.name) for u in users}
    near = sorted(
        (
            {"name": name, **w.to_json()}
            for name, status in windows.items()
            for w in status
            if w.percent is not None and w.percent >= 80
        ),
        key=lambda w: -int(w["percent"] or 0),
    )
    at_limit = {w["name"] for w in near if w["reached"]}
    hits = app.usage.limit_events(since)

    jobs = [j for j in app.jobs.all() if (_ts(j.started) or 0) >= since]
    job_counts = {state: sum(1 for j in jobs if j.status == state) for state in JOB_ENDS}
    running = [j for j in app.jobs.all() if j.status in {"queued", "running"}]

    projects = project_rows(app, since)
    active_projects = {r["project"] for r in rows} | {j.project_id for j in jobs}
    events = app.audit.counts(since)
    recent_events, _ = app.audit.query(limit=8)

    return {
        "period": {"days": days, "since": iso(since), "until": iso(now)},
        "generated": iso(now),
        "kpis": {
            "users": {
                "total": len(users),
                "active": len(callers | signed_in),
                "disabled": sum(1 for u in users if u.disabled),
                "admins": sum(1 for u in users if u.role == "admin"),
            },
            "projects": {
                "total": len(projects),
                "active": len(active_projects & {p["project_id"] for p in projects}),
            },
            "tokens": {**totals, "previous": previous_totals["tokens"]},
            "cost": {
                "total": cost,
                "previous": previous_cost,
                "currency": costing.table.currency,
                "unpriced_tokens": unpriced,
                "priced": not costing.table.empty,
            },
            "jobs": {"total": len(jobs), **job_counts, "running": len(running)},
            "limits": {"hits": len(hits), "at_limit": len(at_limit), "near": len(near)},
            "sign_ins": {
                "ok": events.get("auth.login", 0),
                "failed": events.get("auth.login_failed", 0),
            },
        },
        "daily": daily,
        "top_users": _renamed(_grouped(rows, "user", costing), "user", "name"),
        "top_projects": _renamed(_grouped(rows, "project", costing), "project", "project_id"),
        "models": _grouped(rows, "model", costing, None),
        "kinds": _grouped([{**r, "kind": _kind(r["kind"])} for r in rows], "kind", costing, None),
        "delivery": _delivery(projects),
        "attention": {
            "jobs": [_job_json(j) for j in jobs if j.status in ATTENTION][:TOP],
            "running": [_job_json(j) for j in running],
            "near_limit": near[:TOP],
            "limit_hits": hits[:TOP],
        },
        "audit": recent_events,
    }
