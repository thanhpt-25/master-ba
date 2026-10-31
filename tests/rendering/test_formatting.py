from masterba.models.enums import Scope
from masterba.rendering.formatting import format_value


def test_text_int_and_none() -> None:
    assert format_value("title", "Sign in") == "Sign in"
    assert format_value("version", 3) == 3
    assert format_value("acceptance_hint", None) is None


def test_enum_uses_value_map_and_falls_back_to_its_value() -> None:
    assert format_value("scope", Scope.IN, {"in": "対象"}) == "対象"
    assert format_value("scope", Scope.OUT, {"in": "対象"}) == "out"


def test_steps_are_numbered_and_other_lists_are_one_per_line() -> None:
    assert format_value("steps", ["Open", "Submit"]) == "1. Open\n2. Submit"
    assert format_value("realizes", ["REQ-0001", "REQ-0002"]) == "REQ-0001\nREQ-0002"


def test_empty_list_is_a_blank_cell() -> None:
    assert format_value("realizes", []) is None


def test_bool_is_stored_as_text() -> None:
    assert format_value("flag", True) == "True"
