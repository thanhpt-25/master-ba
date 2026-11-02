"""SRS stage: stored BRD -> writer/QA team -> ids -> trace store -> Excel (spec 04 section 5)."""

from dataclasses import dataclass
from pathlib import Path

from masterba.agents import (
    BrdRequirement,
    SrsDraft,
    brd_requirements,
    checklist_path,
    load_checklist,
    review,
    validate_srs_draft,
    write_srs,
)
from masterba.agents.srs_writer import brd_view, draft_view
from masterba.knowledge import open_session
from masterba.llm import LLM
from masterba.models import (
    BrdContent,
    Document,
    QuestionDraft,
    SrsContent,
    SrsItem,
    TraceLink,
)
from masterba.models.enums import DocStatus, DocType, LinkType, TeamRunStatus
from masterba.pipeline.brd import BRD_DOC_ID
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
    latest_version,
    open_team,
    stage_result,
)
from masterba.rendering import render_to_project
from masterba.team import RecordingLLM, run_writer_review
from masterba.trace_store import (
    DuplicateIdError,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    add_document,
    add_trace_link,
    get_config,
    get_document,
    list_requirements,
)

SRS_DOC_ID = "DOC-SRS-0001"


@dataclass(frozen=True)
class SrsArtifacts:
    document: Document
    content: SrsContent
    links: tuple[TraceLink, ...]


def assign_srs_ids(draft: SrsDraft, *, project_id: str) -> SrsArtifacts:
    """Pure id assignment: items are numbered in draft order, the model never picks ids."""
    items: list[SrsItem] = []
    links: list[TraceLink] = []
    for number, item in enumerate(draft.items, start=1):
        item_ref = f"{SRS_DOC_ID}#item.{number}"
        sources = list(dict.fromkeys(item.derives_from))
        items.append(
            SrsItem(
                item_id=item_ref,
                requirement_id=sources[0],
                kind=item.kind,
                statement=item.statement,
                acceptance_hint=item.acceptance_hint,
                derives_from=sources,
            )
        )
        links.extend(
            TraceLink(from_id=req_id, to_id=item_ref, link_type=LinkType.REALIZES)
            for req_id in sources
        )
    document = Document(
        id=SRS_DOC_ID,
        type=DocType.SRS,
        version=1,
        status=DocStatus.DRAFT,
        template_id=TEMPLATE_ID,
        content_ref=f"json/srs/{SRS_DOC_ID}.v1.json",
        project_id=project_id,
    )
    return SrsArtifacts(document, SrsContent(items=items), tuple(links))


def _exists(store: ProjectStore, doc_id: str) -> bool:
    try:
        get_document(store, doc_id)
    except NotFoundError:
        return False
    return True


def _load_brd(store: ProjectStore) -> list[BrdRequirement]:
    if not _exists(store, BRD_DOC_ID):
        raise NotFoundError(f"{BRD_DOC_ID} does not exist; run the brd stage first")
    _, content = get_document(store, BRD_DOC_ID)
    assert isinstance(content, BrdContent)
    brd = brd_requirements(content, list_requirements(store))
    if not brd:
        raise InvalidDocumentError("the BRD has no in-scope requirements to specify")
    return brd


def run_srs(
    store: ProjectStore,
    templates_root: Path,
    llm: LLM,
    *,
    qa_llm: LLM | None = None,
    resume: Resume | None = None,
    knowledge: KnowledgeOpener = open_session,
) -> StageResult:
    """Run the SRS stage as a writer + QA team; business artifacts are written only when done."""
    if _exists(store, SRS_DOC_ID):
        raise DuplicateIdError(
            f"{SRS_DOC_ID} already exists; changing an SRS goes through a Decision Record"
        )
    brd = _load_brd(store)
    language = get_config(store).document_language
    checklist = load_checklist(checklist_path(DocType.SRS))
    session = knowledge(store)  # before the team opens (Requirement 9.8)
    brd_text = brd_view(brd)
    team, checkpoint = open_team(
        store, DocType.SRS, {BRD_DOC_ID: latest_version(store, BRD_DOC_ID)}, resume
    )
    attach_knowledge(team, session)
    writer = RecordingLLM(llm, team)
    reviewer = RecordingLLM(qa_llm or llm, team)

    draft = run_writer_review(
        team,
        write=lambda previous, feedback: write_srs(
            writer,
            brd,
            language,
            previous,
            feedback,
            SRS_DOC_ID,
            references=kb_block(session, "writer", brd_text),
        ),
        gate=lambda d: [
            *validate_srs_draft(d, brd, language),
            *kb_gate(session, "writer", kb_citations(SRS_DOC_ID, d.items)),
        ],
        review=lambda d: review(
            reviewer,
            checklist=checklist,
            item_counts={SRS_DOC_ID: len(d.items)},
            upstream=brd_text,
            draft_view=draft_view(d, SRS_DOC_ID),
            language=language,
            references=kb_text(session, "writer"),
            reference_refs=kb_refs(session, "writer"),
        ),
        start=checkpoint_draft(checkpoint, "draft", SrsDraft),
        start_feedback=checkpoint_feedback(checkpoint, "writer"),
        writer_questions=lambda d: [
            QuestionDraft(refs=list(q.req_ids), text=q.question) for q in d.open_questions
        ],
    )
    if draft is None:
        return stage_result(team, team.finish(TeamRunStatus.ESCALATED))

    artifacts = assign_srs_ids(draft, project_id=store.project_id)
    add_document(store, artifacts.document, artifacts.content)
    for link in artifacts.links:
        add_trace_link(store, link)
    xlsx_path = render_to_project(store, SRS_DOC_ID, templates_root)
    run = team.finish(TeamRunStatus.DONE)
    return stage_result(
        team,
        run,
        document_id=SRS_DOC_ID,
        xlsx_path=xlsx_path,
        open_questions=tuple(f"{', '.join(q.req_ids)}: {q.question}" for q in draft.open_questions),
    )
