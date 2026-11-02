"""Knowledge trace and DR proposals (Requirements 13.1, 13.3-13.9)."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from factories import draft_for, intake_path, make_config, qa_block, qa_pass
from kbhelpers import head, keyword_backend, md
from masterba.agents import BrdDraft
from masterba.knowledge import FakeRetriever, KnowledgeSession, add_sources, proposal
from masterba.knowledge.errors import KbCommitError
from masterba.knowledge.proposal import remove_with_proposal, replace_with_proposal
from masterba.knowledge.store import kb_paths, read_manifest
from masterba.llm import FakeLLM
from masterba.models import KbCitation, Passage
from masterba.models.enums import DrTrigger, TeamRunStatus
from masterba.pipeline import run_brd
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    create_project,
    get_trace_links,
    knowledge_nodes,
    query_impact,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"
REF = "KB-0001#chunk.1"


def _session() -> KnowledgeSession:
    fake = FakeRetriever([Passage(chunk_ref=REF, text="受注", score=1.0)], match_all=True)
    return KnowledgeSession(
        retriever=fake,
        indexed=frozenset({"KB-0001"}),
        manifest_ids=frozenset({"KB-0001", "KB-0002"}),
        chunk_text={REF: "受注"}.get,
        covers_manifest=lambda: True,
    )


def _cited() -> BrdDraft:
    draft = draft_for(LOGIN)
    reqs = [
        r.model_copy(
            update={"kb_citations": [KbCitation(chunk_ref=REF), KbCitation(chunk_ref=REF)]}
        )
        if n < 2
        else r
        for n, r in enumerate(draft.requirements)
    ]
    return draft.model_copy(update={"requirements": reqs})


def _with_cited_brd(store: ProjectStore, qa: list[object] | None = None) -> TeamRunStatus:
    add_sources(store, [md("a.md", "受注"), md("b.md", "出荷")], "u", backend=keyword_backend())
    session = _session()
    result = run_brd(
        store,
        TEMPLATES,
        FakeLLM([_cited()]),
        intake_path(LOGIN),
        qa_llm=FakeLLM(qa or [qa_pass()]),  # type: ignore[arg-type]
        knowledge=lambda s: session,
    )
    return result.status


def test_done_run_stores_nodes_and_links_in_the_document_commit(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    assert _with_cited_brd(store) is TeamRunStatus.DONE
    assert knowledge_nodes(store) == ["KB-0001"]
    links = [x for x in get_trace_links(store) if x.from_id == "KB-0001"]
    assert [(x.to_id, x.link_type.value) for x in links] == [
        ("DOC-BRD-0001#item.1", "derives_from"),
        ("DOC-BRD-0001#item.2", "derives_from"),
    ]

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=store.root, capture_output=True, text=True, check=True
        )
        return done.stdout

    subject = "doc(PRJ-001): create DOC-BRD-0001 v1"
    sha = git("log", "--fixed-strings", f"--grep={subject}", "--format=%H").split()[0]
    files = git("show", "--name-only", "--format=", sha).split()
    assert "projects/PRJ-001/traceability/knowledge-nodes.json" in files
    assert "projects/PRJ-001/traceability/links.json" in files
    impact = query_impact(store, "KB-0001")
    assert [n.node_id for n in impact][:2] == ["DOC-BRD-0001#item.1", "DOC-BRD-0001#item.2"]
    assert len({n.node_id for n in impact}) == len(impact)
    with pytest.raises(NotFoundError, match="no Knowledge_Node exists for KB-0002"):
        query_impact(store, "KB-0002")


def test_escalated_run_writes_no_node(projects_root: Path) -> None:
    store = create_project(projects_root, make_config(max_rounds=1))
    assert _with_cited_brd(store, [qa_block()]) is TeamRunStatus.ESCALATED
    assert knowledge_nodes(store) == []


def test_replace_and_remove_of_a_cited_source_propose_a_dr(store: ProjectStore) -> None:
    _with_cited_brd(store)
    before = read_manifest(store).sources[0]
    report, dr = replace_with_proposal(
        store, "KB-0001", md("a2.md", "受注 改訂"), "sato", backend=keyword_backend()
    )
    assert dr is not None and dr.trigger is DrTrigger.KNOWLEDGE_CHANGE
    assert dr.impacted_items == ["DOC-BRD-0001#item.1", "DOC-BRD-0001#item.2"]
    assert before.sha256 in dr.description and report.after.sha256 in dr.description
    assert "a.md" in dr.description and "a2.md" in dr.description
    subjects = subprocess.run(
        ["git", "log", "-2", "--format=%s"],
        cwd=store.root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    assert subjects[:2] == ["kb(PRJ-001): replace KB-0001", f"dr(PRJ-001): create {dr.id}"]
    removed, dr2 = remove_with_proposal(store, "KB-0001", backend=keyword_backend())
    assert removed.removed and dr2 is not None and "removed" in dr2.description
    assert knowledge_nodes(store) == ["KB-0001"]  # removal keeps the node and links
    assert any(x.from_id == "KB-0001" for x in get_trace_links(store))


def test_uncited_source_makes_no_dr(store: ProjectStore) -> None:
    _with_cited_brd(store)
    _, dr = remove_with_proposal(store, "KB-0002", backend=keyword_backend())
    assert dr is None


def test_failed_dr_changes_nothing(store: ProjectStore, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_cited_brd(store)
    paths = kb_paths(store)
    snapshot = (
        head(store.root),
        paths.manifest.read_bytes(),
        sorted(p.name for p in paths.sources.iterdir()),
        json.dumps([x.model_dump(mode="json") for x in get_trace_links(store)]),
    )

    def boom(*args: object, **kwargs: object) -> None:
        raise ValueError("dr store broken")

    monkeypatch.setattr(proposal, "new_dr", boom)
    with pytest.raises(ValueError, match="dr store broken"):
        replace_with_proposal(
            store, "KB-0001", md("x.md", "新しい"), "u", backend=keyword_backend()
        )
    with pytest.raises(ValueError):
        remove_with_proposal(store, "KB-0001", backend=keyword_backend())
    after = (
        head(store.root),
        paths.manifest.read_bytes(),
        sorted(p.name for p in paths.sources.iterdir()),
        json.dumps([x.model_dump(mode="json") for x in get_trace_links(store)]),
    )
    assert after == snapshot


def test_manifest_failure_after_dr_names_the_dr(
    store: ProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_cited_brd(store)
    from masterba.knowledge import store as kb

    def fail(*args: object) -> bool:
        raise RuntimeError("no space")

    monkeypatch.setattr(kb, "commit_paths", fail)
    with pytest.raises(KbCommitError, match="DR-0001 was created"):
        remove_with_proposal(store, "KB-0001", backend=keyword_backend())
