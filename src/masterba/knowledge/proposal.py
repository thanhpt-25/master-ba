"""Replace or remove a cited source and propose a Decision Record (spec 12, Requirement 13).

Kept apart from `knowledge.store` because `change` imports `pipeline`, which imports
`knowledge`; only the CLI and the API import this module.
"""

from masterba.change.lifecycle import new_dr
from masterba.knowledge.errors import KbCommitError
from masterba.knowledge.indexer import DEFAULT_BACKEND, Clock, IndexBackend, utc_now
from masterba.knowledge.store import (
    IncomingFile,
    ReplaceReport,
    remove_source,
    replace_source,
)
from masterba.knowledge.trace import citing_items
from masterba.models import DecisionRecord, KbSource
from masterba.models.enums import DrTrigger
from masterba.trace_store import ProjectStore


def _propose(
    store: ProjectStore, source_id: str, description: str, created: list[DecisionRecord]
) -> None:
    items = citing_items(store, source_id)
    if items:  # an uncited source changes nothing downstream (Requirement 13.7)
        created.append(new_dr(store, DrTrigger.KNOWLEDGE_CHANGE, description, items))


def _commit_failed(exc: KbCommitError, created: list[DecisionRecord]) -> KbCommitError:
    if not created:
        return exc
    dr = created[0].id
    return KbCommitError(
        f"{exc}; {dr} was created for this change, reject it with `masterba dr reject`"
    )


def replace_with_proposal(
    store: ProjectStore,
    source_id: str,
    file: IncomingFile,
    added_by: str,
    *,
    backend: IndexBackend = DEFAULT_BACKEND,
    now: Clock = utc_now,
) -> tuple[ReplaceReport, DecisionRecord | None]:
    created: list[DecisionRecord] = []

    def before_commit(before: KbSource, after: KbSource) -> None:
        description = (
            f"Knowledge source {source_id} ({before.file_name}) was replaced by "
            f"{after.file_name}; sha256 {before.sha256} -> {after.sha256}."
        )
        _propose(store, source_id, description, created)

    try:
        report = replace_source(
            store, source_id, file, added_by, backend=backend, now=now, before_commit=before_commit
        )
    except KbCommitError as exc:
        raise _commit_failed(exc, created) from exc
    return report, created[0] if created else None


def remove_with_proposal(
    store: ProjectStore,
    source_id: str,
    *,
    backend: IndexBackend = DEFAULT_BACKEND,
    now: Clock = utc_now,
) -> tuple[KbSource, DecisionRecord | None]:
    """Removal keeps the Knowledge_Node and its links (Requirement 13.5)."""
    created: list[DecisionRecord] = []

    def before_commit(entry: KbSource) -> None:
        description = f"Knowledge source {source_id} ({entry.file_name}) was removed."
        _propose(store, source_id, description, created)

    try:
        removed = remove_source(
            store, source_id, backend=backend, now=now, before_commit=before_commit
        )
    except KbCommitError as exc:
        raise _commit_failed(exc, created) from exc
    return removed, created[0] if created else None
