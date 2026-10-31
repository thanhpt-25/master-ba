"""Change management: Decision Records, impact analysis, patches and propagation (spec 07)."""

from masterba.change.diffview import DocumentDiff, dr_diff, rows
from masterba.change.impact import V_ORDER, Impact, ImpactEntry, analyse_impact
from masterba.change.lifecycle import (
    LifecycleError,
    approve_dr,
    close_dr,
    dr_from_run,
    new_dr,
    reject_dr,
)
from masterba.change.links import links_for_document, missing_links
from masterba.change.patch import (
    PatchContext,
    PatchError,
    PatchOp,
    PatchResult,
    RevisionPatch,
    apply_patch,
    validate_patch,
)
from masterba.change.propagate import DocOutcome, PropagationResult, propagate_dr

__all__ = [
    "V_ORDER",
    "DocOutcome",
    "DocumentDiff",
    "Impact",
    "ImpactEntry",
    "LifecycleError",
    "PatchContext",
    "PatchError",
    "PatchOp",
    "PatchResult",
    "PropagationResult",
    "RevisionPatch",
    "analyse_impact",
    "apply_patch",
    "approve_dr",
    "close_dr",
    "dr_diff",
    "dr_from_run",
    "links_for_document",
    "missing_links",
    "new_dr",
    "propagate_dr",
    "reject_dr",
    "rows",
    "validate_patch",
]
