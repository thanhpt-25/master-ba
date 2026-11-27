import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from masterba.accounts import AccessError, ProjectAccess


@dataclass(frozen=True)
class Account:
    name: str
    role: str


def make_project(projects: Path, pid: str) -> None:
    (projects / pid).mkdir(parents=True)
    (projects / pid / "project.json").write_text("{}", "utf-8")


@pytest.fixture
def setup(tmp_path: Path) -> tuple[ProjectAccess, Path, list[Account]]:
    projects = tmp_path / "projects"
    make_project(projects, "PRJ-001")
    accounts = [Account("admin", "admin"), Account("alice", "approver"), Account("vera", "viewer")]
    access = ProjectAccess(tmp_path / ".masterba" / "access.json", projects, lambda: accounts)
    return access, projects, accounts


def test_existing_projects_go_to_the_first_admin_and_users_keep_their_access(
    setup: tuple[ProjectAccess, Path, list[Account]],
) -> None:
    access, projects, accounts = setup
    assert access.entry("PRJ-001") == {
        "owner": "admin",
        "members": {"alice": "approver", "vera": "viewer"},
    }
    alice, vera = accounts[1], accounts[2]
    assert access.role_of("PRJ-001", alice) == "approver"
    assert access.role_of("PRJ-001", vera) == "viewer"
    # A project made later with the CLI goes to the admin only.
    make_project(projects, "PRJ-002")
    assert access.entry("PRJ-002") == {"owner": "admin", "members": {}}
    assert access.visible(alice) == ["PRJ-001"]
    assert access.visible(accounts[0]) == ["PRJ-001", "PRJ-002"]
    assert access.role_of("PRJ-002", accounts[0]) == "admin"
    assert access.role_of("PRJ-009", accounts[0]) is None


def test_no_admin_means_no_migration_yet(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    make_project(projects, "PRJ-001")
    accounts: list[Account] = []
    access = ProjectAccess(tmp_path / "access.json", projects, lambda: accounts)
    assert access.entry("PRJ-001") is None
    assert not (tmp_path / "access.json").exists()
    accounts.append(Account("root", "admin"))
    assert access.entry("PRJ-001") == {"owner": "root", "members": {}}


def test_sharing_handing_over_and_forgetting_a_user(
    setup: tuple[ProjectAccess, Path, list[Account]], tmp_path: Path
) -> None:
    access, _, accounts = setup
    access.create("PRJ-005", "alice")
    alice = accounts[1]
    assert access.role_of("PRJ-005", alice) == "admin"
    with pytest.raises(AccessError, match="owns"):
        access.set_member("PRJ-005", "alice", "viewer")
    with pytest.raises(AccessError, match="does not exist"):
        access.set_member("PRJ-005", "mallory", "viewer")
    with pytest.raises(AccessError, match="member role"):
        access.set_member("PRJ-005", "vera", "admin")
    access.set_member("PRJ-005", "vera", "approver")
    access.remove_member("PRJ-005", "vera")
    with pytest.raises(AccessError, match="not a member"):
        access.remove_member("PRJ-005", "vera")
    access.set_owner("PRJ-005", "vera")
    assert access.entry("PRJ-005") == {"owner": "vera", "members": {"alice": "approver"}}
    access.forget_user("vera", "admin")
    access.forget_user("alice", "admin")
    assert access.entry("PRJ-005") == {"owner": "admin", "members": {}}
    saved = json.loads((tmp_path / ".masterba" / "access.json").read_text("utf-8"))
    assert saved["version"] == 1
