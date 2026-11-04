"""Basic Design stage: SRS -> designer/tester/QA team -> design + IT + ST (spec 05)."""

from dataclasses import dataclass
from pathlib import Path

from masterba.agents import checklist_path, load_checklist, review
from masterba.agents.design_writer import (
    BasicDesignDraft,
    active_srs_items,
    design_view,
    srs_view,
    validate_design_draft,
    write_design,
)
from masterba.agents.test_writer import (
    TestDraft,
    cases_view,
    validate_test_draft,
    write_tests,
)
from masterba.knowledge import open_session
from masterba.llm import LLM
from masterba.models import (
    BasicDesignContent,
    BasicDesignItem,
    Document,
    SrsContent,
    TestCaseItem,
    TestExclusion,
    TestSpecContent,
    TraceLink,
)
from masterba.models.enums import DocType, Level, LinkType, ReviewStage, TeamRunStatus
from masterba.pipeline.srs import SRS_DOC_ID
from masterba.pipeline.stage import (
    KnowledgeOpener,
    Resume,
    StageResult,
    attach_knowledge,
    checkpoint_draft,
    checkpoint_feedback,
    document_exists,
    kb_block,
    kb_citations,
    kb_gate,
    kb_refs,
    kb_text,
    latest_version,
    make_document,
    open_team,
    stage_result,
    store_document,
    unique_links,
)
from masterba.rendering import render_to_project
from masterba.review import require_reviewed
from masterba.team import (
    Answer,
    DesignTestHooks,
    DesignTestResult,
    DesignTestStart,
    Question,
    RecordingLLM,
    run_design_test_team,
)
from masterba.trace_store import (
    DuplicateIdError,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    add_trace_link,
    get_config,
    get_document,
)

DESIGN_DOC_ID = "DOC-BASIC_DESIGN-0001"
IT_DOC_ID = "DOC-TEST_IT-0001"
ST_DOC_ID = "DOC-TEST_ST-0001"


@dataclass(frozen=True)
class BasicArtifacts:
    documents: tuple[tuple[Document, BasicDesignContent | TestSpecContent], ...]
    links: tuple[TraceLink, ...]


def assign_basic_ids(
    result: DesignTestResult[BasicDesignDraft, TestDraft], *, project_id: str
) -> BasicArtifacts:
    """Pure id assignment: items by position, test ids in draft order."""
    design, tests = result.design, result.tests
    design_items: list[BasicDesignItem] = []
    links: list[TraceLink] = []
    for number, item in enumerate(design.items, start=1):
        ref = f"{DESIGN_DOC_ID}#item.{number}"
        design_items.append(
            BasicDesignItem(
                item_id=ref,
                kind=item.kind,
                name=item.name,
                description=item.description,
                realizes=list(dict.fromkeys(item.realizes)),
                kb_citations=item.kb_citations,
            )
        )
        links.extend(
            TraceLink(from_id=srs_ref, to_id=ref, link_type=LinkType.REALIZES)
            for srs_ref in dict.fromkeys(item.realizes)
        )
    design_prefix = f"{DESIGN_DOC_ID}#"
    contents: dict[Level, TestSpecContent] = {}
    for level, doc_id, cases in (
        (Level.IT, IT_DOC_ID, tests.it_cases),
        (Level.ST, ST_DOC_ID, tests.st_cases),
    ):
        items: list[TestCaseItem] = []
        for number, case in enumerate(cases, start=1):
            test_id = f"TC-{level.value}-{number:04d}"
            targets = list(dict.fromkeys(case.verifies))
            items.append(
                TestCaseItem(
                    item_id=f"{doc_id}#item.{number}",
                    test_id=test_id,
                    level=level,
                    precondition=case.precondition,
                    input=case.input,
                    steps=case.steps,
                    expected=case.expected,
                    verifies=targets,
                    kb_citations=case.kb_citations,
                )
            )
            links.extend(
                TraceLink(from_id=target, to_id=test_id, link_type=LinkType.TESTS)
                for target in targets
            )
        wanted_design = level is Level.IT
        exclusions = [
            TestExclusion(item_ref=e.item_ref, reason=e.reason)
            for e in tests.exclusions
            if e.item_ref.startswith(design_prefix) == wanted_design
        ]
        contents[level] = TestSpecContent(items=items, exclusions=exclusions)
    documents: tuple[tuple[Document, BasicDesignContent | TestSpecContent], ...] = (
        (
            make_document(DESIGN_DOC_ID, DocType.BASIC_DESIGN, project_id),
            BasicDesignContent(items=design_items),
        ),
        (make_document(IT_DOC_ID, DocType.TEST_IT, project_id), contents[Level.IT]),
        (make_document(ST_DOC_ID, DocType.TEST_ST, project_id), contents[Level.ST]),
    )
    return BasicArtifacts(documents, tuple(unique_links(links)))


