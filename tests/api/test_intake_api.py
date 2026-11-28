"""The intake files of a project for the Documents tree (spec 26 section 6)."""

from api_support import ClientFor

P = "/api/projects/PRJ-001"


def test_a_viewer_lists_the_intake_files_with_size_and_lines(seeded_client: ClientFor) -> None:
    reply = seeded_client("viewer").get(f"{P}/intake")
    assert reply.status_code == 200
    files = reply.json()
    assert [f["name"] for f in files] == ["login_system.txt"]
    assert files[0]["size"] > 0 and files[0]["lines"] > 1


def test_a_viewer_reads_one_intake_file(seeded_client: ClientFor) -> None:
    viewer = seeded_client("viewer")
    reply = viewer.get(f"{P}/intake/login_system.txt")
    assert reply.status_code == 200
    assert reply.json()["name"] == "login_system.txt" and reply.json()["text"].strip()


def test_unknown_or_unsafe_intake_names_are_not_found(seeded_client: ClientFor) -> None:
    viewer = seeded_client("viewer")
    assert viewer.get(f"{P}/intake/missing.txt").status_code == 404
    assert viewer.get(f"{P}/intake/..%2Fproject.json").status_code == 404
    assert viewer.get(f"{P}/intake/notes.json").status_code == 404


def test_a_project_without_intake_lists_none(empty_client: ClientFor) -> None:
    admin = empty_client("admin")
    assert admin.post("/api/projects", json={"project_id": "PRJ-009"}).status_code == 201
    reply = admin.get("/api/projects/PRJ-009/intake")
    assert reply.status_code == 200 and reply.json() == []


def test_signed_out_users_cannot_read_intake(seeded_client: ClientFor) -> None:
    assert seeded_client(None).get(f"{P}/intake").status_code == 401
