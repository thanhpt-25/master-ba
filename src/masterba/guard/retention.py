"""Transcript retention (spec 30 section 4)."""

import os
import time
from pathlib import Path

DAYS_ENV = "MASTERBA_TRANSCRIPT_DAYS"
DEFAULT_DAYS = 30


def transcript_days() -> int:
    """Days transcripts are kept; 0 keeps them all. A bad value falls back to the default."""
    raw = os.environ.get(DAYS_ENV, "").strip()
    if not raw:
        return DEFAULT_DAYS
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_DAYS
    return days if days >= 0 else DEFAULT_DAYS


def prune_transcripts(root: Path, days: int, now: float | None = None) -> int:
    """Delete transcript files older than `days` under `projects/*/runs/*/transcripts/`."""
    if days <= 0:
        return 0
    cutoff = (time.time() if now is None else now) - days * 86_400
    removed = 0
    for path in root.glob("projects/*/runs/*/transcripts/*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
