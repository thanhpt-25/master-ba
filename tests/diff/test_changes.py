import pytest

from factories import make_brd, make_brd_item
from masterba.diff import (
    ChangeType,
    Classification,
    ItemChange,
    classify_change,
    diff_documents,
)
from masterba.models.enums import ItemStatus

BRD = "DOC-BRD-0001"
ORIGINAL = "The system lets registered users sign in with email and password."


def test_added_and_removed_items_are_detected() -> None:
    old = make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2))
    new = make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 3))
    assert diff_documents(old, new) == [
        ItemChange(
            item_id=f"{BRD}#item.3",
            change_type=ChangeType.ADDED,
            classification=Classification.STRUCTURAL_CHANGE,
        ),
        ItemChange(
            item_id=f"{BRD}#item.2",
            change_type=ChangeType.REMOVED,
            classification=Classification.STRUCTURAL_CHANGE,
        ),
    ]


def test_identical_documents_have_no_changes() -> None:
    doc = make_brd(make_brd_item(BRD, 1))
    assert diff_documents(doc, doc) == []


def test_reworded_description_is_classified_as_reworded_only() -> None:
    reworded = "The system lets registered users sign in using email and password."
    old = make_brd(make_brd_item(BRD, 1, description=ORIGINAL))
    new = make_brd(make_brd_item(BRD, 1, description=reworded))
    [change] = diff_documents(old, new)
    assert change.field == "description"
    assert change.change_type is ChangeType.FIELD_CHANGED
    assert change.classification is Classification.REWORDED_ONLY


def test_meaning_change_is_structural() -> None:
    changed = "Anonymous visitors can read the public catalogue without any account."
    old = make_brd(make_brd_item(BRD, 1, description=ORIGINAL))
    new = make_brd(make_brd_item(BRD, 1, description=changed))
    [change] = diff_documents(old, new)
    assert change.classification is Classification.STRUCTURAL_CHANGE


def test_status_change_is_structural_even_though_short() -> None:
    old = make_brd(make_brd_item(BRD, 1))
    new = make_brd(make_brd_item(BRD, 1, status=ItemStatus.REMOVED))
    [change] = diff_documents(old, new)
    assert (change.field, change.old, change.new) == ("status", "active", "removed")
    assert change.classification is Classification.STRUCTURAL_CHANGE


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "The system must support 100 concurrent users at peak.",
            "The system must support 1000 concurrent users at peak.",
        ),
        ("short", "shorter"),
        (1, 2),
        (["a"], ["b"]),
        (None, "The system must support 100 concurrent users at peak."),
    ],
)
def test_numbers_short_text_and_non_text_are_structural(old: object, new: object) -> None:
    assert classify_change(old, new) is Classification.STRUCTURAL_CHANGE  # type: ignore[arg-type]


def test_threshold_is_configurable() -> None:
    a = "The system lets registered users sign in with email and password."
    b = "The system lets registered users sign in with email."
    assert classify_change(a, b, threshold=0.5) is Classification.REWORDED_ONLY
    assert classify_change(a, b, threshold=0.99) is Classification.STRUCTURAL_CHANGE


def test_whitespace_and_case_do_not_count_as_a_change() -> None:
    a = "The system lets   registered users sign in with email and password."
    b = "the system lets registered users SIGN IN with email and password."
    assert classify_change(a, b) is Classification.REWORDED_ONLY
