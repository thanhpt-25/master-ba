"""Spec 29 section 1.2: who sees and manages a template set."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from masterba.library import TemplateAccess, TemplateAccessError


@dataclass(frozen=True)
class Person:
    name: str
    role: str


ADMIN, ANNA, BOB, CARL = (
    Person("root", "admin"),
    Person("anna", "approver"),
    Person("bob", "viewer"),
    Person("carl", "viewer"),
)


def _access(tmp_path: Path, people: list[Person], folders: tuple[str, ...] = ()) -> TemplateAccess:
    templates = tmp_path / "templates"
    for name in folders:
        (templates / "companies" / name).mkdir(parents=True)
    return TemplateAccess(tmp_path / "state" / "template_access.json", templates, lambda: people)


def test_existing_sets_go_to_the_first_admin_and_the_sample_is_public(tmp_path: Path) -> None:
    access = _access(tmp_path, [ANNA, ADMIN], ("acme", "sample-sier"))

    assert access.entry("acme") == {
        "owner": "root",
        "visibility": "private",
        "shared_with": [],
        "title": None,
    }
    sample = access.entry("sample-sier")
    assert sample is not None and sample["visibility"] == "public" and sample["title"]
    assert access.visible(ANNA) == ["default", "sample-sier"]
    assert access.visible(ADMIN) == ["default", "acme", "sample-sier"]


def test_without_an_admin_nothing_is_written_until_one_exists(tmp_path: Path) -> None:
    people = [ANNA]
    access = _access(tmp_path, people, ("acme",))

    assert access.entry("acme") is None
    assert not (tmp_path / "state" / "template_access.json").exists()
    people.append(ADMIN)
    assert access.entry("acme") is not None


def test_private_shared_and_public(tmp_path: Path) -> None:
    access = _access(tmp_path, [ADMIN, ANNA, BOB, CARL])
    (tmp_path / "templates" / "companies" / "anna-co").mkdir(parents=True)
    access.create("anna-co", "anna")

    assert access.sees("anna-co", ANNA) and access.manages("anna-co", ANNA)
    assert not access.sees("anna-co", BOB)
    assert access.sees("anna-co", ADMIN) and access.manages("anna-co", ADMIN)

    access.set_visibility("anna-co", "shared", ["bob", "anna", " "])
    assert access.entry("anna-co")["shared_with"] == ["bob"]  # type: ignore[index]
    assert access.sees("anna-co", BOB) and not access.manages("anna-co", BOB)
    assert not access.sees("anna-co", CARL)

    access.set_visibility("anna-co", "public")
    assert access.sees("anna-co", CARL) and not access.manages("anna-co", CARL)

    access.set_visibility("anna-co", "private")
    assert not access.sees("anna-co", BOB)


def test_the_builtin_set_is_seen_by_everyone_and_managed_by_nobody(tmp_path: Path) -> None:
    access = _access(tmp_path, [ADMIN, BOB])

    assert access.sees("default", BOB)
    assert not access.manages("default", ADMIN)
    assert not access.sees("ghost", ADMIN)


def test_bad_changes_are_refused(tmp_path: Path) -> None:
    access = _access(tmp_path, [ADMIN], ("acme",))

    with pytest.raises(TemplateAccessError, match="no such user"):
        access.set_visibility("acme", "shared", ["nobody"])
    with pytest.raises(TemplateAccessError, match="visibility"):
        access.set_visibility("acme", "everyone")
    with pytest.raises(TemplateAccessError, match="no template set"):
        access.set_visibility("ghost", "public")
    with pytest.raises(TemplateAccessError, match="80"):
        access.set_title("acme", "x" * 81)
    access.set_title("acme", "  ACME 標準  ")
    assert access.entry("acme")["title"] == "ACME 標準"  # type: ignore[index]


def test_a_removed_user_hands_their_sets_over_and_leaves_every_share(tmp_path: Path) -> None:
    access = _access(tmp_path, [ADMIN, ANNA, BOB], ("acme",))
    (tmp_path / "templates" / "companies" / "anna-co").mkdir(parents=True)
    access.create("anna-co", "anna")
    access.set_visibility("anna-co", "shared", ["bob", "root"])
    access.set_visibility("acme", "shared", ["anna"])

    access.forget_user("anna", "root")

    assert access.entry("anna-co")["owner"] == "root"  # type: ignore[index]
    assert access.entry("anna-co")["shared_with"] == ["bob"]  # type: ignore[index]
    assert access.entry("acme")["shared_with"] == []  # type: ignore[index]
