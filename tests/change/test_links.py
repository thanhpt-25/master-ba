from masterba.change import links_for_document, missing_links
from masterba.models import SrsContent, TraceLink
from masterba.models.enums import ItemStatus, LinkType
from masterba.trace_store import ProjectStore, get_document, get_trace_links, latest_documents

SRS = "DOC-SRS-0001"


def test_links_for_every_document_reproduce_what_the_pipelines_wrote(chain: ProjectStore) -> None:
    wanted: set[TraceLink] = set()
    for _, content in latest_documents(chain):
        wanted.update(links_for_document(content))
    assert wanted == set(get_trace_links(chain))
    assert len(wanted) == 5 + 4 + 14 + 11


def test_removed_items_imply_no_links(chain: ProjectStore) -> None:
    _, content = get_document(chain, SRS)
    assert isinstance(content, SrsContent)
    items = list(content.items)
    items[0] = items[0].model_copy(update={"status": ItemStatus.REMOVED})
    shrunk = SrsContent(items=items)
    assert len(links_for_document(shrunk)) == len(links_for_document(content)) - 1


def test_missing_links_keeps_order_and_skips_existing() -> None:
    a = TraceLink(from_id="REQ-0001", to_id=f"{SRS}#item.1", link_type=LinkType.REALIZES)
    b = TraceLink(from_id="REQ-0002", to_id=f"{SRS}#item.2", link_type=LinkType.REALIZES)
    c = TraceLink(from_id="REQ-0003", to_id=f"{SRS}#item.3", link_type=LinkType.REALIZES)
    assert missing_links([b], [a, b, c]) == [a, c]
    assert missing_links([a, b, c], [a, b, c]) == []
