# Feature: local-rag, Property 23: Contradiction normalisation
from hypothesis import given
from hypothesis import strategies as st

from masterba.agents.qa_reviewer import QaIssue, QaReport, normalise_contradictions

_refs = st.sampled_from(["KB-0001#chunk.1", "KB-0001#chunk.2", "KB-0002#chunk.1"])
_issues = st.builds(
    QaIssue,
    checklist_id=st.sampled_from(["BRD-KB", "BRD-01"]),
    severity=st.sampled_from(["blocking", "advisory"]),
    ref=st.sampled_from([None, "DOC-BRD-0001#item.1"]),
    message=st.just("m"),
    action_required=st.just("fix"),
    chunk_refs=st.lists(_refs, max_size=2, unique=True),
)


@given(st.lists(_issues, max_size=6), st.sets(_refs).map(frozenset))
def test_normalise_contradictions(issues: list[QaIssue], block: frozenset[str]) -> None:
    report = QaReport(issues=issues)
    out, notes = normalise_contradictions(report, frozenset({"BRD-KB"}), block)
    downgraded = 0
    for before, after in zip(issues, out.issues, strict=True):
        should = (
            before.severity == "blocking"
            and before.checklist_id == "BRD-KB"
            and not set(before.chunk_refs) & block
        )
        if should:
            downgraded += 1
            assert after == before.model_copy(update={"severity": "advisory"})
        else:
            assert after == before
    assert len(notes) == downgraded
    assert all("downgraded (no cited passage in the block" in n for n in notes)
    assert normalise_contradictions(out, frozenset({"BRD-KB"}), block) == (out, [])
