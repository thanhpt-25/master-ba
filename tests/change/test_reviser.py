import datetime as dt

from factories import login_srs_draft
from masterba.agents import checklist_path, load_checklist
from masterba.change import PatchContext, PatchOp, RevisionPatch, apply_patch
from masterba.change.reviser import (
    CHECKLIST_STEM,
    document_view,
    dr_text,
    item_fields_view,
    patch_view,
    write_patch,
)
from masterba.llm import FakeLLM
from masterba.models import DecisionRecord, SrsContent
from masterba.models.enums import DocLanguage, DocType, DrStatus, DrTrigger, ItemStatus
from masterba.pipeline import assign_srs_ids

SRS = "DOC-SRS-0001"
CONTENT = assign_srs_ids(login_srs_draft(), project_id="PRJ-001").content
DR = DecisionRecord(
    id="DR-0001",
    date=dt.date(2026, 10, 31),
    trigger=DrTrigger.REQUIREMENT_CHANGE,
    description="Password reset must also work by SMS.",
    decision="Approved for release 2.",
    impacted_items=["REQ-0002"],
    affected_documents=[SRS],
    status=DrStatus.APPROVED,
    approver="Ms. Sato",
)


def patch(*ops: PatchOp) -> RevisionPatch:
    return RevisionPatch(operations=list(ops), summary="s")


def test_dr_text_names_the_trigger_decision_and_items() -> None:
    text = dr_text(DR)
    assert (
        text.splitlines()[0] == "DR-0001 [requirement_change] Password reset must also work by SMS."
    )
    assert "Decision: Approved for release 2." in text
    assert "Impacted items: REQ-0002" in text
    assert "Rationale" not in text


def test_the_document_view_lists_only_active_items_one_json_object_per_line() -> None:
    items = list(CONTENT.items)
    items[0] = items[0].model_copy(update={"status": ItemStatus.REMOVED})
    lines = document_view(SrsContent(items=items)).splitlines()
    assert len(lines) == 3
    assert '"item_id": "DOC-SRS-0001#item.2"' in lines[0]


def test_the_item_fields_view_lists_the_fields_of_the_item_type() -> None:
    view = item_fields_view(DocType.SRS)
    assert "- statement:" in view
    assert "- derives_from:" in view


def test_every_document_type_has_an_existing_checklist() -> None:
    assert set(CHECKLIST_STEM) == {
        DocType.BRD,
        DocType.SRS,
        DocType.BASIC_DESIGN,
        DocType.TEST_IT,
        DocType.TEST_ST,
        DocType.DETAIL_DESIGN,
        DocType.TEST_UT,
    }
    for stem in set(CHECKLIST_STEM.values()):
        assert load_checklist(checklist_path(stem)).checks


def test_the_patch_view_names_real_item_ids_and_counts_unchanged_items() -> None:
    ctx = PatchContext(SRS, DocType.SRS, "DR-0001", frozenset({"REQ-0001", "REQ-0002"}), 6)
    operations = patch(
        PatchOp(
            op="update", item_id=f"{SRS}#item.2", fields={"statement": "New."}, reason="DR-0001"
        ),
        PatchOp(op="remove", item_id=f"{SRS}#item.4", reason="obsolete"),
        PatchOp(
            op="add",
            fields={
                "kind": "functional",
                "statement": "Added.",
                "derives_from": ["REQ-0001"],
                "requirement_id": "REQ-0001",
            },
            reason="new",
        ),
    )
    result = apply_patch(CONTENT, operations, ctx, {})
    lines = patch_view(result, CONTENT).splitlines()
    assert lines[0].startswith(f"{SRS}#item.2 UPDATE (DR-0001): statement: ")
    assert lines[0].endswith('-> "New."')
    assert lines[1] == f"{SRS}#item.4 REMOVE (obsolete)"
    assert lines[2].startswith(f"{SRS}#item.5 ADD (new): ")
    assert lines[3] == "Unchanged items: 2"


def test_the_first_call_carries_the_dr_the_focus_and_the_document() -> None:
    llm = FakeLLM([patch()])
    write_patch(
        llm,
        dr=DR,
        doc_type=DocType.SRS,
        content=CONTENT,
        focus=[f"{SRS}#item.2"],
        upstream_changes=["DOC-BRD-0001 v2: DOC-BRD-0001#item.2 field_changed description"],
        language=DocLanguage.EN,
        previous=None,
        feedback=[],
        system_prompt="BASE",
    )
    call = llm.calls[0]
    assert call.tool_name == "submit_patch"
    assert call.system.startswith("BASE")
    assert "English" in call.system
    assert "<decision_record>\nDR-0001 [requirement_change]" in call.user
    assert f"<focus_items>\n{SRS}#item.2\n</focus_items>" in call.user
    assert "DOC-BRD-0001 v2" in call.user
    assert "<item_fields>" in call.user
    assert f'"item_id": "{SRS}#item.1"' in call.user
    assert "previous_patch" not in call.user


def test_a_correction_call_carries_the_previous_patch_and_the_reasons() -> None:
    llm = FakeLLM([patch()])
    previous = patch(PatchOp(op="remove", item_id=f"{SRS}#item.1", reason="x"))
    write_patch(
        llm,
        dr=DR,
        doc_type=DocType.SRS,
        content=CONTENT,
        focus=[],
        upstream_changes=[],
        language=DocLanguage.JA,
        previous=previous,
        feedback=["operation 1 (remove): not allowed"],
    )
    user = llm.calls[0].user
    assert "<upstream_changes>\n(none)\n</upstream_changes>" in user
    assert "<focus_items>\n(none)\n</focus_items>" in user
    assert "<previous_patch>" in user
    assert "- operation 1 (remove): not allowed" in user
    assert "日本語" in llm.calls[0].system
