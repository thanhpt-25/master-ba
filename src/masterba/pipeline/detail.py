"""Detail Design stage: Basic Design -> designer/tester/QA team -> detail + UT (spec 06)."""

from dataclasses import dataclass
from pathlib import Path

from masterba.agents import checklist_path, load_checklist, review
from masterba.agents.detail_writer import (
    DetailDesignDraft,
    active_basic_items,
    basic_view,
    detail_view,
    validate_detail_draft,
    write_detail,
)
from masterba.agents.unit_test_writer import (
    UnitTestDraft,
    unit_cases_view,
    validate_unit_test_draft,
    write_unit_tests,
)
from masterba.knowledge import open_session
from masterba.llm import LLM
from masterba.models import (
    BasicDesignContent,
    DetailDesignContent,
    DetailDesignItem,
    Document,
    TestCaseItem,
    TestExclusion,
    TestSpecContent,
    TraceLink,
)
from masterba.models.enums import DocType, Level, LinkType, TeamRunStatus
from masterba.pipeline.basic import DESIGN_DOC_ID
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

DETAIL_DOC_ID = "DOC-DETAIL_DESIGN-0001"
UT_DOC_ID = "DOC-TEST_UT-0001"


@dataclass(frozen=True)
class DetailArtifacts:
    documents: tuple[tuple[Document, DetailDesignContent | TestSpecContent], ...]
    links: tuple[TraceLink, ...]


def assign_detail_ids(
    result: DesignTestResult[DetailDesignDraft, UnitTestDraft], *, project_id: str
) -> DetailArtifacts:
    """Pure id assignment: items by position, `TC-UT-####` in draft order."""
    detail, tests = result.design, result.tests
    items: list[DetailDesignItem] = []
    links: list[TraceLink] = []
    for number, item in enumerate(detail.items, start=1):
        ref = f"{DETAIL_DOC_ID}#item.{number}"
        refines = list(dict.fromkeys(item.refines))
        items.append(
            DetailDesignItem(
                item_id=ref,
                kind=item.kind,
                name=item.name,
                spec=item.spec,
                refines=refines,
                kb_citations=item.kb_citations,
            )
        )
        links.extend(
            TraceLink(from_id=basic_ref, to_id=ref, link_type=LinkType.REALIZES)
            for basic_ref in refines
        )
    cases: list[TestCaseItem] = []
    for number, case in enumerate(tests.ut_cases, start=1):
        test_id = f"TC-UT-{number:04d}"
        targets = list(dict.fromkeys(case.verifies))
        cases.append(
            TestCaseItem(
                item_id=f"{UT_DOC_ID}#item.{number}",
                test_id=test_id,
                level=Level.UT,
                precondition=case.precondition,
                input=case.input,
                steps=case.steps,
                expected=case.expected,
                verifies=targets,
                kb_citations=case.kb_citations,
            )
        )
        links.extend(
            TraceLink(from_id=target, to_id=test_id, link_type=LinkType.TESTS) for target in targets
        )
    exclusions = [TestExclusion(item_ref=e.item_ref, reason=e.reason) for e in tests.exclusions]
    documents: tuple[tuple[Document, DetailDesignContent | TestSpecContent], ...] = (
        (
            make_document(DETAIL_DOC_ID, DocType.DETAIL_DESIGN, project_id),
            DetailDesignContent(items=items),
        ),
        (
            make_document(UT_DOC_ID, DocType.TEST_UT, project_id),
            TestSpecContent(items=cases, exclusions=exclusions),
        ),
    )
    return DetailArtifacts(documents, tuple(unique_links(links)))


