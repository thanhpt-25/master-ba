import datetime as dt
import subprocess

import pytest

from masterba.models import Question
from masterba.models.enums import DocType, QuestionOrigin, QuestionStatus
from masterba.trace_store import (
    DuplicateIdError,
    NotFoundError,
    ProjectStore,
    add_question,
    get_question,
    list_questions,
    save_question,
)


def question(number: int = 1, **update: object) -> Question:
    base = Question(
        id=f"Q-{number:04d}",
        origin=QuestionOrigin.AGENT,
        stage=DocType.SRS,
        run_id="RUN-0001",
        refs=[],
        text=f"Question {number}?",
        status=QuestionStatus.OPEN,
        asked_on=dt.date(2026, 11, 1),
    )
    return base.model_copy(update=update)


def subjects(store: ProjectStore) -> list[str]:
    done = subprocess.run(
        ["git", "log", "--format=%s"], cwd=store.root, capture_output=True, text=True, check=True
    )
    return done.stdout.splitlines()


def test_a_question_is_one_file_and_one_commit(store: ProjectStore) -> None:
    add_question(store, question())
    assert (store.path / "questions" / "Q-0001.json").is_file()
    assert subjects(store)[0] == f"question({store.project_id}): add Q-0001"
    assert get_question(store, "Q-0001") == question()


def test_a_duplicate_id_and_an_unknown_id_are_refused(store: ProjectStore) -> None:
    add_question(store, question())
    with pytest.raises(DuplicateIdError):
        add_question(store, question())
    with pytest.raises(NotFoundError):
        get_question(store, "Q-0002")


def test_list_is_empty_without_a_folder_and_sorted_by_id(store: ProjectStore) -> None:
    assert list_questions(store) == []
    add_question(store, question(2))
    add_question(store, question(1))
    assert [q.id for q in list_questions(store)] == ["Q-0001", "Q-0002"]


def test_save_rewrites_an_existing_question_with_the_action_in_the_subject(
    store: ProjectStore,
) -> None:
    add_question(store, question())
    withdrawn = question(status=QuestionStatus.WITHDRAWN)
    save_question(store, withdrawn, "withdraw")
    assert get_question(store, "Q-0001").status is QuestionStatus.WITHDRAWN
    assert subjects(store)[0] == f"question({store.project_id}): withdraw Q-0001"
    with pytest.raises(NotFoundError):
        save_question(store, question(9), "withdraw")
