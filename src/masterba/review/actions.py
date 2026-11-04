"""Approve or reject a phase (spec 15 sections 3 to 6).

Imported by the CLI and the API only: rejecting runs Decision Record propagation, and
`change` imports `pipeline`.
"""

import datetime as dt
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from masterba.change import PropagationResult, analyse_impact, approve_dr, new_dr, propagate_dr
from masterba.llm import LLM
from masterba.models import Document, Review, ReviewComment, ReviewedDocument, payload_items
from masterba.models.enums import (
    DocStatus,
    DrTrigger,
    ItemStatus,
    QuestionStatus,
    ReviewDecision,
    ReviewStage,
)
from masterba.rendering import render_to_project
from masterba.review.gates import NEXT, STAGE_DOCS, ReviewError, latest
from masterba.trace_store import (
    ProjectStore,
    add_review,
    get_document,
    list_questions,
    list_reviews,
    save_review,
)

Clock = Callable[[], dt.datetime]
_ITEM_PREFIX = re.compile(r"^\s*(DOC-[A-Z_]+-\d{4}#item\.\d+)\s*:\s*(.*)$", re.S)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def parse_comment(raw: str) -> ReviewComment:
    """`DOC-SRS-0001#item.12: text` names an item; any other text is about the whole phase."""
    match = _ITEM_PREFIX.match(raw)
    if match:
        return ReviewComment(ref=match.group(1), text=match.group(2).strip())
    return ReviewComment(text=raw.strip())


def next_review_id(store: ProjectStore) -> str:
    numbers = [int(r.id.removeprefix("REV-")) for r in list_reviews(store)]
    return f"REV-{max(numbers, default=0) + 1:04d}"


def open_question_ids(store: ProjectStore) -> list[str]:
    return [q.id for q in list_questions(store) if q.status is QuestionStatus.OPEN]


def phase_in_review(store: ProjectStore, stage: ReviewStage) -> list[Document]:
    """The phase's latest versions, when the whole phase is waiting for review."""
    after = NEXT.get(stage)
    if after is not None and any(latest(store, d) for d in STAGE_DOCS[after]):
        raise ReviewError(
            f"the {after.value} phase has started; change the {stage.value} documents "
            "through a Decision Record"
        )
    docs = [latest(store, doc_id) for doc_id in STAGE_DOCS[stage]]
    missing = [doc_id for doc_id, d in zip(STAGE_DOCS[stage], docs, strict=True) if d is None]
    if missing:
        raise ReviewError(
            f"the {stage.value} phase has no {', '.join(missing)}; run the {stage.value} stage"
        )
    found = [d for d in docs if d is not None]
    if any(d.status is not DocStatus.IN_REVIEW for d in found):
        listed = "; ".join(f"{d.id} v{d.version} is {d.status.value}" for d in found)
        raise ReviewError(f"{listed}; only a phase in review can be approved or rejected")
    return found


def _signer(by: str) -> str:
    if not by.strip():
        raise ReviewError("say who reviews (--by)")
    return by.strip()


def _render(store: ProjectStore, templates_root: Path, docs: Sequence[Document]) -> None:
    # The workbooks print the status, so a status change renders the version again;
    # render_to_project reads the stored version, so only id and version matter here.
    for doc in docs:
        render_to_project(store, doc.id, templates_root, version=doc.version)


def approve_phase(
    store: ProjectStore,
    templates_root: Path,
    stage: ReviewStage,
    by: str,
    *,
    now: Clock = utc_now,
) -> Review:
    """Approve every document of a phase in review; the next stage may then start."""
    docs = phase_in_review(store, stage)
    review = Review(
        id=next_review_id(store),
        stage=stage,
        documents=[ReviewedDocument(doc_id=d.id, version=d.version) for d in docs],
        decision=ReviewDecision.APPROVED,
        by=_signer(by),
        at=now(),
        open_questions=open_question_ids(store),
    )
    add_review(store, review, DocStatus.APPROVED)
    _render(store, templates_root, docs)
    return review


def _active_items(store: ProjectStore, docs: Sequence[Document]) -> list[str]:
    refs: list[str] = []
    for doc in docs:
        _, content = get_document(store, doc.id, doc.version)
        refs += [i.item_id for i in payload_items(content) if i.status is ItemStatus.ACTIVE]
    return refs


def check_rejection(
    store: ProjectStore, stage: ReviewStage, comments: Sequence[ReviewComment]
) -> tuple[list[Document], list[str]]:
    """Validate a rejection before anything is written; return the phase and impacted items."""
    docs = phase_in_review(store, stage)
    if not comments:
        raise ReviewError("a rejection needs at least one comment")
    items = _active_items(store, docs)
    unknown = sorted({c.ref for c in comments if c.ref and c.ref not in items})
    if unknown:
        raise ReviewError(f"{', '.join(unknown)} are not active items of the {stage.value} phase")
    named = [c.ref for c in comments if c.ref]
    impacted = list(dict.fromkeys(named)) if len(named) == len(comments) else items
    outside = set(analyse_impact(store, impacted, DrTrigger.REVIEW_FEEDBACK).documents) - set(
        STAGE_DOCS[stage]
    )
    if outside:
        raise ReviewError(f"the comments reach {', '.join(sorted(outside))} outside the phase")
    return docs, impacted


def _description(review_id: str, stage: ReviewStage, comments: Sequence[ReviewComment]) -> str:
    lines = [f"- {c.ref or f'the {stage.value} phase'}: {c.text}" for c in comments]
    return f"Review {review_id} rejected the {stage.value} phase:\n" + "\n".join(lines)


def record_revision(store: ProjectStore, review: Review, result: PropagationResult) -> Review:
    """Name the run of the revision: the escalated one, else the last document revised."""
    runs = [d.run_id for d in result.documents if d.outcome == "escalated"] or [
        d.run_id for d in result.documents
    ]
    if not runs:
        return review
    updated = review.model_copy(update={"revision_run": runs[0] if result.escalated else runs[-1]})
    save_review(store, updated, "update")
    return updated


def review_of_dr(store: ProjectStore, dr_id: str) -> Review | None:
    return next((r for r in list_reviews(store) if r.dr_id == dr_id), None)


def reject_phase(
    store: ProjectStore,
    templates_root: Path,
    stage: ReviewStage,
    by: str,
    comments: Sequence[ReviewComment],
    llm: LLM,
    *,
    qa_llm: LLM | None = None,
    now: Clock = utc_now,
) -> tuple[Review, PropagationResult]:
    """Record the comments and revise the phase through a `review_feedback` DR (section 5)."""
    signer = _signer(by)
    docs, impacted = check_rejection(store, stage, comments)
    review_id = next_review_id(store)
    at = now()
    dr = new_dr(
        store,
        DrTrigger.REVIEW_FEEDBACK,
        _description(review_id, stage, comments),
        impacted,
        today=lambda: at.date(),
    )
    approve_dr(
        store,
        dr.id,
        signer,
        f"Revise the {stage.value} documents as the review comments ask ({review_id})",
    )
    review = Review(
        id=review_id,
        stage=stage,
        documents=[ReviewedDocument(doc_id=d.id, version=d.version) for d in docs],
        decision=ReviewDecision.REJECTED,
        by=signer,
        at=at,
        comments=list(comments),
        open_questions=open_question_ids(store),
        dr_id=dr.id,
    )
    add_review(store, review, None)
    result = propagate_dr(store, templates_root, dr.id, llm, qa_llm=qa_llm)
    return record_revision(store, review, result), result
