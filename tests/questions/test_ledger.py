import datetime as dt
import subprocess

from factories import make_requirement
from masterba.models import QuestionDraft
from masterba.models.enums import DocType, QuestionOrigin, QuestionStatus
from masterba.questions import record_questions
from masterba.trace_store import (
    ProjectStore,
    add_requirement,
    get_question,
    list_questions,
    save_question,
)

TODAY = dt.date(2026, 11, 1)


def draft(text: str, *refs: str, origin: QuestionOrigin = QuestionOrigin.AGENT) -> QuestionDraft:
    return QuestionDraft(origin=origin, refs=list(refs), text=text)


def record(store: ProjectStore, *drafts: QuestionDraft, run: str = "RUN-0001"):  # type: ignore[no-untyped-def]
    return record_questions(store, run, DocType.SRS, list(drafts), today=lambda: TODAY)


def subjects(store: ProjectStore) -> list[str]:
    done = subprocess.run(
        ["git", "log", "--format=%s"], cwd=store.root, capture_output=True, text=True, check=True
    )
    return done.stdout.splitlines()


def test_new_drafts_get_ids_in_order_and_one_commit_each(store: ProjectStore) -> None:
    result = record(store, draft("First?"), draft("Second?"))
    assert result.ids == ("Q-0001", "Q-0002")
    assert subjects(store)[:2] == [
        f"question({store.project_id}): add Q-0002",
        f"question({store.project_id}): add Q-0001",
    ]
    first = get_question(store, "Q-0001")
    assert (first.status, first.stage, first.run_id, first.asked_on) == (
        QuestionStatus.OPEN,
        DocType.SRS,
        "RUN-0001",
        TODAY,
    )


def test_equal_normalised_text_adds_nothing_and_returns_the_existing_id(
    store: ProjectStore,
) -> None:
    record(store, draft("What is the limit?"))
    result = record(store, draft("what is  the LIMIT ?"), run="RUN-0002")
    assert result.ids == ("Q-0001",)
    assert [q.run_id for q in list_questions(store)] == ["RUN-0001"]


def test_a_draft_that_matches_an_answered_question_counts_as_reasked(
    store: ProjectStore,
) -> None:
    record(store, draft("What is the limit?"))
    asked = get_question(store, "Q-0001")
    save_question(
        store,
        asked.model_copy(
            update={
                "status": QuestionStatus.ANSWERED,
                "answer": "3 days",
                "answered_by": "alice",
                "answered_on": TODAY,
                "dr_id": "DR-0001",
            }
        ),
        "answer",
    )
    result = record(store, draft("What is the limit?"), draft("A new one?"))
    assert (result.ids, result.reasked) == (("Q-0001", "Q-0002"), 1)


def test_a_withdrawn_question_is_not_added_again(store: ProjectStore) -> None:
    record(store, draft("Not relevant?"))
    save_question(
        store,
        get_question(store, "Q-0001").model_copy(update={"status": QuestionStatus.WITHDRAWN}),
        "withdraw",
    )
    result = record(store, draft("Not relevant?"))
    assert (result.ids, result.reasked) == (("Q-0001",), 0)
    assert len(list_questions(store)) == 1


def test_the_same_text_twice_in_one_batch_is_one_question(store: ProjectStore) -> None:
    result = record(store, draft("Same?"), draft("same ?"))
    assert result.ids == ("Q-0001", "Q-0001")
    assert len(list_questions(store)) == 1


def test_only_stable_references_are_stored(store: ProjectStore) -> None:
    add_requirement(store, make_requirement())
    record(
        store,
        draft(
            "Which one?",
            "REQ-0001",
            "REQ-0099",
            "DOC-SRS-0001#item.9",
            "intake/login_system.txt#L2-L3",
        ),
    )
    assert get_question(store, "Q-0001").refs == ["REQ-0001", "intake/login_system.txt#L2-L3"]


def test_the_origin_is_kept(store: ProjectStore) -> None:
    record(store, draft("QA still objects.", origin=QuestionOrigin.QA_BLOCKER))
    assert get_question(store, "Q-0001").origin is QuestionOrigin.QA_BLOCKER
