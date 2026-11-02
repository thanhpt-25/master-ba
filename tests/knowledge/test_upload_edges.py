"""Upload edge cases (Requirements 2.2, 2.3, 2.8)."""

import struct
import zipfile
from io import BytesIO

from masterba.knowledge.safety import MAX_FILE_BYTES, RefusalKind, check_upload

_TYPES = b"<Types/>"


def _package(members: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return out.getvalue()


def _kinds(name: str, data: bytes) -> list[RefusalKind]:
    return [r.kind for r in check_upload(name, data)]


def test_size_boundary() -> None:
    assert _kinds("a.md", b"a" * MAX_FILE_BYTES) == []
    assert _kinds("a.md", b"a" * (MAX_FILE_BYTES + 1)) == [RefusalKind.SIZE]


def test_empty_file() -> None:
    assert _kinds("a.pdf", b"") == [RefusalKind.EMPTY]


def test_xlsx_with_macro_project() -> None:
    data = _package(
        {"[Content_Types].xml": _TYPES, "xl/workbook.xml": b"", "xl/vbaProject.bin": b"x"}
    )
    assert _kinds("a.xlsx", data) == [RefusalKind.MACRO]


def test_broken_zip() -> None:
    good = _package({"[Content_Types].xml": _TYPES, "word/document.xml": b"<d/>"})
    assert _kinds("a.docx", good[: len(good) // 2]) == [RefusalKind.PACKAGE]


def test_declared_uncompressed_size_above_limit() -> None:
    data = bytearray(
        _package({"[Content_Types].xml": _TYPES, "xl/workbook.xml": b"", "xl/big.xml": b"x"})
    )
    # Patch the uncompressed size of the last central directory entry to 201 MB.
    central = data.rfind(b"PK\x01\x02")
    struct.pack_into("<I", data, central + 24, 201 * 1_048_576)
    assert _kinds("a.xlsx", bytes(data)) == [RefusalKind.BOMB]


def test_encrypted_office_file_is_not_a_package() -> None:
    cfb = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    assert _kinds("secret.docx", cfb) == [RefusalKind.PACKAGE]
