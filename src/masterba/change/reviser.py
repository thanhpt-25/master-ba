"""document-reviser agent: DR + one document -> RevisionPatch (spec 07 sections 4 and 5)."""

import json
from collections.abc import Sequence

from masterba.agents.requirements_analyst import REPO_ROOT, load_system_prompt
from masterba.change.patch import ChangedItem, PatchResult, RevisionPatch
from masterba.llm import LLM, LLMResult
from masterba.models import DecisionRecord, Payload, payload_items
from masterba.models.enums import DocLanguage, DocType, ItemStatus
from masterba.rendering.bindings import item_class

PROMPT_PATH = REPO_ROOT / "agents" / "document-reviser.md"
TOOL_NAME = "submit_patch"
CHECKLIST_STEM: dict[DocType, str] = {
    DocType.BRD: "brd",
    DocType.SRS: "srs",
    DocType.BASIC_DESIGN: "basic_design",
    DocType.TEST_IT: "tests",
    DocType.TEST_ST: "tests",
    DocType.DETAIL_DESIGN: "detail_design",
    DocType.TEST_UT: "unit_tests",
}
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write every new or changed text, and every reason, in Japanese (日本語).",
    DocLanguage.EN: "Write every new or changed text, and every reason, in English.",
}


def dr_text(dr: DecisionRecord) -> str:
    parts = [f"{dr.id} [{dr.trigger.value}] {dr.description}"]
    if dr.decision:
        parts.append(f"Decision: {dr.decision}")
    if dr.rationale:
        parts.append(f"Rationale: {dr.rationale}")
    parts.append(f"Impacted items: {', '.join(dr.impacted_items) or '(none)'}")
    return "\n".join(parts)


def document_view(content: Payload) -> str:
    """Active items, one JSON object per line."""
    return "\n".join(
        json.dumps(i.model_dump(mode="json"), ensure_ascii=False)
        for i in payload_items(content)
        if i.status is ItemStatus.ACTIVE
    )


def item_fields_view(doc_type: DocType) -> str:
    props = item_class(doc_type).model_json_schema()["properties"]
    return "\n".join(
        f"- {name}: {json.dumps(spec, ensure_ascii=False)}" for name, spec in props.items()
    )


def _changed_line(change: ChangedItem) -> str:
    if change.op == "add" and change.after is not None:
        body = json.dumps(change.after.model_dump(mode="json"), ensure_ascii=False)
        return f"{change.item_id} ADD ({change.reason}): {body}"
    if change.op == "remove":
        return f"{change.item_id} REMOVE ({change.reason})"
    assert change.before is not None and change.after is not None
    old, new = change.before.model_dump(mode="json"), change.after.model_dump(mode="json")
    fields = [
        f"{k}: {json.dumps(old[k], ensure_ascii=False)} -> {json.dumps(new[k], ensure_ascii=False)}"
        for k in new
        if new[k] != old[k]
    ]
    return f"{change.item_id} UPDATE ({change.reason}): " + "; ".join(fields)


def patch_view(result: PatchResult, content: Payload) -> str:
    """What the reviewer reads: every change with its real item id, then the unchanged count."""
    touched = {c.item_id for c in result.changes}
    untouched = sum(1 for i in payload_items(content) if i.item_id not in touched)
    lines = [_changed_line(c) for c in result.changes]
    lines.append(f"Unchanged items: {untouched}")
    return "\n".join(lines)


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    return f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"


def write_patch(
    llm: LLM,
    *,
    dr: DecisionRecord,
    doc_type: DocType,
    content: Payload,
    focus: Sequence[str],
    upstream_changes: Sequence[str],
    language: DocLanguage,
    previous: RevisionPatch | None,
    feedback: Sequence[str],
    system_prompt: str | None = None,
) -> LLMResult[RevisionPatch]:
    """One reviser call: a first patch, or a corrected one after gate or QA feedback."""
    upstream = "\n".join(upstream_changes) or "(none)"
    user = (
        f"<decision_record>\n{dr_text(dr)}\n</decision_record>\n\n"
        f"<upstream_changes>\n{upstream}\n</upstream_changes>\n\n"
        f"<focus_items>\n{chr(10).join(focus) or '(none)'}\n</focus_items>\n\n"
        f"<item_fields>\n{item_fields_view(doc_type)}\n</item_fields>\n\n"
        f"<document>\n{document_view(content)}\n</document>"
    )
    if previous is not None:
        listing = "\n".join(f"- {f}" for f in feedback)
        user += (
            f"\n\n<previous_patch>\n{previous.model_dump_json(indent=2)}\n</previous_patch>\n\n"
            f"The previous patch was sent back for these reasons:\n{listing}\n"
            "Return a corrected, complete patch."
        )
    return llm.generate(
        system=system_prompt_for(language, system_prompt),
        user=user,
        output=RevisionPatch,
        tool_name=TOOL_NAME,
    )
