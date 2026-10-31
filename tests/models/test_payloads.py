import pytest
from pydantic import ValidationError

from factories import make_brd, make_brd_item, make_test_item, make_test_spec
from masterba.models import BrdContent, TestExclusion, TestSpecContent, payload_items
from masterba.models.enums import DocType, Level
from masterba.models.payloads import LEVEL_BY_TEST_TYPE, PAYLOAD_BY_TYPE


def test_every_doc_type_has_a_payload_class() -> None:
    assert set(PAYLOAD_BY_TYPE) == set(DocType)


def test_every_test_doc_type_maps_to_a_level() -> None:
    assert LEVEL_BY_TEST_TYPE == {
        DocType.TEST_IT: Level.IT,
        DocType.TEST_ST: Level.ST,
        DocType.TEST_UT: Level.UT,
        DocType.TEST_UAT: Level.UAT,
    }


def test_payload_items_returns_items() -> None:
    doc = "DOC-BRD-0001"
    content = make_brd(make_brd_item(doc, 1), make_brd_item(doc, 2))
    assert [i.item_id for i in payload_items(content)] == [f"{doc}#item.1", f"{doc}#item.2"]


def test_item_id_must_be_an_item_ref() -> None:
    with pytest.raises(ValidationError):
        BrdContent.model_validate(
            {
                "items": [
                    {
                        "item_id": "DOC-BRD-0001",
                        "requirement_id": "REQ-0001",
                        "title": "t",
                        "description": "d",
                        "scope": "in",
                        "source_ref": "s",
                    }
                ]
            }
        )


def test_test_case_requires_valid_test_id() -> None:
    item = make_test_item("DOC-TEST_UT-0001", 1, "TC-UT-0001", Level.UT)
    assert make_test_spec(item).items[0].test_id == "TC-UT-0001"
    with pytest.raises(ValidationError):
        make_test_item("DOC-TEST_UT-0001", 1, "TC-9-1", Level.UT)


def test_test_spec_exclusions_default_to_empty_and_round_trip() -> None:
    assert TestSpecContent.model_validate({"items": []}).exclusions == []
    content = TestSpecContent(
        items=[],
        exclusions=[
            TestExclusion(item_ref="DOC-BASIC_DESIGN-0001#item.2", reason="Not testable yet.")
        ],
    )
    assert TestSpecContent.model_validate(content.model_dump(mode="json")) == content
    with pytest.raises(ValidationError):
        TestExclusion(item_ref="DOC-BASIC_DESIGN-0001#item.2", reason="")
