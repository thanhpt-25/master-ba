"""Errors of the knowledge base; every message is user-facing."""


class KbError(Exception):
    """A command-level rejection; nothing was changed."""


class UnknownSourceError(KbError):
    def __init__(self, source_id: str, reason: str) -> None:
        super().__init__(f"{source_id}: {reason}")
        self.source_id = source_id
        self.reason = reason  # "unknown" or "already removed"


class UploadRefusedError(KbError):
    """A replacement file was refused (upload rule or duplicate content)."""


class KbCommitError(KbError):
    """Copying a source or committing the Manifest failed; earlier state was restored."""


class IndexBuildError(KbError):
    """Building a new index generation failed; the previous generation stays active."""


class KnowledgeUnavailableError(KbError):
    """The knowledge base lists sources but its index cannot be opened."""
