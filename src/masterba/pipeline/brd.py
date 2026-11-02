"""BRD stage: intake -> writer/QA team -> ids -> trace store -> Excel (specs 03 and 04)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from masterba.agents import (
    BrdDraft,
    brd_draft_view,
    checklist_path,
    load_checklist,
    number_lines,
    review,
    uncovered_lines,
    validate_draft,
    write_brd,
)
from masterba.knowledge import open_session
from masterba.llm import LLM
from masterba.models import (
    BrdContent,
    BrdItem,
    Document,
    QuestionDraft,
    RequirementItem,
    TraceLink,
)
from masterba.models.enums import DocStatus, DocType, LinkType, TeamRunStatus
from masterba.pipeline.stage import (
    TEMPLATE_ID,
    KnowledgeOpener,
    Resume,
    StageResult,
    attach_knowledge,
    checkpoint_draft,
    checkpoint_feedback,
    kb_block,
    kb_citations,
    kb_gate,
    kb_refs,
    kb_text,
    open_team,
    stage_result,
    store_document,
)
from masterba.rendering import render_to_project
from masterba.team import RecordingLLM, run_writer_review
from masterba.trace_store import (
    DuplicateIdError,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
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
MAX_INTAKE_CHARS = 200_000


@dataclass(frozen=True)
class BrdArtifacts:
    requirements: tuple[RequirementItem, ...]
    document: Document
    content: BrdContent
    links: tuple[TraceLink, ...]


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
                kb_citations=req.kb_citations,
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
    qa_llm: LLM | None = None,
    reuse_intake: bool = False,
    resume: Resume | None = None,
    knowledge: KnowledgeOpener = open_session,
) -> StageResult:
    """Run the BRD stage as a writer + QA team; business artifacts are written only when done."""
    if _brd_exists(store):
        raise DuplicateIdError(
            f"{BRD_DOC_ID} already exists; changing a BRD goes through a Decision Record"
        )
    text = intake_file.read_text(encoding="utf-8")
    if len(text) > MAX_INTAKE_CHARS:
        raise InvalidDocumentError(f"intake is longer than {MAX_INTAKE_CHARS} characters")
    # A resumed run reads the intake it stored before; the given file must match it.
    stored = _store_intake(store, intake_file.name, text, reuse_intake or resume is not None)
    language = get_config(store).document_language
    checklist = load_checklist(checklist_path(DocType.BRD))
    # Before the team opens: a broken index stops the stage with nothing written (Req. 9.8).
    session = knowledge(store)
    team, checkpoint = open_team(store, DocType.BRD, {f"intake/{intake_file.name}": 1}, resume)
    attach_knowledge(team, session)
    writer = RecordingLLM(llm, team)
    reviewer = RecordingLLM(qa_llm or llm, team)

    draft = run_writer_review(
        team,
        write=lambda previous, feedback: write_brd(
            writer,
            stored,
            language,
            previous,
            feedback,
            BRD_DOC_ID,
            references=kb_block(session, "writer", stored),
        ),
        # The intake-citation rule stays; Chunk_Refs only add to it (Requirement 10.8).
        gate=lambda d: [
            *validate_draft(d, stored, language),
            *kb_gate(session, "writer", kb_citations(BRD_DOC_ID, d.requirements)),
        ],
        review=lambda d: review(
            reviewer,
            checklist=checklist,
            item_counts={BRD_DOC_ID: len(d.requirements)},
            upstream=number_lines(stored),
            draft_view=brd_draft_view(d, BRD_DOC_ID),
            language=language,
            references=kb_text(session, "writer"),
            reference_refs=kb_refs(session, "writer"),
        ),
        start=checkpoint_draft(checkpoint, "draft", BrdDraft),
        start_feedback=checkpoint_feedback(checkpoint, "writer"),
        writer_questions=lambda d: [
            QuestionDraft(
                refs=[citation(f"intake/{intake_file.name}", q.start_line, q.end_line)],
                text=q.question,
            )
            for q in d.open_questions
        ],
    )
    if draft is None:
        return stage_result(team, team.finish(TeamRunStatus.ESCALATED))

    artifacts = assign_ids(
        draft,
        project_id=store.project_id,
        intake_ref=f"intake/{intake_file.name}",
        first_req_number=next_requirement_number(list_requirements(store)),
    )
    for requirement in artifacts.requirements:
        add_requirement(store, requirement)
    store_document(store, artifacts.document, artifacts.content)
    for link in artifacts.links:
        add_trace_link(store, link)
    xlsx_path = render_to_project(store, BRD_DOC_ID, templates_root)
    run = team.finish(TeamRunStatus.DONE)
    return stage_result(
        team,
        run,
        document_id=BRD_DOC_ID,
        requirement_ids=tuple(r.id for r in artifacts.requirements),
        xlsx_path=xlsx_path,
        open_questions=tuple(
            f"L{q.start_line}-L{q.end_line}: {q.question}" for q in draft.open_questions
        ),
        uncovered_lines=tuple(uncovered_lines(draft, stored)),
    )
