"""Template library: who may see and use which template set, and switching a project (spec 29)."""

from masterba.library.access import VISIBILITIES, TemplateAccess, TemplateAccessError
from masterba.library.coverage import Coverage, TypeCoverage, coverage, kinds
from masterba.library.sets import clone, set_types, sync_builtin
from masterba.library.switch import (
    CoverageGapError,
    SwitchResult,
    UnknownSetError,
    project_coverage,
    reissue,
    set_exists,
    switch_template,
)

__all__ = [
    "VISIBILITIES",
    "Coverage",
    "CoverageGapError",
    "SwitchResult",
    "TemplateAccess",
    "TemplateAccessError",
    "TypeCoverage",
    "UnknownSetError",
    "clone",
    "coverage",
    "kinds",
    "project_coverage",
    "reissue",
    "set_exists",
    "set_types",
    "switch_template",
    "sync_builtin",
]
