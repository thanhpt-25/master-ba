import re

import pytest

from masterba.change import (
    PatchContext,
    PatchError,
    PatchOp,
    RevisionPatch,
    apply_patch,
    validate_patch,
)
from masterba.change.patch import max_item_number
from masterba.change.propagate import active_node_ids
from masterba.models import (
    BasicDesignContent,
    BrdContent,
    RequirementItem,
    SrsContent,
    TestSpecContent,
)
from masterba.models.enums import DocType, ItemStatus
from masterba.pipeline.brd import next_requirement_number
from masterba.trace_store import ProjectStore, get_document, list_requirements

SRS = "DOC-SRS-0001"
BRD = "DOC-BRD-0001"


def op(
    action: str, item_id: str | None = None, /, *, reason: str = "DR-0001", **fields: object
) -> PatchOp:
    return PatchOp.model_validate(
        {"op": action, "item_id": item_id, "fields": fields, "reason": reason}
    )


def patch(*ops: PatchOp) -> RevisionPatch:
    return RevisionPatch(operations=list(ops), summary="test")


def context(store: ProjectStore, doc_id: str, doc_type: DocType) -> PatchContext:
    return PatchContext(
        doc_id=doc_id,
        doc_type=doc_type,
        dr_id="DR-0001",
        active_nodes=active_node_ids(store),
        next_req_number=next_requirement_number(list_requirements(store)),
    )


def reqs(store: ProjectStore) -> dict[str, RequirementItem]:
    return {r.id: r for r in list_requirements(store)}


def test_an_update_changes_only_the_named_fields_and_leaves_other_items_identical(
    chain: ProjectStore,
) -> None:
    _, content = get_document(chain, SRS)
    assert isinstance(content, SrsContent)
    ctx = context(chain, SRS, DocType.SRS)
    new_statement = "The system shall also let a customer reset a password by SMS."
    result = apply_patch(
        content, patch(op("update", f"{SRS}#item.2", statement=new_statement)), ctx, reqs(chain)
    )
    assert isinstance(result.content, SrsContent)
    assert result.content.items[1].statement == new_statement
    assert result.content.items[1].acceptance_hint == content.items[1].acceptance_hint
    for n in (0, 2, 3):
        assert result.content.items[n] == content.items[n]
    assert [c.op for c in result.changes] == ["update"]


def test_remove_marks_the_item_removed_and_its_number_is_never_reused(chain: ProjectStore) -> None:
    _, content = get_document(chain, SRS)
    assert isinstance(content, SrsContent)
    ctx = context(chain, SRS, DocType.SRS)
    removed = apply_patch(content, patch(op("remove", f"{SRS}#item.4")), ctx, reqs(chain))
    assert isinstance(removed.content, SrsContent)
    assert removed.content.items[3].status is ItemStatus.REMOVED
    assert len(removed.content.items) == 4
    added = apply_patch(
        removed.content,
        patch(
            op(
                "add",
                kind="functional",
                statement="The system shall export orders.",
                derives_from=["REQ-0004"],
                requirement_id="REQ-0004",
            )
        ),
        ctx,
        reqs(chain),
    )
    assert isinstance(added.content, SrsContent)
    assert added.content.items[-1].item_id == f"{SRS}#item.5"
    assert max_item_number(added.content) == 5


def test_adding_a_brd_item_creates_the_next_requirement(chain: ProjectStore) -> None:
    _, content = get_document(chain, BRD)
    assert isinstance(content, BrdContent)
    ctx = context(chain, BRD, DocType.BRD)
    result = apply_patch(
        content,
        patch(
            op("add", title="Export", description="Export orders.", scope="in", category="business")
        ),
        ctx,
        reqs(chain),
    )
    assert isinstance(result.content, BrdContent)
    created = result.content.items[-1]
    assert (created.item_id, created.requirement_id, created.source_ref) == (
        f"{BRD}#item.6",
        "REQ-0006",
        "DR-0001",
    )
    [requirement] = result.new_requirements
    assert (requirement.id, requirement.text, requirement.category.value) == (
        "REQ-0006",
        "Export orders.",
        "business",
    )


def test_a_brd_description_change_updates_the_requirement_text_and_removal_marks_it(
    chain: ProjectStore,
) -> None:
    _, content = get_document(chain, BRD)
    assert isinstance(content, BrdContent)
    ctx = context(chain, BRD, DocType.BRD)
    changed = apply_patch(
        content,
        patch(op("update", f"{BRD}#item.2", description="Reset by email or SMS.")),
        ctx,
        reqs(chain),
    )
    [updated] = changed.updated_requirements
    assert (updated.id, updated.text) == ("REQ-0002", "Reset by email or SMS.")
    removed = apply_patch(content, patch(op("remove", f"{BRD}#item.2")), ctx, reqs(chain))
    assert removed.updated_requirements[0].status is ItemStatus.REMOVED


