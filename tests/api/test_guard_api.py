"""Spec 30 over the API: intake uploads, masking settings, template sharing."""

import shutil
from pathlib import Path

from fastapi import FastAPI
from openpyxl import load_workbook

from api_support import REPO, ClientFor, Script
from masterba.api import Settings, create_app

P = "/api/projects/PRJ-001"
S = "/api/template-sets"


def test_an_intake_with_a_secret_is_refused_and_personal_data_is_reported(
    seeded_client: ClientFor,
) -> None:
    admin = seeded_client("admin")
    secret = admin.post(f"{P}/intake", files={"file": ("a.txt", b"key AKIAIOSFODNN7EXAMPLE")})
    assert secret.status_code == 400
    assert secret.json()["detail"] == (
        "the file contains a secret (aws_key, line 1); remove it and upload again"
    )
    ok = admin.post(f"{P}/intake", files={"file": ("b.txt", b"x\nmail taro@example.com")})
    assert ok.status_code == 201, ok.text
    assert ok.json() == {
        "name": "b.txt",
        "findings": [{"kind": "email", "line": 2, "preview": "t***@e***.com"}],
    }


def test_masking_settings_need_a_global_admin_to_switch_off(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    admin, approver = seeded_client("admin"), seeded_client("approver")
    assert approver.post("/api/projects", json={"project_id": "PRJ-002"}).status_code == 201
    mine = "/api/projects/PRJ-002/settings/guard"
    terms = approver.post(mine, json={"pii_masking": True, "masking_terms": ["ACME", "acme", "x"]})
    assert terms.status_code == 200, terms.text
    assert terms.json()["masking_terms"] == ["ACME"]
    off = approver.post(mine, json={"pii_masking": False, "masking_terms": []})
    assert off.status_code == 403
    assert seeded_client("viewer").post(mine, json={"pii_masking": True}).status_code == 404

    done = admin.post(mine, json={"pii_masking": False, "masking_terms": ["ACME"]})
    assert done.status_code == 200
    assert admin.get("/api/projects/PRJ-002").json()["project"]["pii_masking"] is False
    events, _ = seeded_app.state.masterba.audit.query(limit=10)
    guard = [e for e in events if e["action"] == "project.guard"]
    assert [e["detail"] for e in guard] == [
        {"pii_masking": False, "terms": 1},
        {"pii_masking": True, "terms": 1},
    ]


def _leaky_set(root: Path) -> Path:
    folder = root / "templates" / "companies" / "acme"
    shutil.copytree(
        REPO / "templates" / "companies" / "sample-sier",
        folder,
        ignore=shutil.ignore_patterns("*.preview.xlsx", "*.sample.xlsx"),
    )
    return folder


def _leak(folder: Path) -> None:
    shell = folder / "BRD.xlsx"
    wb = load_workbook(shell)
    wb.worksheets[0]["Z1"] = "担当 yamada@example.co.jp"
    wb.save(shell)


def test_a_set_with_findings_cannot_be_shared_and_becomes_private_at_start(
    seeded_root: Path, seeded_app: FastAPI, seeded_client: ClientFor, script: Script
) -> None:
    folder = _leaky_set(seeded_root)
    admin = seeded_client("admin")
    public = admin.post(f"{S}/acme/visibility", json={"visibility": "public"})
    assert public.status_code == 200, public.text

    _leak(folder)
    refused = admin.post(f"{S}/acme/visibility", json={"visibility": "shared", "shared_with": []})
    assert refused.status_code == 400
    assert "BRD.xlsx" in refused.json()["detail"] and "yamada" not in refused.json()["detail"]
    assert admin.post(f"{S}/acme/visibility", json={"visibility": "private"}).status_code == 200
    # Back to public behind the API's back, as an old server would have left it.
    seeded_app.state.masterba.templates._update(
        lambda sets: sets["acme"].update(visibility="public")
    )

    again = create_app(
        Settings(root=seeded_root, llm_factory=script.factory, hash_iterations=1000),
        seeded_root / "frontend-missing",
    )
    assert again.state.masterba.templates.entry("acme")["visibility"] == "private"
    events, _ = again.state.masterba.audit.query(limit=5)
    assert any(e["action"] == "template.private_by_guard" and e["target"] == "acme" for e in events)
