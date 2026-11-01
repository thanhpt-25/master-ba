"""Propagation: revise the documents affected by an approved DR (spec 07 section 5)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masterba.agents import QaReport, QaReview, checklist_path, load_checklist, review
from masterba.change.diffview import diff_versions
from masterba.change.impact import Impact
from masterba.change.lifecycle import LifecycleError, mark_propagated
from masterba.change.links import links_for_document, missing_links
from masterba.change.patch import (
    PatchContext,
    RevisionPatch,
    apply_patch,
    max_item_number,
    validate_patch,
)
from masterba.change.reviser import CHECKLIST_STEM, dr_text, patch_view, write_patch
from masterba.llm import LLM
from masterba.models import DecisionRecord, RequirementItem, payload_items
from masterba.models.enums import DocStatus, DrStatus, ItemStatus, TeamRunStatus
from masterba.pipeline.brd import next_requirement_number
from masterba.questions.facts import attach_facts
from masterba.rendering import render_to_project
from masterba.team import RecordingLLM, Team, run_writer_review
from masterba.trace_store import (
    ProjectStore,
    add_document,
    add_requirement,
    add_trace_link,
    get_config,
    get_decision_record,
    get_document,
    get_dr_extra,
    get_trace_links,
    latest_documents,
    list_requirements,
    update_requirement,
    write_dr_extra,
)


@dataclass(frozen=True)
class DocOutcome:
    doc_id: str
    outcome: str  # "revised" | "unchanged" | "escalated"
    version: int | None
    run_id: str
    escalations: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropagationResult:
    dr_id: str
    status: DrStatus
    documents: tuple[DocOutcome, ...]

    @property
    def escalated(self) -> bool:
        return any(d.outcome == "escalated" for d in self.documents)

    def to_json(self) -> dict[str, Any]:
        return {
            "dr_id": self.dr_id,
            "status": self.status.value,
            "documents": [
                {
                    "doc_id": d.doc_id,
                    "outcome": d.outcome,
                    "version": d.version,
                    "run_id": d.run_id,
                    "escalations": list(d.escalations),
                }
                for d in self.documents
            ],
        }


def active_node_ids(store: ProjectStore) -> frozenset[str]:
    """Every active requirement and item id in the project (latest document versions)."""
    nodes = {r.id for r in list_requirements(store) if r.status is ItemStatus.ACTIVE}
    for _, content in latest_documents(store):
        nodes.update(i.item_id for i in payload_items(content) if i.status is ItemStatus.ACTIVE)
    return frozenset(nodes)


def _focus(dr: DecisionRecord, impact: Impact, doc_id: str) -> list[str]:
    own = [i for i in dr.impacted_items if i.startswith(f"{doc_id}#")]
    return list(dict.fromkeys([*own, *(e.node_id for e in impact.entries if e.doc_id == doc_id)]))


def _empty_review() -> QaReview:
    return QaReview(QaReport(), 0, 0, 1)


def _revise(
    store: ProjectStore,
    templates_root: Path,
    dr: DecisionRecord,
    impact: Impact,
    doc_id: str,
    upstream: Sequence[str],
    llm: LLM,
    qa_llm: LLM | None,
) -> DocOutcome:
    config = get_config(store)
    language = config.document_language
    document, content = get_document(store, doc_id)
    requirements: dict[str, RequirementItem] = {r.id: r for r in list_requirements(store)}
    ctx = PatchContext(
        doc_id=doc_id,
        doc_type=document.type,
        dr_id=dr.id,
        active_nodes=active_node_ids(store),
        next_req_number=next_requirement_number(list(requirements.values())),
    )
    checklist = load_checklist(checklist_path(CHECKLIST_STEM[document.type]))
    team = Team.open(
        store,
        document.type,
        config.max_rounds_for(document.type),
        config.team_token_budget,
        trigger=dr.id,
    )
    attach_facts(team)
    writer, reviewer = RecordingLLM(llm, team), RecordingLLM(qa_llm or llm, team)
    focus = _focus(dr, impact, doc_id)
    upstream_text = f"{dr_text(dr)}\n\nChanges already made above this document:\n" + (
        "\n".join(upstream) or "(none)"
    )

    def review_patch(patch: RevisionPatch) -> QaReview:
        if not patch.operations:
            return _empty_review()
        result = apply_patch(content, patch, ctx, requirements)
        return review(
            reviewer,
            checklist=checklist,
            item_counts={doc_id: max_item_number(result.content)},
            upstream=upstream_text,
            draft_view=patch_view(result, content),
            language=language,
        )

    patch = run_writer_review(
        team,
        write=lambda previous, feedback: write_patch(
            writer,
            dr=dr,
            doc_type=document.type,
            content=content,
            focus=focus,
            upstream_changes=upstream,
            language=language,
            previous=previous,
            feedback=feedback,
        ),
        gate=lambda p: validate_patch(content, p, ctx, requirements),
        review=review_patch,
    )
    if patch is None:
        run = team.finish(TeamRunStatus.ESCALATED)
        return DocOutcome(doc_id, "escalated", None, run.run_id, tuple(run.escalations))
    if not patch.operations:
        run = team.finish(TeamRunStatus.DONE)
        return DocOutcome(doc_id, "unchanged", None, run.run_id)

    result = apply_patch(content, patch, ctx, requirements)
    for requirement in result.new_requirements:
        add_requirement(store, requirement)
    for requirement in result.updated_requirements:
        update_requirement(store, requirement)
    version = document.version + 1
    revised = document.model_copy(
        update={
            "version": version,
            "status": DocStatus.DRAFT,
            "content_ref": f"json/{document.type.value.lower()}/{doc_id}.v{version}.json",
            "render_ref": None,
        }
    )
    add_document(store, revised, result.content)
    for link in missing_links(get_trace_links(store), links_for_document(result.content)):
        add_trace_link(store, link)
    render_to_project(store, doc_id, templates_root, version=version)
    run = team.finish(TeamRunStatus.DONE)
    return DocOutcome(doc_id, "revised", version, run.run_id)


def _summaries(store: ProjectStore, doc_id: str, version: int) -> list[str]:
    diff = diff_versions(store, doc_id, version - 1, version)
    return [
        f"{doc_id} v{version}: {c.item_id} {c.change_type.value}"
        + (f" {c.field}: {c.old!r} -> {c.new!r}" if c.field else "")
        for c in diff.changes
    ]


def propagate_dr(
    store: ProjectStore,
    templates_root: Path,
    dr_id: str,
    llm: LLM,
    *,
    qa_llm: LLM | None = None,
) -> PropagationResult:
    """Revise every affected document in V order; stops at the first escalation."""
    dr = get_decision_record(store, dr_id)
    if dr.status is not DrStatus.APPROVED:
        raise LifecycleError(f"{dr.id} is {dr.status.value}; only an approved DR can be propagated")
    stored = get_dr_extra(store, dr_id, "impact")
    if stored is None:
        raise LifecycleError(f"{dr.id} has no stored impact analysis")
    impact = Impact.from_json(stored)
    progress: dict[str, Any] = get_dr_extra(store, dr_id, "propagation") or {"documents": {}}
    done: dict[str, Any] = dict(progress["documents"])
    upstream: list[str] = []
    outcomes: list[DocOutcome] = []
    for doc_id in impact.documents:
        if doc_id in done:
            entry = done[doc_id]
            if entry["outcome"] == "revised":
                upstream.extend(_summaries(store, doc_id, int(entry["version"])))
            outcomes.append(DocOutcome(doc_id, entry["outcome"], entry["version"], entry["run_id"]))
            continue
        outcome = _revise(store, templates_root, dr, impact, doc_id, upstream, llm, qa_llm)
        outcomes.append(outcome)
        if outcome.outcome == "escalated":
            return PropagationResult(dr_id, dr.status, tuple(outcomes))
        done[doc_id] = {
            "outcome": outcome.outcome,
            "version": outcome.version,
            "run_id": outcome.run_id,
        }
        write_dr_extra(
            store,
            dr_id,
            "propagation",
            {"documents": done},
            f"dr({store.project_id}): propagate {dr_id} {doc_id}",
        )
        if outcome.outcome == "revised" and outcome.version is not None:
            upstream.extend(_summaries(store, doc_id, outcome.version))
    final = mark_propagated(store, dr)
    return PropagationResult(dr_id, final.status, tuple(outcomes))