def run_basic_design(
    store: ProjectStore,
    templates_root: Path,
    designer_llm: LLM,
    *,
    tester_llm: LLM | None = None,
    qa_llm: LLM | None = None,
    resume: Resume | None = None,
    knowledge: KnowledgeOpener = open_session,
) -> StageResult:
    """Run the Basic Design stage as a three-member team; artifacts are written only when done."""
    for doc_id in (DESIGN_DOC_ID, IT_DOC_ID, ST_DOC_ID):
        if document_exists(store, doc_id):
            raise DuplicateIdError(
                f"{doc_id} already exists; changing a document goes through a Decision Record"
            )
    if not document_exists(store, SRS_DOC_ID):
        raise NotFoundError(f"{SRS_DOC_ID} does not exist; run the srs stage first")
    require_reviewed(store, ReviewStage.BASIC)  # before the team opens (spec 15 3.2)
    _, content = get_document(store, SRS_DOC_ID)
    assert isinstance(content, SrsContent)
    srs_items = active_srs_items(content)
    if not srs_items:
        raise InvalidDocumentError("the SRS has no active items to design from")

    language = get_config(store).document_language
    design_checklist = load_checklist(checklist_path(DocType.BASIC_DESIGN))
    tests_checklist = load_checklist(checklist_path("tests"))
    session = knowledge(store)  # before the team opens (Requirement 9.8)
    team, checkpoint = open_team(
        store, DocType.BASIC_DESIGN, {SRS_DOC_ID: latest_version(store, SRS_DOC_ID)}, resume
    )
    attach_knowledge(team, session)
    designer = RecordingLLM(designer_llm, team)
    tester = RecordingLLM(tester_llm or designer_llm, team)
    reviewer = RecordingLLM(qa_llm or designer_llm, team)
    srs_text = srs_view(srs_items)

    hooks: DesignTestHooks[BasicDesignDraft, TestDraft] = DesignTestHooks(
        write_design=lambda previous, feedback: write_design(
            designer,
            srs_items,
            language,
            previous,
            feedback,
            DESIGN_DOC_ID,
            references=kb_block(session, "designer", srs_text),
        ),
        write_tests=lambda design, previous, feedback: write_tests(
            tester,
            design,
            srs_items,
            language,
            previous,
            feedback,
            DESIGN_DOC_ID,
            IT_DOC_ID,
            ST_DOC_ID,
            references=kb_block(
                session, "tester", f"{srs_text}\n{design_view(design, DESIGN_DOC_ID)}"
            ),
        ),
        gate_design=lambda d: [
            *validate_design_draft(d, srs_items, DESIGN_DOC_ID, language),
            *kb_gate(session, "designer", kb_citations(DESIGN_DOC_ID, d.items)),
        ],
        gate_tests=lambda d, t: [
            *validate_test_draft(t, d, srs_items, DESIGN_DOC_ID, language),
            *kb_gate(
                session,
                "tester",
                [*kb_citations(IT_DOC_ID, t.it_cases), *kb_citations(ST_DOC_ID, t.st_cases)],
            ),
        ],
        questions=lambda t: [Question(q.ref, q.question) for q in t.questions],
        answers=lambda d: [Answer(a.ref, a.text) for a in d.answers],
        review_design=lambda d: review(
            reviewer,
            checklist=design_checklist,
            item_counts={DESIGN_DOC_ID: len(d.items)},
            upstream=srs_text,
            draft_view=design_view(d, DESIGN_DOC_ID),
            language=language,
            references=kb_text(session, "designer", srs_text),
            reference_refs=kb_refs(session, "designer", srs_text),
        ),
        review_tests=lambda d, t: review(
            reviewer,
            checklist=tests_checklist,
            item_counts={IT_DOC_ID: len(t.it_cases), ST_DOC_ID: len(t.st_cases)},
            upstream=f"{srs_text}\n\nBasic Design:\n{design_view(d, DESIGN_DOC_ID)}",
            draft_view=cases_view(t, IT_DOC_ID, ST_DOC_ID),
            language=language,
            references=kb_text(session, "tester", f"{srs_text}\n{design_view(d, DESIGN_DOC_ID)}"),
            reference_refs=kb_refs(
                session, "tester", f"{srs_text}\n{design_view(d, DESIGN_DOC_ID)}"
            ),
        ),
    )
    start = (
        DesignTestStart(
            checkpoint_draft(checkpoint, "design", BasicDesignDraft),
            checkpoint_draft(checkpoint, "tests", TestDraft),
            checkpoint_feedback(checkpoint, "designer"),
            checkpoint_feedback(checkpoint, "tester"),
            checkpoint_feedback(checkpoint, "unresolved"),
        )
        if checkpoint
        else None
    )
    outcome = run_design_test_team(team, hooks, start)
    if outcome is None:
        return stage_result(team, team.finish(TeamRunStatus.ESCALATED))

    artifacts = assign_basic_ids(outcome, project_id=store.project_id)
    for document, doc_content in artifacts.documents:
        store_document(store, document, doc_content)
    for link in artifacts.links:
        add_trace_link(store, link)
    paths = [
        render_to_project(store, document.id, templates_root) for document, _ in artifacts.documents
    ]
    run = team.finish(TeamRunStatus.DONE)
    return stage_result(
        team,
        run,
        document_ids=tuple(document.id for document, _ in artifacts.documents),
        xlsx_path=paths[0],
        open_questions=outcome.unresolved,
    )
