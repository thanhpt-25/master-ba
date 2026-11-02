"""Extractor unit tests (Requirements 2.6, 4.4, 4.5, 4.6, 4.7, 4.11)."""

import builtins
import socket
from pathlib import Path
from typing import Any

import docx
import pytest
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml.ns import qn
from docx.oxml.parser import OxmlElement
from openpyxl import Workbook
from pypdf import PdfReader, PdfWriter

from masterba.knowledge.extract import ExtractionError, extract_source
from pdfgen import text_pdf


def test_formula_cells_use_cached_values_only(tmp_path: Path) -> None:
    # openpyxl writes no cached value for a formula, so the cell reads as empty.
    wb = Workbook()
    ws: Any = wb.active
    ws["A1"] = "合計"
    ws["B1"] = "=1+1"
    path = tmp_path / "KB-0001.xlsx"
    wb.save(path)
    [chunk] = extract_source("KB-0001", path, ".xlsx")
    assert chunk.text == "合計"
    assert chunk.rows == (1, 1)
    assert chunk.sheet == ws.title


def test_formula_cell_with_cached_value(tmp_path: Path) -> None:
    import zipfile

    wb = Workbook()
    sheet: Any = wb.active
    sheet["A1"] = "=1+1"
    raw = tmp_path / "raw.xlsx"
    wb.save(raw)
    path = tmp_path / "KB-0001.xlsx"
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(path, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<f>1+1</f><v></v>", b"<f>1+1</f><v>2</v>").replace(
                    b"<f>1+1</f>", b"<f>1+1</f><v>2</v>"
                )
            dst.writestr(info, data)
    [chunk] = extract_source("KB-0001", path, ".xlsx")
    assert chunk.text == "2"


def _docx_with_link(path: Path) -> None:
    document = docx.Document()
    document.add_heading("概要", level=1)
    document.add_paragraph("本書は受注を扱う。")
    document.add_heading("画面", level=2)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "画面ID"
    table.cell(0, 1).text = "名称"
    table.cell(1, 0).text = "SC-01"
    table.cell(1, 1).text = "受注登録"
    paragraph = document.add_paragraph("詳細は ")
    r_id = paragraph.part.relate_to(
        "https://example.invalid/spec", RELATIONSHIP_TYPE.HYPERLINK, is_external=True
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "仕様書"
    run.append(text)
    link.append(run)
    paragraph._p.append(link)
    document.save(str(path))


def test_docx_headings_table_and_external_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "KB-0002.docx"
    _docx_with_link(path)
    opened: list[str] = []
    real_open = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    def no_connect(self: socket.socket, address: Any) -> None:
        raise AssertionError(f"connect {address}")

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(socket.socket, "connect", no_connect)
    chunks = extract_source("KB-0002", path, ".docx")
    assert all(name == str(path) for name in opened)
    assert [(c.heading_path, c.text) for c in chunks] == [
        (("概要",), "本書は受注を扱う。"),
        (("概要", "画面"), "画面ID | 名称\nSC-01 | 受注登録"),
        (("概要", "画面"), "詳細は 仕様書"),
    ]


def test_pdf_pages(tmp_path: Path) -> None:
    path = tmp_path / "KB-0003.pdf"
    path.write_bytes(text_pdf(["Order intake rules", "Shipping rules"]))
    chunks = extract_source("KB-0003", path, ".pdf")
    assert [(c.page, c.text) for c in chunks] == [(1, "Order intake rules"), (2, "Shipping rules")]


def test_pdf_without_text_layer(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    path = tmp_path / "KB-0004.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ExtractionError, match="^no text found$"):
        extract_source("KB-0004", path, ".pdf")


def test_encrypted_pdf(tmp_path: Path) -> None:
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(text_pdf(["secret"]))
    writer = PdfWriter(clone_from=PdfReader(plain))
    writer.encrypt(user_password="pw", algorithm="RC4-128")
    path = tmp_path / "KB-0005.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ExtractionError, match="^password-protected PDF$"):
        extract_source("KB-0005", path, ".pdf")


def test_corrupt_xlsx(tmp_path: Path) -> None:
    path = tmp_path / "KB-0006.xlsx"
    path.write_bytes(b"PK\x03\x04 broken")
    with pytest.raises(ExtractionError, match="^cannot read xlsx: "):
        extract_source("KB-0006", path, ".xlsx")


def test_markdown_fenced_code_keeps_hash_lines(tmp_path: Path) -> None:
    path = tmp_path / "KB-0008.md"
    path.write_text("﻿# A\r\n\r\n```\n# not a heading\n```\n", encoding="utf-8")
    [chunk] = extract_source("KB-0008", path, ".md")
    assert chunk.heading_path == ("A",)
    assert "# not a heading" in chunk.text
