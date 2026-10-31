"""Decision Record lifecycle: proposed -> approved -> propagated -> closed (spec 07 section 1)."""

import datetime as dt
import json
import re
from collections.abc import Callable, Sequence

from masterba.change.impact import Impact, analyse_impact, resolve_node
from masterba.models import DecisionRecord
from masterba.models.enums import DrStatus, DrTrigger
from masterba.models.ids import ITEM_REF_PATTERN, REQ_ID_PATTERN
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    add_decision_record,
    get_decision_record,
    known_nodes,
    list_decision_records,
    save_decision_record,
)

Clock = Callable[[], dt.date]
_REF = re.compile(ITEM_REF_PATTERN.strip("^$"))
_REQ = re.compile(REQ_ID_PATTERN.strip("^$"))


class LifecycleError(Exception):
    """An action is not allowed in the DR's current state or its input is incomplete."""


def next_dr_id(store: ProjectStore) -> str:
    numbers = [int(r.id.removeprefix("DR-")) for r in list_decision_records(store)]
    return f"DR-{max(numbers, default=0) + 1:04d}"


def new_dr(
    store: ProjectStore,
    trigger: DrTrigger,
    description: str,
    items: Sequence[str],
    today: Clock = dt.date.today,
) -> DecisionRecord:
    """Create a `proposed` DR whose affected documents come from impact analysis."""
    if not description.strip():
        raise LifecycleError("a DR needs a description")
    if not items and trigger is not DrTrigger.CLARIFICATION:
        raise LifecycleError("give at least one --item (only a clarification may have none)")
    resolved = list(dict.fromkeys(resolve_node(store, item) for item in items))
    bad = [r for r in resolved if r.startswith("DOC-") and "#item." not in r]
    if bad:
        raise LifecycleError(f"{bad} are documents; name a requirement or an item")
    impact = analyse_impact(store, resolved, trigger)
    dr = DecisionRecord(
        id=next_dr_id(store),
        date=today(),
        trigger=trigger,
        description=description.strip(),
        impacted_items=resolved,
        affected_documents=list(impact.documents),
        status=DrStatus.PROPOSED,
    )
    add_decision_record(store, dr)
    return dr


def _require(dr: DecisionRecord, status: DrStatus, action: str) -> None:
    if dr.status is not status:
        raise LifecycleError(f"{dr.id} is {dr.status.value}; only a {status.value} DR can {action}")


def _signed(approver: str, decision: str) -> None:
    if not approver.strip() or not decision.strip():
        raise LifecycleError("an approver and a decision are required")


def approve_dr(
    store: ProjectStore,
    dr_id: str,
    approver: str,
    decision: str,
    rationale: str | None = None,
) -> tuple[DecisionRecord, Impact]:
    """Approve a proposed DR and store the impact analysis computed now."""
    dr = get_decision_record(store, dr_id)
    _require(dr, DrStatus.PROPOSED, "be approved")
    _signed(approver, decision)
    impact = analyse_impact(store, dr.impacted_items, dr.trigger)
    approved = dr.model_copy(
        update={
            "status": DrStatus.APPROVED,
            "approver": approver.strip(),
            "decision": decision.strip(),
            "rationale": rationale,
            "affected_documents": list(impact.documents),
        }
    )
    save_decision_record(store, approved, "approve", {"impact": impact.to_json()})
    return approved, impact


def reject_dr(
    store: ProjectStore,
    dr_id: str,
    approver: str,
    decision: str,
    rationale: str | None = None,
) -> DecisionRecord:
    """Close a proposed DR without ever propagating it."""
    dr = get_decision_record(store, dr_id)
    _require(dr, DrStatus.PROPOSED, "be rejected")
    _signed(approver, decision)
    rejected = dr.model_copy(
        update={
            "status": DrStatus.CLOSED,
            "approver": approver.strip(),
            "decision": decision.strip(),
            "rationale": rationale,
        }
    )
    save_decision_record(store, rejected, "reject")
    return rejected


def close_dr(store: ProjectStore, dr_id: str) -> DecisionRecord:
    dr = get_decision_record(store, dr_id)
    _require(dr, DrStatus.PROPAGATED, "be closed")
    closed = dr.model_copy(update={"status": DrStatus.CLOSED})
    save_decision_record(store, closed, "close")
    return closed


def mark_propagated(store: ProjectStore, dr: DecisionRecord) -> DecisionRecord:
    done = dr.model_copy(update={"status": DrStatus.PROPAGATED})
    save_decision_record(store, done, "propagate")
    return done


def dr_from_run(store: ProjectStore, run_id: str, today: Clock = dt.date.today) -> DecisionRecord:
    """A clarification DR for an escalated team run (spec 07 section 2.2)."""
    folder = store.path / "runs" / run_id
    summary_path = folder / "team-summary.json"
    if not summary_path.exists():
        raise NotFoundError(f"{run_id} does not exist")
    summary = json.loads(summary_path.read_text("utf-8"))
    if summary["status"] != "escalated":
        raise LifecycleError(f"{run_id} is {summary['status']}; only an escalated run needs a DR")
    mailbox_path = folder / "mailbox.json"
    mailbox = json.loads(mailbox_path.read_text("utf-8")) if mailbox_path.exists() else []
    last_round = max((m["round"] for m in mailbox), default=0)
    texts = list(summary["escalations"])
    refs = [
        m["ref"]
        for m in mailbox
        if m["ref"] and (m["type"] == "question" or m["round"] == last_round)
    ]
    for text in texts:
        refs.extend(_REF.findall(text))
        refs.extend(_REQ.findall(text))
    known = known_nodes(store)
    items = [r for r in dict.fromkeys(refs) if r in known]
    lines = "\n".join(f"- {t}" for t in texts) or "- (no reason recorded)"
    description = f"Run {run_id} ({summary['stage']}) escalated:\n{lines}"
    return new_dr(store, DrTrigger.CLARIFICATION, description, items, today)
