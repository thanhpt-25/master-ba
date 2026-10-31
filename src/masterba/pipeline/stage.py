"""Result type shared by the team-run stages (BRD, SRS)."""

from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from masterba.models import Document, TeamRun, TraceLink
from masterba.models.enums import DocStatus, DocType, TeamRunStatus
from masterba.team import ResumeError, RunCheckpoint, Team
from masterba.trace_store import NotFoundError, ProjectStore, get_config, get_document

TEMPLATE_ID = "default/v1"
M = TypeVar("M", bound=BaseModel)


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
        return team, None
    team, checkpoint = Team.reopen(
        store, stage, resume.run_id, resume.rounds or limit, config.team_token_budget
    )
    if checkpoint.upstream != upstream:
        raise ResumeError(
            f"the inputs of {resume.run_id} changed since it ran "
            f"(then {checkpoint.upstream}, now {upstream}); start a new run"
        )
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
    }
