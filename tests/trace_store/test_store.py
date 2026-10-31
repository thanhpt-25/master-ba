import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from factories import (
    doc_id,
    make_brd,
    make_brd_item,
    make_config,
    make_document,
    make_requirement,
    make_test_item,
    make_test_spec,
)
from masterba.models import DecisionRecord, Document, RequirementItem, TraceLink
from masterba.models.enums import DocType, DrStatus, DrTrigger, ItemStatus, Level, LinkType
from masterba.trace_store import (
    DuplicateIdError,
    IdStabilityError,
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    add_decision_record,
    add_document,
    add_requirement,
    add_trace_link,
    create_project,
    get_config,
    get_decision_record,
    get_document,
    get_requirement,
    get_trace_links,
    open_project,
)
from masterba.trace_store.git import commit_paths

BRD = doc_id(DocType.BRD)


def test_create_project_writes_config_in_one_commit(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = create_project(projects_root, make_config())
    assert commit_log()[0] == "project(PRJ-001): create"
    assert get_config(store) == make_config()
    assert open_project(projects_root, "PRJ-001") == store


def test_create_project_twice_fails(projects_root: Path, store: ProjectStore) -> None:
    with pytest.raises(DuplicateIdError):
        create_project(projects_root, make_config())


def test_open_missing_project_fails(projects_root: Path) -> None:
    with pytest.raises(NotFoundError):
        open_project(projects_root, "PRJ-404")


def test_add_requirement_commits_and_rejects_reuse(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    add_requirement(store, make_requirement(1))
    assert commit_log()[0] == "req(PRJ-001): add REQ-0001"
    assert get_requirement(store, "REQ-0001") == make_requirement(1)
    with pytest.raises(DuplicateIdError):
        add_requirement(store, make_requirement(1))


def test_add_requirement_needs_existing_parent(store: ProjectStore) -> None:
    child = RequirementItem.model_validate(
        {**make_requirement(2).model_dump(), "parent_id": "REQ-0001"}
    )
    with pytest.raises(NotFoundError):
        add_requirement(store, child)


def test_get_missing_requirement_fails(store: ProjectStore) -> None:
    with pytest.raises(NotFoundError):
        get_requirement(store, "REQ-0009")


def test_add_document_two_versions_one_commit_each(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    before = len(commit_log())
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    assert commit_log()[0] == f"doc(PRJ-001): create {BRD} v1"
    items = (make_brd_item(BRD, 1), make_brd_item(BRD, 2))
    add_document(store, make_document(DocType.BRD, version=2), make_brd(*items))
    assert commit_log()[0] == f"doc(PRJ-001): create {BRD} v2"
    assert len(commit_log()) == before + 2
    assert get_document(store, BRD)[0].version == 2
    assert get_document(store, BRD, 1)[0].version == 1


def test_get_missing_document_or_version_fails(store: ProjectStore) -> None:
    with pytest.raises(NotFoundError):
        get_document(store, BRD)
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    with pytest.raises(NotFoundError):
        get_document(store, BRD, 5)


def test_document_files_are_stable_json(store: ProjectStore) -> None:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    path = store.path / "json" / "brd" / f"{BRD}.v1.json"
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_recommitting_unchanged_files_creates_no_commit(
    git_repo: Path, store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    path = store.path / "json" / "brd" / f"{BRD}.v1.json"
    count = len(commit_log())
    assert commit_paths(git_repo, [path], "again") is False
    assert len(commit_log()) == count


@pytest.mark.parametrize(
    "bad_doc",
    [
        Document.model_validate(
            {**make_document(DocType.BRD).model_dump(), "project_id": "PRJ-002"}
        ),
        Document.model_validate(
            {
                **make_document(DocType.BRD).model_dump(),
                "content_ref": f"other/{BRD}.v1.json",
            }
        ),
        make_document(DocType.BRD, version=3),
    ],
)
def test_add_document_rejects_inconsistent_document(store: ProjectStore, bad_doc: Document) -> None:
    with pytest.raises(InvalidDocumentError):
        add_document(store, bad_doc, make_brd(make_brd_item(BRD, 1)))


def test_add_document_rejects_wrong_payload_type(store: ProjectStore) -> None:
    payload = make_test_spec(make_test_item(BRD, 1, "TC-UT-0001", Level.UT))
    with pytest.raises(InvalidDocumentError, match="does not fit"):
        add_document(store, make_document(DocType.BRD), payload)


def test_add_document_rejects_foreign_or_duplicate_item_ids(store: ProjectStore) -> None:
    with pytest.raises(InvalidDocumentError, match="must start with"):
        add_document(
            store,
            make_document(DocType.BRD),
            make_brd(make_brd_item("DOC-BRD-0002", 1)),
        )
    with pytest.raises(InvalidDocumentError, match="duplicate item ids"):
        add_document(
            store,
            make_document(DocType.BRD),
            make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 1)),
        )


def test_test_document_enforces_level_and_unique_test_ids(store: ProjectStore) -> None:
    ut = doc_id(DocType.TEST_UT)
    doc = make_document(DocType.TEST_UT)
    with pytest.raises(InvalidDocumentError, match="not level"):
        add_document(store, doc, make_test_spec(make_test_item(ut, 1, "TC-IT-0001", Level.IT)))
    with pytest.raises(InvalidDocumentError, match="duplicate test ids"):
        add_document(
            store,
            doc,
            make_test_spec(
                make_test_item(ut, 1, "TC-UT-0001", Level.UT),
                make_test_item(ut, 2, "TC-UT-0001", Level.UT),
            ),
        )


def test_new_version_must_keep_every_item_id(store: ProjectStore) -> None:
    add_document(
        store,
        make_document(DocType.BRD),
        make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2)),
    )
    with pytest.raises(IdStabilityError, match="dropped"):
        add_document(store, make_document(DocType.BRD, version=2), make_brd(make_brd_item(BRD, 1)))


