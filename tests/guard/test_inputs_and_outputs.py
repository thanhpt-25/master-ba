import json
import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment

from masterba.guard import (
    SecretFoundError,
    prune_transcripts,
    refuse_secret,
    scan_text,
    scan_upload,
    scrub,
    transcript_days,
)
from masterba.guard.scan import scan_project
from masterba.guard.templates import clean_workbook, set_findings
from masterba.guard.upload import text_of


def test_scrub_removes_findings_and_credentials_in_urls_and_headers() -> None:
    text = (
        "POST https://bob:hunter2@gw.example.com/v1 failed; Authorization: Bearer abc.def "
        "x-api-key=sk-ant-api03-" + "z" * 24 + " for taro@example.com"
    )
    clean = scrub(text)
    assert "hunter2" not in clean and "abc.def" not in clean
    assert "sk-ant" not in clean and "taro@example.com" not in clean
    assert "https://***@gw.example.com/v1" in clean
    assert "t***@e***.com" in clean
    assert scrub("nothing here") == "nothing here"


def test_refuse_secret_names_the_kind_and_line_but_not_the_value() -> None:
    refuse_secret("fine text", "the intake")
    with pytest.raises(
        SecretFoundError, match=r"the intake contains a secret \(aws_key, line 2\)"
    ) as info:
        refuse_secret("a\nkey AKIAIOSFODNN7EXAMPLE", "the intake")
    assert "AKIA" not in str(info.value)


def test_upload_scan_refuses_secrets_and_reports_personal_data() -> None:
    clean = scan_text("call 03-1234-5678 or mail taro@example.com")
    assert clean.refusal() is None
    assert clean.report() == [
        {"kind": "phone", "line": 1, "preview": "0***8"},
        {"kind": "email", "line": 1, "preview": "t***@e***.com"},
    ]
    secret = scan_upload("notes.md", b"token: ghp_" + b"a" * 36)
    assert secret.refusal() == (
        "the file contains a secret (github_token, line 1); remove it and upload again"
    )
    assert scan_upload("photo.png", b"\x89PNG").refusal() is None


def test_text_of_reads_office_files_and_gives_up_on_broken_ones() -> None:
    wb = Workbook()
    sheet: Any = wb.active
    sheet["A1"] = "担当: taro@example.com"
    buffer = BytesIO()
    wb.save(buffer)
    text = text_of("要件.xlsx", buffer.getvalue())
    assert text is not None and "taro@example.com" in text
    assert text_of("broken.docx", b"not a zip") is None


def test_transcripts_older_than_the_retention_are_pruned(tmp_path: Path) -> None:
    folder = tmp_path / "projects" / "PRJ-001" / "runs" / "RUN-0001" / "transcripts"
    folder.mkdir(parents=True)
    old, new = folder / "001.txt", folder / "002.txt"
    old.write_text("old")
    new.write_text("new")
    month = time.time() - 31 * 86_400
    os.utime(old, (month, month))
    assert prune_transcripts(tmp_path, 0) == 0
    assert prune_transcripts(tmp_path, 30) == 1
    assert not old.exists() and new.exists()


@pytest.mark.parametrize(("raw", "days"), [("", 30), ("7", 7), ("0", 0), ("x", 30), ("-3", 30)])
def test_transcript_days_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, days: int
) -> None:
    monkeypatch.setenv("MASTERBA_TRANSCRIPT_DAYS", raw)
    assert transcript_days() == days


def _workbook(path: Path) -> Path:
    wb = Workbook()
    ws: Any = wb.active
    ws.title = "表紙"
    ws["A1"] = "基本設計書"
    ws["A2"] = "担当: yamada@example.co.jp"
    ws["A3"] = "作成日"
    ws["A3"].comment = Comment("ask 090-1234-5678", "x")
    hidden = wb.create_sheet("memo")
    hidden.sheet_state = "hidden"
    hidden["B2"] = "password=Passw0rd123"
    wb.properties.title = "for ACME"
    wb.save(path)
    return path


def test_set_findings_covers_hidden_sheets_comments_and_json(tmp_path: Path) -> None:
    folder = tmp_path / "acme"
    folder.mkdir()
    _workbook(folder / "BRD.xlsx")
    _workbook(folder / "BRD.sample.xlsx")  # samples are not part of the set's shared files
    (folder / "BRD.calibration.json").write_text(json.dumps({"note": "mail a@b.co"}))
    found = [f.text() for f in set_findings(folder)]
    assert found == [
        "BRD.calibration.json line 1: email a***@b***.co",
        "BRD.xlsx 表紙!A2: email y***@e***.jp",
        "BRD.xlsx 表紙!A3 (comment): phone 0***8",
        "BRD.xlsx memo!B2: credential [credential]",
    ]
    assert set_findings(tmp_path / "missing") == []


def test_clean_workbook_empties_cells_and_drops_comments_and_properties(tmp_path: Path) -> None:
    wb = load_workbook(_workbook(tmp_path / "s.xlsx"))
    assert clean_workbook(wb) == ["表紙!A2", "memo!B2"]
    assert wb["表紙"]["A1"].value == "基本設計書"
    assert wb["表紙"]["A3"].comment is None
    assert wb.properties.title is None


def test_scan_project_reports_files_and_history(tmp_path: Path) -> None:
    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "T")
    git("config", "user.email", "t@t.invalid")
    project = tmp_path / "projects" / "PRJ-001"
    (project / "intake").mkdir(parents=True)
    note = project / "intake" / "a.md"
    note.write_text("line\nkey AKIAIOSFODNN7EXAMPLE\n")
    git("add", ".")
    git("commit", "-q", "-m", "add")
    note.write_text("line\nmail taro@example.com\n")
    report = scan_project(tmp_path, project, history=True)
    lines = [h.line() for h in report.hits]
    assert lines[0] == "projects/PRJ-001/intake/a.md:2: pii email t***@e***.com"
    assert lines[1].endswith(" projects/PRJ-001/intake/a.md:2: secret aws_key [aws_key]")
    assert report.secrets == 1
    assert report.to_json()["counts"] == {"pii": 1, "secret": 1}
    assert report.to_json()["findings"][1]["commit"]
