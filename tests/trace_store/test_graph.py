import pytest

from factories import (
    doc_id,
    make_basic,
    make_basic_item,
    make_document,
    make_requirement,
    make_srs,
    make_srs_item,
    make_test_item,
    make_test_spec,
)
from masterba.models import TraceLink
from masterba.models.enums import DocType, Level, LinkType
from masterba.trace_store import (
    ImpactNode,
    NotFoundError,
    ProjectStore,
    add_document,
    add_requirement,
    add_trace_link,
    build_graph,
    query_impact,
    rtm,
)

SRS = doc_id(DocType.SRS)
BASIC = doc_id(DocType.BASIC_DESIGN)
TEST_IT = doc_id(DocType.TEST_IT)
SRS_ITEM = f"{SRS}#item.1"
BASIC_ITEM = f"{BASIC}#item.1"
TEST_ITEM = f"{TEST_IT}#item.1"


@pytest.fixture
def chain(store: ProjectStore) -> ProjectStore:
    """REQ-0001 -> SRS item -> Basic Design item -> test case TC-IT-0001."""
    add_requirement(store, make_requirement(1))
    add_document(store, make_document(DocType.SRS), make_srs(make_srs_item(SRS, 1)))
    add_document(store, make_document(DocType.BASIC_DESIGN), make_basic(make_basic_item(BASIC, 1)))
    add_document(
        store,
        make_document(DocType.TEST_IT),
        make_test_spec(make_test_item(TEST_IT, 1, "TC-IT-0001", Level.IT)),
    )
    add_trace_link(
        store, TraceLink(from_id="REQ-0001", to_id=SRS_ITEM, link_type=LinkType.REALIZES)
    )
    add_trace_link(
        store, TraceLink(from_id=SRS_ITEM, to_id=BASIC_ITEM, link_type=LinkType.REALIZES)
    )
    add_trace_link(
        store, TraceLink(from_id=BASIC_ITEM, to_id="TC-IT-0001", link_type=LinkType.TESTS)
    )
    return store


def test_downstream_from_requirement_lists_three_nodes_in_order(chain: ProjectStore) -> None:
    assert query_impact(chain, "REQ-0001") == [
        ImpactNode(SRS_ITEM, 1, "realizes", "downstream"),
        ImpactNode(BASIC_ITEM, 2, "realizes", "downstream"),
        ImpactNode(TEST_ITEM, 3, "tests", "downstream"),
    ]


def test_upstream_from_test_id_reaches_the_requirement(chain: ProjectStore) -> None:
    nodes = query_impact(chain, "TC-IT-0001", "upstream")
    assert [n.node_id for n in nodes] == [BASIC_ITEM, SRS_ITEM, "REQ-0001"]
    assert all(n.direction == "upstream" for n in nodes)


def test_both_directions_from_the_middle(chain: ProjectStore) -> None:
    nodes = query_impact(chain, SRS_ITEM, "both")
    assert {(n.node_id, n.direction) for n in nodes} == {
        (BASIC_ITEM, "downstream"),
        (TEST_ITEM, "downstream"),
        ("REQ-0001", "upstream"),
    }


def test_impact_ignores_document_containment(chain: ProjectStore) -> None:
    ids = {n.node_id for n in query_impact(chain, TEST_ITEM, "upstream")}
    assert not ids & {SRS, BASIC, TEST_IT}


def test_impact_of_unknown_node_fails(chain: ProjectStore) -> None:
    with pytest.raises(NotFoundError):
        query_impact(chain, "REQ-0099")


def test_rtm_returns_the_full_chain(chain: ProjectStore) -> None:
    assert rtm(chain, "REQ-0001") == [["REQ-0001", SRS_ITEM, BASIC_ITEM, TEST_ITEM]]


def test_rtm_of_requirement_without_tests_is_empty(chain: ProjectStore) -> None:
    add_requirement(chain, make_requirement(2))
    assert rtm(chain, "REQ-0002") == []
    with pytest.raises(NotFoundError):
        rtm(chain, "REQ-0099")


def test_graph_has_containment_and_trace_edges(chain: ProjectStore) -> None:
    graph = build_graph(chain)
    assert graph.edges[SRS, SRS_ITEM]["kind"] == "contains"
    assert graph.edges["REQ-0001", SRS_ITEM]["kind"] == "trace"
    assert graph.nodes[TEST_ITEM]["kind"] == "test_case"
    assert "TC-IT-0001" not in graph