def test_removing_an_item_explicitly_is_allowed_but_not_reviving_it(store: ProjectStore) -> None:
    add_document(
        store,
        make_document(DocType.BRD),
        make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2)),
    )
    removed = make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2, status=ItemStatus.REMOVED))
    add_document(store, make_document(DocType.BRD, version=2), removed)
    revived = make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2))
    with pytest.raises(IdStabilityError, match="revived"):
        add_document(store, make_document(DocType.BRD, version=3), revived)


def test_split_item_uses_removed_plus_new_id(store: ProjectStore) -> None:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    split = make_brd(
        make_brd_item(BRD, 1, status=ItemStatus.REMOVED),
        make_brd_item(BRD, 2),
        make_brd_item(BRD, 3),
    )
    add_document(store, make_document(DocType.BRD, version=2), split)
    assert len(get_document(store, BRD)[1].items) == 3


def test_trace_link_commit_order_and_validation(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    add_requirement(store, make_requirement(1))
    add_requirement(store, make_requirement(2))
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    second = TraceLink(from_id="REQ-0002", to_id=f"{BRD}#item.1", link_type=LinkType.REALIZES)
    first = TraceLink(from_id="REQ-0001", to_id=f"{BRD}#item.1", link_type=LinkType.REALIZES)
    add_trace_link(store, second)
    assert commit_log()[0] == f"trace(PRJ-001): link REQ-0002 -> {BRD}#item.1"
    add_trace_link(store, first)
    assert get_trace_links(store) == [first, second]
    with pytest.raises(DuplicateIdError):
        add_trace_link(store, first)


def test_trace_link_needs_existing_endpoints(store: ProjectStore) -> None:
    link = TraceLink(from_id="REQ-0001", to_id="REQ-0002", link_type=LinkType.DERIVES_FROM)
    with pytest.raises(NotFoundError, match="unknown trace endpoints"):
        add_trace_link(store, link)


def test_get_trace_links_empty_by_default(store: ProjectStore) -> None:
    assert get_trace_links(store) == []


def test_decision_record_roundtrip(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    dr = DecisionRecord(
        id="DR-0007",
        date=dt.date(2026, 10, 31),
        trigger=DrTrigger.CLARIFICATION,
        description="Which SSO provider?",
        impacted_items=["REQ-0001"],
        affected_documents=[BRD],
        status=DrStatus.PROPOSED,
    )
    add_decision_record(store, dr)
    assert commit_log()[0] == "dr(PRJ-001): create DR-0007"
    assert get_decision_record(store, "DR-0007") == dr
    with pytest.raises(DuplicateIdError):
        add_decision_record(store, dr)
    with pytest.raises(NotFoundError):
        get_decision_record(store, "DR-0008")
