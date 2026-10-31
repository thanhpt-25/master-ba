"""Errors raised by the trace store."""


class TraceStoreError(Exception):
    """Base class for all trace store failures."""


class DuplicateIdError(TraceStoreError):
    """An id (or link) that must be unique already exists."""


class NotFoundError(TraceStoreError):
    """A referenced project, entity or node does not exist."""


class InvalidDocumentError(TraceStoreError):
    """A document or payload violates a store invariant."""


class IdStabilityError(InvalidDocumentError):
    """A new document version dropped or revived item ids (spec 00 section 3)."""


class GitError(TraceStoreError):
    """A git command failed."""
