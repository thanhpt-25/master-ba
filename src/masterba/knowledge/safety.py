"""Upload checks run before a file is stored in the knowledge base (spec 12, Requirement 2)."""

import re
import zipfile
import zlib
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO

SUPPORTED_TYPES = (".md", ".txt", ".xlsx", ".docx", ".pdf")
MAX_FILE_BYTES = 20 * 1_048_576  # 20,971,520; equal is accepted
MAX_OOXML_UNCOMPRESSED = 200 * 1_048_576
MAX_NAME_BYTES = 255
ARCHIVE_SUFFIXES = (".zip", ".7z", ".tar", ".gz", ".rar", ".bz2", ".xz", ".tgz")

_OFFICE_MAIN_PART = {".xlsx": "xl/workbook.xml", ".docx": "word/document.xml"}
_CONTENT_TYPES = "[Content_Types].xml"
# [Content_Types].xml is tiny in real packages; read at most this much of it.
_MAX_CONTENT_TYPES_BYTES = 1_048_576
_ARCHIVE_PREFIXES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"7z\xbc\xaf\x27\x1c",
    b"\x1f\x8b",
    b"Rar!\x1a\x07",
    b"\xfd7zXZ\x00",
)
_BZIP2 = re.compile(rb"BZh[1-9]1AY&SY")
_TAR_MAGIC_OFFSET = 257
_PDF_HEADER = b"%PDF-"
_UTF8_BOM = b"\xef\xbb\xbf"


class RefusalKind(StrEnum):
    """The rule of Requirement 2 that a refused file breaks."""

    NAME = "name"
    EMPTY = "empty"
    SIZE = "size"
    TYPE = "type"
    ARCHIVE = "archive"
    MISMATCH = "content_mismatch"
    MACRO = "macro"
    PACKAGE = "invalid_package"
    BOMB = "uncompressed_size"


@dataclass(frozen=True)
class Refusal:
    """Why a file was refused; `message` is shown to the user."""

    kind: RefusalKind
    message: str


_MESSAGES = {
    RefusalKind.NAME: "the file name is not allowed",
    RefusalKind.EMPTY: "the file is empty",
    RefusalKind.SIZE: f"the file is larger than the limit of {MAX_FILE_BYTES:,} bytes (20 MB)",
    RefusalKind.TYPE: "the file type is not supported; supported types: "
    + ", ".join(SUPPORTED_TYPES),
    RefusalKind.ARCHIVE: "archives are not accepted",
    RefusalKind.MISMATCH: "the content does not match the extension",
    RefusalKind.MACRO: "the Office file contains a macro project",
    RefusalKind.PACKAGE: "the file is not a valid Office Open XML package",
    RefusalKind.BOMB: "the Office file's total uncompressed size is above the limit of "
    f"{MAX_OOXML_UNCOMPRESSED:,} bytes (200 MB)",
}


def _refuse(kind: RefusalKind) -> list[Refusal]:
    return [Refusal(kind, _MESSAGES[kind])]


def _bad_name(name: str) -> bool:
    if name in ("", ".", ".."):
        return True
    if "/" in name or "\\" in name:
        return True
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return True
    return len(name.encode("utf-8", errors="surrogatepass")) > MAX_NAME_BYTES


def _suffix(name: str) -> str:
    """Lower-cased text from the last dot on, so `.md` and `a.TXT` both have a suffix."""
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def _looks_like_archive(data: bytes) -> bool:
    if data.startswith(_ARCHIVE_PREFIXES) or _BZIP2.match(data):
        return True
    return data[_TAR_MAGIC_OFFSET : _TAR_MAGIC_OFFSET + 5] == b"ustar"


def _check_plain(suffix: str, data: bytes) -> list[Refusal]:
    if _looks_like_archive(data):
        return _refuse(RefusalKind.ARCHIVE)
    if suffix == ".pdf":
        return [] if data.startswith(_PDF_HEADER) else _refuse(RefusalKind.MISMATCH)
    body = data[len(_UTF8_BOM) :] if data.startswith(_UTF8_BOM) else data
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return _refuse(RefusalKind.MISMATCH)
    return []


def _check_office(suffix: str, data: bytes) -> list[Refusal]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as package:
            infos = package.infolist()
            names = {info.filename for info in infos}
            if _CONTENT_TYPES not in names or _OFFICE_MAIN_PART[suffix] not in names:
                return _refuse(RefusalKind.PACKAGE)
            with package.open(_CONTENT_TYPES) as handle:
                content_types = handle.read(_MAX_CONTENT_TYPES_BYTES)
    except (
        zipfile.BadZipFile,  # not a ZIP, e.g. an encrypted (CFB) Office file
        RuntimeError,  # encrypted member
        NotImplementedError,  # unsupported compression method
        OSError,
        EOFError,
        ValueError,
        zlib.error,  # corrupt deflate stream
    ):
        return _refuse(RefusalKind.PACKAGE)
    lowered = content_types.lower()
    if any(name.lower().endswith("vbaproject.bin") for name in names) or (
        b"macroenabled" in lowered or b"vbaproject" in lowered
    ):
        return _refuse(RefusalKind.MACRO)
    if sum(info.file_size for info in infos) > MAX_OOXML_UNCOMPRESSED:
        return _refuse(RefusalKind.BOMB)
    return []


def check_upload(name: str, data: bytes) -> list[Refusal]:
    """Check one upload. An empty list means accepted.

    Pure: no file or network access. Checks run in a fixed order (name, empty, size,
    archive extension, type, content) and stop at the first failure, so at most one
    refusal is returned.
    """
    if _bad_name(name):
        return _refuse(RefusalKind.NAME)
    if len(data) == 0:
        return _refuse(RefusalKind.EMPTY)
    if len(data) > MAX_FILE_BYTES:
        return _refuse(RefusalKind.SIZE)
    suffix = _suffix(name)
    if suffix in ARCHIVE_SUFFIXES:
        return _refuse(RefusalKind.ARCHIVE)
    if suffix not in SUPPORTED_TYPES:
        return _refuse(RefusalKind.TYPE)
    if suffix in _OFFICE_MAIN_PART:
        return _check_office(suffix, data)
    return _check_plain(suffix, data)
