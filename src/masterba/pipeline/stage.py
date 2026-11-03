"""Result type shared by the team-run stages (BRD, SRS)."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from masterba.knowledge import KnowledgeSession
from masterba.knowledge.trace import knowledge_links
from masterba.models import Document, KbCitation, Payload, TeamRun, TraceLink
from masterba.models.enums import DocStatus, DocType, TeamRunStatus
from masterba.questions import attach_facts, record_run_questions
from masterba.team import ResumeError, RunCheckpoint, Team
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    add_document,
    get_config,
    get_document,
)

TEMPLATE_ID = "default/v1"
M = TypeVar("M", bound=BaseModel)
# Opens the knowledge session of a stage; tests pass one built on a FakeRetriever.
KnowledgeOpener = Callable[[ProjectStore], KnowledgeSession | None]


def attach_knowledge(team: Team, session: KnowledgeSession | None) -> None:
    """Share the run's seen refs with the session, so a checkpoint keeps them (Req. 10.5)."""
    if session is not None:
        session.seen_refs = team.kb_seen_refs


def kb_block(session: KnowledgeSession | None, role: str, writer_input: str) -> str:
    """A fresh Reference_Block for one writer call; "" without a knowledge base."""
    return session.references_for(role, writer_input) if session else ""


def kb_text(session: KnowledgeSession | None, role: str) -> str:
    """The exact block the writer `role` last received, for QA (no new search, Req. 9.6)."""
    return session.block_for_review(role).text if session else ""


def kb_refs(session: KnowledgeSession | None, role: str) -> frozenset[str]:
    return session.block_for_review(role).refs if session else frozenset()


def kb_gate(
    session: KnowledgeSession | None, role: str, citations: Sequence[tuple[str, KbCitation]]
) -> list[str]:
    return session.gate(role, citations) if session else []


def store_document(store: ProjectStore, doc: Document, content: Payload) -> None:
    """Store a document with its Knowledge_Nodes and `derives_from` links in one commit."""
    nodes, links = knowledge_links(content)
    add_document(store, doc, content, links=links, knowledge=nodes)


def kb_citations(doc_id: str, items: Iterable[object]) -> list[tuple[str, KbCitation]]:
    """(item ref, citation) pairs, numbered as the items will be on commit."""
    return [
        (f"{doc_id}#item.{n}", citation)
        for n, item in enumerate(items, start=1)
        for citation in getattr(item, "kb_citations", [])
    ]


@dataclass(frozen=True)
class Resume:
    """Resume an escalated run (spec 11 section 3.2); `rounds` defaults to the stage limit."""

    run_id: str
    rounds: int | None = None


def open_team(
    store: ProjectStore, stage: DocType, upstream: dict[str, int], resume: Resume | None
) -> tuple[Team, RunCheckpoint | None]:
    """Open a new team, or reopen an escalated run whose inputs have not changed since."""
    config = get_config(store)
    limit = config.max_rounds_for(stage)
    if resume is None:
        team = Team.open(store, stage, limit, config.team_token_budget)
        team.upstream = dict(upstream)
        attach_facts(team)
        return team, None
    team, checkpoint = Team.reopen(
        store, stage, resume.run_id, resume.rounds or limit, config.team_token_budget
    )
    if checkpoint.upstream != upstream:
        raise ResumeError(
            f"the inputs of {resume.run_id} changed since it ran "
            f"(then {checkpoint.upstream}, now {upstream}); start a new run"
        )
    attach_facts(team)
    return team, checkpoint


def checkpoint_draft(checkpoint: RunCheckpoint | None, key: str, model: type[M]) -> M | None:
    """One draft from a checkpoint, parsed as its model (None when absent)."""
    data = checkpoint.drafts.get(key) if checkpoint else None
    return model.model_validate(data) if data is not None else None


def checkpoint_feedback(checkpoint: RunCheckpoint | None, key: str) -> tuple[str, ...]:
    return tuple(checkpoint.feedback.get(key, ())) if checkpoint else ()


def latest_version(store: ProjectStore, doc_id: str) -> int:
    document, _ = get_document(store, doc_id)
    return document.version


@dataclass(frozen=True)
class StageResult:
    stage: DocType
    status: TeamRunStatus
    run_id: str
    rounds: int
    issues_raised: int
    issues_resolved: int
    advisory: tuple[str, ...]
    escalations: tuple[str, ...]
    tokens_used: int
    document_id: str | None = None
    document_ids: tuple[str, ...] = ()
    exchanges: int = 0
    requirement_ids: tuple[str, ...] = ()
    xlsx_path: Path | None = None
    open_questions: tuple[str, ...] = ()
    uncovered_lines: tuple[int, ...] = ()
    question_ids: tuple[str, ...] = ()
    reasked: int = 0


def stage_result(
    team: Team,
    run: TeamRun,
    *,
    document_id: str | None = None,
    document_ids: tuple[str, ...] = (),
    requirement_ids: tuple[str, ...] = (),
    xlsx_path: Path | None = None,
    open_questions: tuple[str, ...] = (),
    uncovered_lines: tuple[int, ...] = (),
) -> StageResult:
    recorded = record_run_questions(team, run)
    return StageResult(
        stage=run.stage,
        status=run.status,
        run_id=run.run_id,
        rounds=run.rounds,
        issues_raised=run.issues_raised,
        issues_resolved=run.issues_resolved,
        advisory=tuple(team.advisory),
        escalations=tuple(run.escalations),
        tokens_used=run.tokens_used or 0,
        document_id=document_id or (document_ids[0] if document_ids else None),
        document_ids=document_ids or ((document_id,) if document_id else ()),
        exchanges=team.exchanges,
        requirement_ids=requirement_ids,
        xlsx_path=xlsx_path,
        open_questions=tuple(dict.fromkeys([*open_questions, *run.customer_questions])),
        uncovered_lines=uncovered_lines,
        question_ids=recorded.ids,
        reasked=recorded.reasked,
    )


def make_document(doc_id: str, doc_type: DocType, project_id: str) -> Document:
    """A version 1 draft document whose content lives at the conventional path."""
    return Document(
        id=doc_id,
        type=doc_type,
        version=1,
        status=DocStatus.DRAFT,
        template_id=TEMPLATE_ID,
        content_ref=f"json/{doc_type.value.lower()}/{doc_id}.v1.json",
        project_id=project_id,
    )


def unique_links(links: list[TraceLink]) -> list[TraceLink]:
    """Drop repeated links, keeping the first occurrence of each."""
    return list(dict.fromkeys(links))


def document_exists(store: ProjectStore, doc_id: str) -> bool:
    try:
        get_document(store, doc_id)
    except NotFoundError:
        return False
    return True


def stage_summary(result: StageResult) -> dict[str, object]:
    """The JSON summary of a stage run (printed by the CLI, returned by the API)."""
    return {
        "stage": result.stage.value,
        "status": result.status.value,
        "run_id": result.run_id,
        "rounds": result.rounds,
        "issues_raised": result.issues_raised,
        "issues_resolved": result.issues_resolved,
        "advisory_issues": list(result.advisory),
        "escalations": list(result.escalations),
        "tokens_used": result.tokens_used,
        "document_id": result.document_id,
        "document_ids": list(result.document_ids),
        "exchanges": result.exchanges,
        "requirement_ids": list(result.requirement_ids),
        "xlsx": str(result.xlsx_path) if result.xlsx_path else None,
        "open_questions": list(result.open_questions),
        "uncovered_lines": list(result.uncovered_lines),
        "question_ids": list(result.question_ids),
        "reasked": result.reasked,
    }
