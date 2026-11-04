"""Phase review gates: which documents a phase has and whether the next one may start.

Spec 15 sections 1 to 3. Imported by the pipelines, so it depends on `models` and
`trace_store` only (the approve and reject actions, which need `change`, are in `actions`).
"""

from masterba.models import Document
from masterba.models.enums import DocStatus, ReviewStage
from masterba.trace_store import ProjectStore, document_versions, get_config, get_document

STAGE_DOCS: dict[ReviewStage, tuple[str, ...]] = {
    ReviewStage.BRD: ("DOC-BRD-0001",),
    ReviewStage.SRS: ("DOC-SRS-0001",),
    ReviewStage.BASIC: ("DOC-BASIC_DESIGN-0001", "DOC-TEST_IT-0001", "DOC-TEST_ST-0001"),
    ReviewStage.DETAIL: ("DOC-DETAIL_DESIGN-0001", "DOC-TEST_UT-0001"),
}
PREVIOUS: dict[ReviewStage, ReviewStage] = {
    ReviewStage.SRS: ReviewStage.BRD,
    ReviewStage.BASIC: ReviewStage.SRS,
    ReviewStage.DETAIL: ReviewStage.BASIC,
}
NEXT: dict[ReviewStage, ReviewStage] = {before: after for after, before in PREVIOUS.items()}


class ReviewError(Exception):
    """A review action or a gated start was refused; nothing was changed."""


def initial_status(store: ProjectStore) -> DocStatus:
    """The status a stage stores its documents with: in review when the project has gates."""
    return DocStatus.IN_REVIEW if get_config(store).review_gates else DocStatus.DRAFT


def latest(store: ProjectStore, doc_id: str) -> Document | None:
    """The latest stored version of a document, or None when it does not exist."""
    if not document_versions(store, doc_id):
        return None
    return get_document(store, doc_id)[0]


def phase_documents(store: ProjectStore, stage: ReviewStage) -> list[Document | None]:
    return [latest(store, doc_id) for doc_id in STAGE_DOCS[stage]]


def phase_state(store: ProjectStore, stage: ReviewStage) -> str:
    """`not_started`, `in_review`, `approved` or `draft` (gates off, or revised by a DR)."""
    docs = phase_documents(store, stage)
    if all(d is None for d in docs):
        return "not_started"
    statuses = {d.status for d in docs if d is not None}
    if DocStatus.IN_REVIEW in statuses:
        return "in_review"
    if statuses == {DocStatus.APPROVED} and all(d is not None for d in docs):
        return "approved"
    return "draft"


def blocking_phase(store: ProjectStore, stage: ReviewStage) -> ReviewStage | None:
    """The previous phase when it is still in review and the project has gates, else None."""
    previous = PREVIOUS.get(stage)
    if previous is None or not get_config(store).review_gates:
        return None
    return previous if phase_state(store, previous) == "in_review" else None


def require_reviewed(store: ProjectStore, stage: ReviewStage) -> None:
    """Refuse to start `stage` while the previous phase is in review (spec 15 section 3.2)."""
    previous = blocking_phase(store, stage)
    if previous is None:
        return
    waiting = [
        f"{d.id} v{d.version} is in_review"
        for d in phase_documents(store, previous)
        if d is not None and d.status is DocStatus.IN_REVIEW
    ]
    raise ReviewError(
        "; ".join(waiting) + f"; approve the {previous.value} phase first: masterba review approve "
        f"--project {store.project_id} --stage {previous.value} --by NAME"
    )
