"""Result type shared by the team-run stages (BRD, SRS)."""

from dataclasses import dataclass
from pathlib import Path

from masterba.models import TeamRun
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team import Team


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
    requirement_ids: tuple[str, ...] = ()
    xlsx_path: Path | None = None
    open_questions: tuple[str, ...] = ()
    uncovered_lines: tuple[int, ...] = ()


def stage_result(
    team: Team,
    run: TeamRun,
    *,
    document_id: str | None = None,
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
        document_id=document_id,
        requirement_ids=requirement_ids,
        xlsx_path=xlsx_path,
        open_questions=open_questions,
        uncovered_lines=uncovered_lines,
    )
