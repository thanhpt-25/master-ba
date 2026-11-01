"""The customer questions ledger: recording what the agents could not settle (spec 13)."""

import datetime as dt
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from masterba.calibration.heuristic import normalise
from masterba.models import Question, QuestionDraft, TeamRun
from masterba.models.enums import DocType, QuestionStatus, TeamRunStatus
from masterba.team import Team
from masterba.trace_store import ProjectStore, add_question, known_nodes, list_questions

Clock = Callable[[], dt.date]
INTAKE_REF = re.compile(r"^intake/[^#/]+#L\d+-L\d+$")


@dataclass(frozen=True)
class Recorded:
    ids: tuple[str, ...] = ()
    reasked: int = 0


def record_questions(
    store: ProjectStore,
    run_id: str,
    stage: DocType,
    drafts: Sequence[QuestionDraft],
    today: Clock = dt.date.today,
) -> Recorded:
    """Add the drafts that are new; an equal normalised text maps to the existing question."""
    nodes = known_nodes(store)
    known = list_questions(store)
    by_text = {normalise(q.text): q for q in known}
    number = max((int(q.id.removeprefix("Q-")) for q in known), default=0) + 1
    ids: list[str] = []
    reasked = 0
    for draft in drafts:
        key = normalise(draft.text)
        if (match := by_text.get(key)) is not None:
            ids.append(match.id)
            reasked += match.status is QuestionStatus.ANSWERED
            continue
        question = Question(
            id=f"Q-{number:04d}",
            origin=draft.origin,
            stage=stage,
            run_id=run_id,
            # Only references that name something stable now: a draft's own item numbers do not.
            refs=[r for r in dict.fromkeys(draft.refs) if r in nodes or INTAKE_REF.match(r)],
            text=draft.text.strip(),
            status=QuestionStatus.OPEN,
            asked_on=today(),
        )
        add_question(store, question)
        by_text[key] = question
        number += 1
        ids.append(question.id)
    return Recorded(tuple(ids), reasked)


def record_run_questions(team: Team, run: TeamRun) -> Recorded:
    """Record what a finished run left open; an escalated run adds QA's objections."""
    drafts = team.collected_questions(escalated=run.status is TeamRunStatus.ESCALATED)
    return record_questions(team.store, run.run_id, run.stage, drafts)
