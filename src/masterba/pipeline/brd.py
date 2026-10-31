"""BRD pipeline: intake -> agent -> ids -> trace store -> Excel (spec 03 section 5)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from masterba.agents import analyse_intake, uncovered_lines
from masterba.agents.requirements_analyst import BrdDraft
from masterba.llm import LLM
from masterba.models import (
    BrdContent,
    BrdItem,
    Document,
    RequirementItem,
    TraceLink,
)
from masterba.models.enums import DocStatus, DocType, LinkType
from masterba.rendering import render_to_project
from masterba.trace_store import (
    DuplicateIdError,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    add_document,
    add_intake,
    add_requirement,
    add_trace_link,
    get_config,
    get_document,
    get_intake,
    list_requirements,
)
from masterba.trace_store.store import normalize_text

BRD_DOC_ID = "DOC-BRD-0001"
TEMPLATE_ID = "default/v1"
MAX_INTAKE_CHARS = 200_000


@dataclass(frozen=True)
class BrdArtifacts:
    requirements: tuple[RequirementItem, ...]
    document: Document
    content: BrdContent
    links: tuple[TraceLink, ...]


@dataclass(frozen=True)
class BrdRunResult:
    document_id: str
    requirement_ids: tuple[str, ...]
    xlsx_path: Path
    open_questions: tuple[str, ...]
    uncovered_lines: tuple[int, ...]
    input_tokens: int
    output_tokens: int
    attempts: int


def next_requirement_number(existing: Sequence[RequirementItem]) -> int:
    """First number after the highest used one; removed requirements still count as used."""
    return max((int(r.id.removeprefix("REQ-")) for r in existing), default=0) + 1


def citation(intake_ref: str, start: int, end: int) -> str:
    return f"{intake_ref}#L{start}-L{end}"


def assign_ids(
    draft: BrdDraft, *, project_id: str, intake_ref: str, first_req_number: int
) -> BrdArtifacts:
    """Pure id assignment: the model never chooses an id."""
    requirements: list[RequirementItem] = []
    items: list[BrdItem] = []
    links: list[TraceLink] = []
    for offset, req in enumerate(draft.requirements):
        req_id = f"REQ-{first_req_number + offset:04d}"
        item_ref = f"{BRD_DOC_ID}#item.{offset + 1}"
        source = citation(intake_ref, req.start_line, req.end_line)
        requirements.append(
            RequirementItem(
                id=req_id, source_ref=source, text=req.description, category=req.category
            )
        )
        items.append(
            BrdItem(
                item_id=item_ref,
                requirement_id=req_id,
                title=req.title,
                description=req.description,
                scope=req.scope,
                source_ref=source,
            )
        )
        links.append(TraceLink(from_id=req_id, to_id=item_ref, link_type=LinkType.REALIZES))
    document = Document(
        id=BRD_DOC_ID,
        type=DocType.BRD,
        version=1,
        status=DocStatus.DRAFT,
        template_id=TEMPLATE_ID,
        content_ref=f"json/brd/{BRD_DOC_ID}.v1.json",
        project_id=project_id,
    )
    return BrdArtifacts(tuple(requirements), document, BrdContent(items=items), tuple(links))


def _brd_exists(store: ProjectStore) -> bool:
    try:
        get_document(store, BRD_DOC_ID)
    except NotFoundError:
        return False
    return True


def _store_intake(store: ProjectStore, name: str, text: str, reuse: bool) -> str:
    """Return the stored (normalised) intake text, committing it first when it is new."""
    try:
        stored = get_intake(store, name)
    except NotFoundError:
        add_intake(store, name, text)
        return get_intake(store, name)
    if not reuse:
        raise DuplicateIdError(f"intake {name} already exists; pass --reuse-intake to use it again")
    if stored != normalize_text(text):
        raise InvalidDocumentError(f"stored intake {name} differs from the given file")
    return stored


def run_brd(
    store: ProjectStore,
    templates_root: Path,
    llm: LLM,
    intake_file: Path,
    *,
    reuse_intake: bool = False,
) -> BrdRunResult:
    """Run the whole BRD stage; nothing but the intake is written unless the draft is accepted."""
    if _brd_exists(store):
        raise DuplicateIdError(
            f"{BRD_DOC_ID} already exists; changing a BRD goes through a Decision Record"
        )
    text = intake_file.read_text(encoding="utf-8")
    if len(text) > MAX_INTAKE_CHARS:
        raise InvalidDocumentError(f"intake is longer than {MAX_INTAKE_CHARS} characters")
    stored = _store_intake(store, intake_file.name, text, reuse_intake)
    analysis = analyse_intake(llm, stored, get_config(store).document_language)
    artifacts = assign_ids(
        analysis.draft,
        project_id=store.project_id,
        intake_ref=f"intake/{intake_file.name}",
        first_req_number=next_requirement_number(list_requirements(store)),
    )
    for requirement in artifacts.requirements:
        add_requirement(store, requirement)
    add_document(store, artifacts.document, artifacts.content)
    for link in artifacts.links:
        add_trace_link(store, link)
    xlsx_path = render_to_project(store, BRD_DOC_ID, templates_root)
    return BrdRunResult(
        document_id=BRD_DOC_ID,
        requirement_ids=tuple(r.id for r in artifacts.requirements),
        xlsx_path=xlsx_path,
        open_questions=tuple(
            f"L{q.start_line}-L{q.end_line}: {q.question}" for q in analysis.draft.open_questions
        ),
        uncovered_lines=tuple(uncovered_lines(analysis.draft, stored)),
        input_tokens=analysis.input_tokens,
        output_tokens=analysis.output_tokens,
        attempts=analysis.attempts,
    )
