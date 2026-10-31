from pathlib import Path

from calibration_samples import brd_sample
from masterba.calibration import MappingDraft, heuristic_draft, profile_workbook
from masterba.calibration.models import ColumnMap
from masterba.calibration.suggest import suggest_mapping
from masterba.llm import FakeLLM, LLMError
from masterba.models.enums import DocType


def setup(tmp_path: Path):  # type: ignore[no-untyped-def]
    sample = brd_sample(tmp_path / "brd.xlsx")
    profile = profile_workbook(sample, DocType.BRD)
    return profile, heuristic_draft(profile, DocType.BRD, sample)


def with_field(draft: MappingDraft, col: str, field: str | None) -> MappingDraft:
    table = draft.tables[0]
    columns = [c.model_copy(update={"field": field}) if c.col == col else c for c in table.columns]
    return draft.model_copy(update={"tables": [table.model_copy(update={"columns": columns})]})


def test_a_valid_model_mapping_replaces_the_heuristic_one(tmp_path: Path) -> None:
    profile, heuristic = setup(tmp_path)
    better = with_field(heuristic, "F", "source_ref")

    outcome = suggest_mapping(FakeLLM([better]), profile, heuristic, DocType.BRD)

    assert outcome.used_model
    assert {c.col: c.field for c in outcome.draft.tables[0].columns}["F"] == "source_ref"


def test_an_invalid_mapping_is_retried_once_then_the_heuristic_is_kept(tmp_path: Path) -> None:
    profile, heuristic = setup(tmp_path)
    bad = with_field(heuristic, "F", "invented_field")
    llm = FakeLLM([bad, bad])

    outcome = suggest_mapping(llm, profile, heuristic, DocType.BRD)

    assert not outcome.used_model and outcome.draft == heuristic
    assert "rejected" in (outcome.message or "")
    assert "was rejected" in llm.calls[1].user


def test_a_model_failure_falls_back_to_the_heuristic(tmp_path: Path) -> None:
    profile, heuristic = setup(tmp_path)

    outcome = suggest_mapping(FakeLLM([LLMError("down")]), profile, heuristic, DocType.BRD)

    assert not outcome.used_model and outcome.draft == heuristic


def test_sample_text_reaches_the_model_only_as_tagged_data(tmp_path: Path) -> None:
    profile, heuristic = setup(tmp_path)
    llm = FakeLLM([heuristic])

    suggest_mapping(llm, profile, heuristic, DocType.BRD)

    assert "<sample_profile>" in llm.calls[0].user and "<item_fields>" in llm.calls[0].user
    assert llm.calls[0].tool_name == "submit_mapping"
    assert isinstance(ColumnMap(col="A"), ColumnMap)
