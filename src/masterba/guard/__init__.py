"""Sensitive-data guardrails (spec 30): detection, masking, scrubbing, retention, scans."""

from masterba.guard.detect import Finding, clean_terms, describe, find, has_secret, preview
from masterba.guard.mask import GuardedLLM, Masker, masker_for
from masterba.guard.retention import prune_transcripts, transcript_days
from masterba.guard.scrub import scrub
from masterba.guard.upload import UploadScan, scan_text, scan_upload
from masterba.trace_store import InvalidDocumentError


class SecretFoundError(InvalidDocumentError):
    """Text that would be stored or sent holds a secret."""


def refuse_secret(text: str, what: str) -> None:
    """Raise SecretFoundError when `text` holds a secret; the message names no value."""
    found = has_secret(text)
    if found is not None:
        raise SecretFoundError(
            f"{what} contains a secret ({describe(found)}); remove it and try again"
        )


__all__ = [
    "Finding",
    "GuardedLLM",
    "Masker",
    "SecretFoundError",
    "UploadScan",
    "clean_terms",
    "describe",
    "find",
    "has_secret",
    "masker_for",
    "preview",
    "prune_transcripts",
    "refuse_secret",
    "scan_text",
    "scan_upload",
    "scrub",
    "transcript_days",
]
