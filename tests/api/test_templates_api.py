from pathlib import Path

import pytest

from api_support import ClientFor
from calibration_samples import brd_sample

T = "/api/templates"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def sample(tmp_path: Path) -> bytes:
    return brd_sample(tmp_path / "brd.xlsx").read_bytes()


def upload(client, sample: bytes, name: str = "brd.xlsx", company: str = "acme", query: str = ""):  # type: ignore[no-untyped-def]
    return client.post(f"{T}/{company}/BRD/calibrate{query}", files={"file": (name, sample, XLSX)})


@pytest.mark.parametrize("role", [None, "viewer", "approver"])
def test_only_an_admin_may_touch_templates(
    empty_client: ClientFor, sample: bytes, role: str | None
) -> None:
    client = empty_client(role)
    expected = 401 if role is None else 403

    assert client.get(T).status_code == expected
    assert upload(client, sample).status_code == expected
    assert client.post(f"{T}/acme/BRD/confirm").status_code == expected


def test_an_admin_calibrates_reviews_edits_and_confirms(
    empty_client: ClientFor, sample: bytes
) -> None:
    admin = empty_client("admin")

    created = upload(admin, sample)
    assert created.status_code == 201, created.text
    assert created.json()["state"] == "draft"
    assert created.json()["problems"] == []
    assert admin.get(T).json() == [{"company": "acme", "doc_type": "BRD", "state": "draft"}]

    edited = admin.put(
        f"{T}/acme/BRD/mapping", json={"sheet": "要件一覧", "col": "F", "field": "source_ref"}
    )
    assert edited.status_code == 200, edited.text

    assert admin.post(f"{T}/acme/BRD/preview").json() == {"differences": []}
    assert admin.get(f"{T}/acme/BRD/preview.xlsx").status_code == 200

    confirmed = admin.post(f"{T}/acme/BRD/confirm")
    assert confirmed.json()["state"] == "confirmed"
    assert admin.post(f"{T}/acme/BRD/unconfirm").json()["state"] == "draft"


def test_hostile_uploads_are_rejected(empty_client: ClientFor, sample: bytes) -> None:
    admin = empty_client("admin")

    assert upload(admin, sample, name="macro.xlsm").status_code == 400
    assert upload(admin, b"not a zip").status_code == 400
    assert upload(admin, b"PK" + b"0" * 5_100_000).status_code == 400
    assert upload(admin, sample, company="default").status_code == 400
    assert upload(admin, sample, company="a b").status_code in (400, 404)
    assert (
        admin.post(f"{T}/acme/NOPE/calibrate", files={"file": ("a.xlsx", sample)}).status_code
        == 404
    )


def test_unknown_templates_and_previews_are_404(empty_client: ClientFor) -> None:
    admin = empty_client("admin")

    assert admin.get(f"{T}/acme/BRD").status_code == 404
    assert admin.get(f"{T}/acme/BRD/preview.xlsx").status_code == 404
    assert admin.get(f"{T}/acme/NOPE").status_code == 404


def test_replacing_a_confirmed_template_needs_the_flag(
    empty_client: ClientFor, sample: bytes
) -> None:
    admin = empty_client("admin")
    upload(admin, sample)
    admin.post(f"{T}/acme/BRD/confirm")

    assert upload(admin, sample).status_code == 400
    assert upload(admin, sample, query="?replace=true").status_code == 201
