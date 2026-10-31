import pytest

from masterba.change import V_ORDER, Impact, analyse_impact
from masterba.change.impact import resolve_node
from masterba.models.enums import DocType, DrTrigger
from masterba.trace_store import NotFoundError, ProjectStore

ALL_DOCS = (
    "DOC-BRD-0001",
    "DOC-SRS-0001",
    "DOC-BASIC_DESIGN-0001",
    "DOC-TEST_IT-0001",
    "DOC-TEST_ST-0001",
    "DOC-DETAIL_DESIGN-0001",
    "DOC-TEST_UT-0001",
)


def test_v_order_puts_each_test_after_the_design_it_checks() -> None:
    assert V_ORDER == (
        DocType.BRD,
        DocType.SRS,
        DocType.BASIC_DESIGN,
        DocType.TEST_IT,
        DocType.TEST_ST,
        DocType.DETAIL_DESIGN,
        DocType.TEST_UT,
    )


def test_a_requirement_change_reaches_every_document_in_v_order(chain: ProjectStore) -> None:
    impact = analyse_impact(chain, ["REQ-0002"], DrTrigger.REQUIREMENT_CHANGE)
    assert impact.documents == ALL_DOCS
    nodes = {e.node_id for e in impact.entries}
    assert "DOC-BRD-0001#item.2" in nodes
    assert "DOC-SRS-0001#item.2" in nodes
    assert "DOC-BASIC_DESIGN-0001#item.3" in nodes
    assert "DOC-TEST_UT-0001#item.3" in nodes
    assert all(e.direction == "downstream" for e in impact.entries)


def test_an_item_in_the_middle_only_reaches_what_is_below_and_its_own_document(
    chain: ProjectStore,
) -> None:
    impact = analyse_impact(chain, ["DOC-BASIC_DESIGN-0001#item.3"], DrTrigger.DESIGN_CHANGE)
    assert impact.documents == (
        "DOC-BASIC_DESIGN-0001",
        "DOC-TEST_IT-0001",
        "DOC-DETAIL_DESIGN-0001",
        "DOC-TEST_UT-0001",
    )


def test_a_defect_follows_the_chain_upstream_as_well(chain: ProjectStore) -> None:
    impact = analyse_impact(chain, ["TC-UT-0003"], DrTrigger.DEFECT)
    assert impact.documents == (
        "DOC-SRS-0001",
        "DOC-BASIC_DESIGN-0001",
        "DOC-DETAIL_DESIGN-0001",
        "DOC-TEST_UT-0001",
    )
    assert {e.direction for e in impact.entries} == {"upstream"}
    assert "REQ-0002" in {e.node_id for e in impact.entries}


def test_the_result_is_stable_and_round_trips_through_json(chain: ProjectStore) -> None:
    first = analyse_impact(chain, ["REQ-0001", "REQ-0002"], DrTrigger.REQUIREMENT_CHANGE)
    second = analyse_impact(chain, ["REQ-0002", "REQ-0001"], DrTrigger.REQUIREMENT_CHANGE)
    assert first.documents == second.documents
    assert Impact.from_json(first.to_json()) == first


def test_nodes_are_reported_once_even_when_reached_from_several_items(chain: ProjectStore) -> None:
    impact = analyse_impact(chain, ["REQ-0001", "REQ-0002"], DrTrigger.REQUIREMENT_CHANGE)
    ids = [e.node_id for e in impact.entries]
    assert len(ids) == len(set(ids))


def test_test_case_ids_resolve_to_their_item_refs(chain: ProjectStore) -> None:
    assert resolve_node(chain, "TC-IT-0002") == "DOC-TEST_IT-0001#item.2"
    assert resolve_node(chain, "REQ-0001") == "REQ-0001"


def test_unknown_nodes_are_rejected(chain: ProjectStore) -> None:
    with pytest.raises(NotFoundError):
        resolve_node(chain, "REQ-0099")
    with pytest.raises(NotFoundError):
        resolve_node(chain, "TC-IT-0099")
    with pytest.raises(NotFoundError):
        analyse_impact(chain, ["DOC-SRS-0001#item.99"], DrTrigger.DEFECT)
