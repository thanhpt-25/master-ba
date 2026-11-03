"""Basic accept and refuse cases for `check_upload` (one per check of the fixed order)."""

import zipfile
from io import BytesIO

import pytest

from masterba.knowledge.safety import SUPPORTED_TYPES, RefusalKind, check_upload


def _package(members: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return out.getvalue()


_TYPES = b'<?xml version="1.0"?><Types/>'
XLSX = _package({"[Content_Types].xml": _TYPES, "xl/workbook.xml": b"<workbook/>"})
DOCX = _package({"[Content_Types].xml": _TYPES, "word/document.xml": b"<document/>"})


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("notes.md", "# 見出し\n本文".encode()),
        ("NOTES.TXT", b"\xef\xbb\xbfplain text"),
        ("spec.pdf", b"%PDF-1.7\n..."),
        ("book.xlsx", XLSX),
        ("doc.DOCX", DOCX),
    ],
)
def test_accepts_valid_files(name: str, data: bytes) -> None:
    assert check_upload(name, data) == []


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [
        ("", b"x", RefusalKind.NAME),
        ("..", b"x", RefusalKind.NAME),
        ("a/b.md", b"x", RefusalKind.NAME),
        ("a\\b.md", b"x", RefusalKind.NAME),
        ("a\x7fb.md", b"x", RefusalKind.NAME),
        ("あ" * 85 + ".md", b"x", RefusalKind.NAME),
        ("a.md", b"", RefusalKind.EMPTY),
        ("a.zip", b"x", RefusalKind.ARCHIVE),
        ("a.TGZ", b"x", RefusalKind.ARCHIVE),
        ("a.csv", b"x", RefusalKind.TYPE),
        ("a.md", b"PK\x03\x04rest", RefusalKind.ARCHIVE),
        ("a.txt", b"\x00" * 257 + b"ustar", RefusalKind.ARCHIVE),
        ("a.pdf", b"BZh91AY&SYdata", RefusalKind.ARCHIVE),
        ("a.pdf", b"not a pdf", RefusalKind.MISMATCH),
        ("a.txt", b"\xff\xfe", RefusalKind.MISMATCH),
        ("a.docx", b"not a zip", RefusalKind.PACKAGE),
        ("a.docx", XLSX, RefusalKind.PACKAGE),
        ("a.xlsx", XLSX[:-10], RefusalKind.PACKAGE),
        (
            "a.xlsx",
            _package(
                {"[Content_Types].xml": _TYPES, "xl/workbook.xml": b"", "xl/vbaProject.bin": b""}
            ),
            RefusalKind.MACRO,
        ),
        (
            "a.docx",
            _package(
                {
                    "[Content_Types].xml": b"<Types>macroEnabled.12</Types>",
                    "word/document.xml": b"",
                }
            ),
            RefusalKind.MACRO,
        ),
    ],
)
def test_refuses_with_first_failing_check(name: str, data: bytes, kind: RefusalKind) -> None:
    refusals = check_upload(name, data)
    assert [r.kind for r in refusals] == [kind]


def test_size_limit_and_messages() -> None:
    limit = 20 * 1_048_576
    assert check_upload("a.txt", b"a" * limit) == []
    [size] = check_upload("a.txt", b"a" * (limit + 1))
    assert size.kind is RefusalKind.SIZE
    assert "20,971,520" in size.message
    [typ] = check_upload("a.exe", b"x")
    assert all(t in typ.message for t in SUPPORTED_TYPES)