def run_detail_design(
    store: ProjectStore,
    templates_root: Path,
    designer_llm: LLM,
    *,
    tester_llm: LLM | None = None,
    qa_llm: LLM | None = None,
    resume: Resume | None = None,
    knowledge: KnowledgeOpener = open_session,
) -> StageResult:
    """Run the Detail Design stage as a three-member team; artifacts are written only when done."""
    for doc_id in (DETAIL_DOC_ID, UT_DOC_ID):
        if document_exists(store, doc_id):
            raise DuplicateIdError(
                f"{doc_id} already exists; changing a document goes through a Decision Record"
            )
    if not document_exists(store, DESIGN_DOC_ID):
        raise NotFoundError(f"{DESIGN_DOC_ID} does not exist; run the basic stage first")
    _, content = get_document(store, DESIGN_DOC_ID)
    assert isinstance(content, BasicDesignContent)
    basic_items = active_basic_items(content)
    if not basic_items:
        raise InvalidDocumentError("the Basic Design has no active items to detail")

    language = get_config(store).document_language
    design_checklist = load_checklist(checklist_path(DocType.DETAIL_DESIGN))
    tests_checklist = load_checklist(checklist_path("unit_tests"))
    session = knowledge(store)  # before the team opens (Requirement 9.8)
    team, checkpoint = open_team(
        store, DocType.DETAIL_DESIGN, {DESIGN_DOC_ID: latest_version(store, DESIGN_DOC_ID)}, resume
    )
    attach_knowledge(team, session)
    designer = RecordingLLM(designer_llm, team)
    tester = RecordingLLM(tester_llm or designer_llm, team)
    reviewer = RecordingLLM(qa_llm or designer_llm, team)
    basic_text = basic_view(basic_items)

    hooks: DesignTestHooks[DetailDesignDraft, UnitTestDraft] = DesignTestHooks(
        write_design=lambda previous, feedback: write_detail(
            designer,
            basic_items,
            language,
            previous,
            feedback,
            DETAIL_DOC_ID,
            references=kb_block(session, "designer", basic_text),
        ),
        write_tests=lambda detail, previous, feedback: write_unit_tests(
            tester,
            detail,
            basic_items,
            language,
            previous,
            feedback,
            DETAIL_DOC_ID,
            UT_DOC_ID,
            references=kb_block(
                session, "tester", f"{basic_text}\n{detail_view(detail, DETAIL_DOC_ID)}"
            ),
        ),
        gate_design=lambda d: [
            *validate_detail_draft(d, basic_items, DETAIL_DOC_ID, language),
            *kb_gate(session, "designer", kb_citations(DETAIL_DOC_ID, d.items)),
        ],
        gate_tests=lambda d, t: [
            *validate_unit_test_draft(t, d, DETAIL_DOC_ID, language),
            *kb_gate(session, "tester", kb_citations(UT_DOC_ID, t.ut_cases)),
        ],
        questions=lambda t: [Question(q.ref, q.question) for q in t.questions],
        answers=lambda d: [Answer(a.ref, a.text) for a in d.answers],
        review_design=lambda d: review(
            reviewer,
            checklist=design_checklist,
            item_counts={DETAIL_DOC_ID: len(d.items)},
            upstream=basic_text,
            draft_view=detail_view(d, DETAIL_DOC_ID),
            language=language,
            references=kb_text(session, "designer", basic_text),
            reference_refs=kb_refs(session, "designer", basic_text),
        ),
        review_tests=lambda d, t: review(
            reviewer,
            checklist=tests_checklist,
            item_counts={UT_DOC_ID: len(t.ut_cases)},
            upstream=f"{basic_text}\n\nDetail Design:\n{detail_view(d, DETAIL_DOC_ID)}",
            draft_view=unit_cases_view(t, UT_DOC_ID),
            language=language,
            references=kb_text(session, "tester", f"{basic_text}\n{detail_view(d, DETAIL_DOC_ID)}"),
            reference_refs=kb_refs(
                session, "tester", f"{basic_text}\n{detail_view(d, DETAIL_DOC_ID)}"
            ),
        ),
    )
    start = (
        DesignTestStart(
            checkpoint_draft(checkpoint, "design", DetailDesignDraft),
            checkpoint_draft(checkpoint, "tests", UnitTestDraft),
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

    artifacts = assign_detail_ids(outcome, project_id=store.project_id)
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
