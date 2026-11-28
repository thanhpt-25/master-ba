"""Scanning an uploaded file before it is stored (spec 30 section 3.2)."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masterba.guard.detect import Finding, describe, find, preview

MAX_REPORTED = 50
_TEXT = (".txt", ".md")


@dataclass(frozen=True)
class UploadScan:
    secret: Finding | None
    pii: tuple[Finding, ...]

    def refusal(self) -> str | None:
        if self.secret is None:
            return None
        return f"the file contains a secret ({describe(self.secret)}); remove it and upload again"

    def report(self) -> list[dict[str, Any]]:
        """Personal data found, without values, for the response (at most 50)."""
        return [
            {"kind": f.kind, "line": f.line, "preview": preview(f)} for f in self.pii[:MAX_REPORTED]
        ]


def scan_text(text: str) -> UploadScan:
    findings = find(text)
    secret = next((f for f in findings if f.category == "secret"), None)
    return UploadScan(secret, tuple(f for f in findings if f.category == "pii"))


def text_of(name: str, data: bytes) -> str | None:
    """The text of an upload as the intake and knowledge base read it; None if unreadable."""
    suffix = Path(name).suffix.lower()
    if suffix in _TEXT:
        return data.decode("utf-8", errors="replace")
    # Imported here: the intake converter pulls in the knowledge extractors.
    from masterba.intake import CONVERTED_SUFFIXES, intake_text

    if suffix not in CONVERTED_SUFFIXES:
        return None
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            return intake_text(path)
        except Exception:  # noqa: BLE001 - an unreadable file is left to the existing checks
            return None


def scan_upload(name: str, data: bytes) -> UploadScan:
    text = text_of(name, data)
    return scan_text(text) if text is not None else UploadScan(None, ())
