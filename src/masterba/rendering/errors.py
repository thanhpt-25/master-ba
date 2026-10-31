"""Rendering errors (specs/02-excel-rendering.md section 1)."""


class RenderError(Exception):
    """Base class for all rendering failures."""


class TemplateNotFoundError(RenderError):
    """No usable template exists for the requested company and document type."""


class InvalidTemplateError(RenderError):
    """A template file is malformed or its bindings do not match the payload model."""


class RenderValidationError(RenderError):
    """Rendered content breaks a `validation_rules` check or the input does not fit."""
