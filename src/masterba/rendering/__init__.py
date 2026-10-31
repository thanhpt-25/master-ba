"""Deterministic Excel rendering engine (specs/02-excel-rendering.md)."""

from masterba.rendering.engine import render_document
from masterba.rendering.errors import (
    InvalidTemplateError,
    RenderError,
    RenderValidationError,
    TemplateNotFoundError,
)
from masterba.rendering.project import render_to_project
from masterba.rendering.template import ResolvedTemplate, load_template, resolve_template
from masterba.rendering.xlsxio import workbook_bytes

__all__ = [
    "InvalidTemplateError",
    "RenderError",
    "RenderValidationError",
    "ResolvedTemplate",
    "TemplateNotFoundError",
    "load_template",
    "render_document",
    "render_to_project",
    "resolve_template",
    "workbook_bytes",
]
