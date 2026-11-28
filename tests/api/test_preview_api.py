"""Document preview and per-stage blockers on the overview (spec 19 part 3)."""

import subprocess
from io import BytesIO

from openpyxl import load_workbook

from api_support import ClientFor, new_project

P = "/api/projects/PRJ-001"


def _head(root: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def test_the_preview_lists_every_default_sheet_with_the_workbook_text(
    seeded_client: ClientFor,
) -> None:
    viewer = seeded_client("viewer")
    reply = viewer.get(f"{P}/documents/DOC-BRD-0001/preview")
    assert reply.status_code == 200
    data = reply.json()
    names = [s["name"] for s in data["sheets"]]
    assert names == [
        "表紙", "改訂履歴", "目次", "背景・目的", "業務要件一覧", "システム化の範囲", "対象外業務",
        "前提条件・制約事項", "未決事項", "トレーサビリティ",
    ]  # fmt: skip
    cover = data["sheets"][0]
    assert cover["kind"] == "cover" and cover["title"] == "業務要件定義書"
    assert ["文書番号", "DOC-BRD-0001"] in cover["rows"]
    history = data["sheets"][1]
    assert history["columns"][:4] == ["版数", "改訂日", "改訂箇所", "改訂内容"]
    assert history["rows"][0][:4] == ["1.0", history["rows"][0][1], "全体", "初版作成"]
    toc = data["sheets"][2]
    assert toc["kind"] == "table" and [r[1] for r in toc["rows"]] == names
    background = data["sheets"][3]
    assert background["kind"] == "section" and background["empty_text"]
    requirements = data["sheets"][4]
    assert requirements["columns"][0] == "要件ID"
    assert requirements["rows"] and requirements["rows"][0][0].startswith("REQ-")
    scope = data["sheets"][5]
    assert all(row[3] == "対象" for row in scope["rows"])
    questions = next(s for s in data["sheets"] if s["key"] == "open_questions")
    assert questions["columns"] == ["QA番号", "内容", "参照箇所", "起票日", "状態"]
    assert all(row[4] == "未回答" for row in questions["rows"])


def test_test_spec_preview_drops_hand_entry_columns_and_ends_with_exclusions(
    seeded_client: ClientFor,
) -> None:
    data = seeded_client("viewer").get(f"{P}/documents/DOC-TEST_IT-0001/preview").json()
    cases = next(s for s in data["sheets"] if s["key"] == "cases")
    assert "判定" not in cases["columns"] and "期待結果" in cases["columns"]
    assert cases["columns"][:2] == ["テスト項番", "大項目"]
    assert all(row[0].startswith("TC-IT-") and row[1] for row in cases["rows"])
    progress = next(s for s in data["sheets"] if s["key"] == "progress")
    total = str(len(cases["rows"]))
    assert progress["rows"][-2:] == [["未実施", total], ["合計", total]]
    assert data["sheets"][-1]["name"] == "除外項目"


def test_a_basic_design_preview_shows_the_diagram_note(seeded_client: ClientFor) -> None:
    data = seeded_client("viewer").get(f"{P}/documents/DOC-BASIC_DESIGN-0001/preview").json()
    note = next(s for s in data["sheets"] if s["key"] == "diagrams")
    assert note["kind"] == "note" and note["note"]


def test_the_preview_writes_nothing_and_rejects_unknown_versions(
    seeded_client: ClientFor, seeded_root: object
) -> None:
    viewer = seeded_client("viewer")
    before = _head(str(seeded_root))
    assert viewer.get(f"{P}/documents/DOC-SRS-0001/preview").status_code == 200
    assert _head(str(seeded_root)) == before
    missing = viewer.get(f"{P}/documents/DOC-SRS-0001/preview", params={"version": 9})
    assert missing.status_code == 404


def test_the_overview_counts_questions_per_stage_and_lists_pending_drs(
    seeded_client: ClientFor,
) -> None:
    approver = seeded_client("approver")
    overview = approver.get(P).json()
    counts = {s["stage"]: s["open_questions"] for s in overview["stages"]}
    assert counts["brd"] == 1 and counts["detail"] == 0  # the demo BRD draft's question
    assert overview["pending_drs"] == []
    created = approver.post(
        f"{P}/drs", json={"trigger": "defect", "description": "Bug", "items": ["REQ-0001"]}
    ).json()
    approver.post(f"{P}/drs/{created['id']}/approve", json={"decision": "Fix", "rationale": "x"})
    pending = approver.get(P).json()["pending_drs"]
    assert pending == [{"id": created["id"], "description": "Bug"}]


def test_a_word_intake_is_converted_on_upload_and_bad_files_are_refused(
    empty_client: ClientFor, tmp_path: object
) -> None:
    from pathlib import Path

    from test_intake import make_docx

    admin = empty_client("admin")
    created = new_project(admin, {"project_id": "PRJ-001", "company_id": "default"})
    assert created.status_code == 201, created.text
    path = make_docx(Path(str(tmp_path)) / "RFP v2.docx")
    reply = admin.post(f"{P}/intake", files={"file": ("RFP v2.docx", path.read_bytes())})
    assert reply.status_code == 201, reply.text
    assert reply.json() == {"name": "RFP-v2-docx.md", "converted_from": "RFP v2.docx"}
    fake = admin.post(f"{P}/intake", files={"file": ("x.docx", b"not a zip at all")})
    assert fake.status_code == 400
    blank = admin.post(f"{P}/intake", files={"file": ("x.pdf", b"%PDF-1.4 nothing")})
    assert blank.status_code == 400 and "x.pdf" in blank.json()["detail"]
    other = admin.post(f"{P}/intake", files={"file": ("mail.eml", b"From: a")})
    assert other.status_code == 400


def test_the_registers_download_as_workbooks(seeded_client: ClientFor) -> None:
    viewer = seeded_client("viewer")
    for register, sheet in (("questions", "QA管理表"), ("changes", "変更管理台帳")):
        reply = viewer.get(f"{P}/registers/{register}.xlsx")
        assert reply.status_code == 200
        assert "attachment; filename*=UTF-8''PRJ-001_" in reply.headers["content-disposition"]
        assert load_workbook(BytesIO(reply.content)).sheetnames[0] == sheet
    assert viewer.get(f"{P}/registers/secrets.xlsx").status_code == 422
