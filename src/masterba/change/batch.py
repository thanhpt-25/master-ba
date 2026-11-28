"""Propagate several approved DRs in one call (spec 07 section 5.2)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masterba.change.lifecycle import LifecycleError
from masterba.change.propagate import PropagationResult, propagate_dr
from masterba.llm import LLM
from masterba.models.enums import DrStatus
from masterba.team import PROGRESS
from masterba.trace_store import (
    ProjectStore,
    get_decision_record,
    get_dr_extra,
    list_decision_records,
)

StopHook = Callable[[], str | None]


@dataclass(frozen=True)
class BatchEntry:
    dr_id: str
    outcome: str  # "propagated" | "escalated" | "waiting_for_input" | "failed" | "skipped"
    error: str | None = None
    blocked_by: str | None = None
    propagation: PropagationResult | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "dr_id": self.dr_id,
            "outcome": self.outcome,
            "error": self.error,
            "blocked_by": self.blocked_by,
            "propagation": self.propagation.to_json() if self.propagation else None,
        }


@dataclass(frozen=True)
class BatchResult:
    entries: tuple[BatchEntry, ...]

    @property
    def status(self) -> str:
        """`done` when every DR is propagated; `waiting_for_input` when only answers are missing."""
        outcomes = {e.outcome for e in self.entries}
        if outcomes <= {"propagated"}:
            return "done"
        if outcomes <= {"propagated", "waiting_for_input"}:
            return "waiting_for_input"
        return "escalated"

    @property
    def stopped(self) -> bool:
        return self.status != "done"

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, "results": [e.to_json() for e in self.entries]}


def approved_dr_ids(store: ProjectStore) -> list[str]:
    """Every `approved` DR with a stored impact analysis, oldest first."""
    return sorted(
        dr.id
        for dr in list_decision_records(store)
        if dr.status is DrStatus.APPROVED and get_dr_extra(store, dr.id, "impact") is not None
    )


def _say(line: str) -> None:
    listener = PROGRESS.get()
    if listener is not None:
        listener(line)


def _documents(store: ProjectStore, dr_id: str) -> frozenset[str]:
    try:
        return frozenset(get_decision_record(store, dr_id).affected_documents)
    except Exception:  # an unreadable record blocks nothing; it fails on its own turn
        return frozenset()


def _outcome(result: PropagationResult) -> str:
    if result.escalated:
        return "escalated"
    if result.waiting:
        return "waiting_for_input"
    return "propagated"


def propagate_many(
    store: ProjectStore,
    templates_root: Path,
    dr_ids: Iterable[str],
    llm: LLM,
    *,
    qa_llm: LLM | None = None,
    stop: StopHook | None = None,
) -> BatchResult:
    """Propagate the DRs in id order; a stopped DR only holds back DRs on the same documents."""
    entries: list[BatchEntry] = []
    unsettled: dict[str, str] = {}  # document id -> the DR that stopped or failed on it
    stop_reason: str | None = None
    ordered = sorted(set(dr_ids))
    for index, dr_id in enumerate(ordered, start=1):
        if stop_reason is None and stop is not None:
            stop_reason = stop()
        if stop_reason is not None:
            entries.append(BatchEntry(dr_id, "skipped", error=stop_reason))
            continue
        documents = _documents(store, dr_id)
        blocker = next((unsettled[d] for d in sorted(documents) if d in unsettled), None)
        if blocker is not None:
            entries.append(
                BatchEntry(
                    dr_id,
                    "skipped",
                    error=f"shares a document with {blocker}, which did not finish",
                    blocked_by=blocker,
                )
            )
            continue
        _say(f"{dr_id}: propagating ({index}/{len(ordered)})")
        try:
            result = propagate_dr(store, templates_root, dr_id, llm, qa_llm=qa_llm)
        except LifecycleError as exc:  # refused before anything was written: blocks nothing
            entries.append(BatchEntry(dr_id, "failed", error=str(exc)))
            continue
        except Exception as exc:  # reported per DR; the batch goes on (spec 07 section 5.2)
            entries.append(BatchEntry(dr_id, "failed", error=f"{type(exc).__name__}: {exc}"))
            unsettled.update(dict.fromkeys(documents - unsettled.keys(), dr_id))
            continue
        outcome = _outcome(result)
        _say(f"{dr_id}: {outcome}")
        entries.append(BatchEntry(dr_id, outcome, propagation=result))
        if outcome != "propagated":
            unsettled.update(dict.fromkeys(documents - unsettled.keys(), dr_id))
    return BatchResult(tuple(entries))