def test_a_new_test_case_gets_the_next_test_id_and_the_documents_level(chain: ProjectStore) -> None:
    _, content = get_document(chain, "DOC-TEST_IT-0001")
    assert isinstance(content, TestSpecContent)
    ctx = context(chain, "DOC-TEST_IT-0001", DocType.TEST_IT)
    result = apply_patch(
        content,
        patch(
            op(
                "add",
                precondition="p",
                input="i",
                steps=["Open", "Submit"],
                expected="ok",
                verifies=["DOC-BASIC_DESIGN-0001#item.3"],
            )
        ),
        ctx,
        reqs(chain),
    )
    assert isinstance(result.content, TestSpecContent)
    case = result.content.items[-1]
    assert (case.item_id, case.test_id, case.level.value) == (
        "DOC-TEST_IT-0001#item.6",
        "TC-IT-0006",
        "IT",
    )
    assert result.content.exclusions == content.exclusions


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (op("update", f"{SRS}#item.1", color="red"), "cannot change ['color']"),
        (
            op("update", f"{SRS}#item.1", requirement_id="REQ-0002"),
            "cannot change ['requirement_id']",
        ),
        (op("update", f"{SRS}#item.1", status="removed"), "cannot change ['status']"),
        (op("update", f"{SRS}#item.1"), "cannot change"),
        (op("update", f"{SRS}#item.1", kind="loud"), "operation 1 (update)"),
        (op("update", f"{SRS}#item.9", statement="x"), "is not an item of"),
        (op("remove", f"{SRS}#item.9"), "is not an item of"),
        (
            op(
                "add",
                item_id="x",
                kind="functional",
                statement="s",
                derives_from=["REQ-0001"],
                requirement_id="REQ-0001",
            ),
            "assigned by the system",
        ),
        (
            op("add", kind="functional", statement="s", derives_from=["REQ-0001"]),
            "operation 1 (add)",
        ),
        (
            op("update", f"{SRS}#item.1", derives_from=["REQ-0099"]),
            "reference REQ-0099 is not an active node",
        ),
    ],
)
def test_invalid_operations_are_rejected_with_a_clear_message(
    chain: ProjectStore, operation: PatchOp, message: str
) -> None:
    _, content = get_document(chain, SRS)
    ctx = context(chain, SRS, DocType.SRS)
    with pytest.raises(PatchError, match=re.escape(message)):
        apply_patch(content, patch(operation), ctx, reqs(chain))


def test_an_item_cannot_be_changed_twice_or_after_removal(chain: ProjectStore) -> None:
    _, content = get_document(chain, SRS)
    ctx = context(chain, SRS, DocType.SRS)
    twice = patch(op("update", f"{SRS}#item.1", statement="a"), op("remove", f"{SRS}#item.1"))
    errors = validate_patch(content, twice, ctx, reqs(chain))
    assert errors == [f"operation 2 (remove): {SRS}#item.1 is changed twice in one patch"]
    removed = apply_patch(content, patch(op("remove", f"{SRS}#item.1")), ctx, reqs(chain))
    again = validate_patch(
        removed.content, patch(op("update", f"{SRS}#item.1", statement="b")), ctx, reqs(chain)
    )
    assert again == [f"operation 1 (update): {SRS}#item.1 is not active"]


def test_references_to_the_items_of_the_same_patch_are_not_dangling(chain: ProjectStore) -> None:
    _, content = get_document(chain, "DOC-BASIC_DESIGN-0001")
    assert isinstance(content, BasicDesignContent)
    ctx = context(chain, "DOC-BASIC_DESIGN-0001", DocType.BASIC_DESIGN)
    good = patch(
        op(
            "add",
            kind="function",
            name="Audit",
            description="Logs sign-ins.",
            realizes=[f"{SRS}#item.1"],
        )
    )
    assert validate_patch(content, good, ctx, reqs(chain)) == []
    bad = patch(
        op("add", kind="function", name="Audit", description="d", realizes=[f"{SRS}#item.9"])
    )
    assert validate_patch(content, bad, ctx, reqs(chain)) == [
        f"DOC-BASIC_DESIGN-0001#item.6: reference {SRS}#item.9 is not an active node"
    ]


def test_an_empty_patch_changes_nothing(chain: ProjectStore) -> None:
    _, content = get_document(chain, SRS)
    ctx = context(chain, SRS, DocType.SRS)
    result = apply_patch(content, patch(), ctx, reqs(chain))
    assert result.content == content
    assert result.changes == ()
