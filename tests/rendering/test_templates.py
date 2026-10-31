import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from masterba.models.enums import DocType
from masterba.rendering import (
    InvalidTemplateError,
    TemplateNotFoundError,
    load_template,
    resolve_template,
)
from masterba.rendering.catalog import CATALOG
from masterba.rendering.shells import write_default_templates

TEMPLATES = Path(__file__).parents[2] / "templates"


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    target = tmp_path / "templates"
    shutil.copytree(TEMPLATES, target)
    return target


def edit_json(path: Path, mutate: Callable[[dict[str, Any]], object]) -> None:
    data = json.loads(path.read_text("utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("doc_type", list(DocType))
def test_every_default_template_loads(doc_type: DocType) -> None:
    template = load_template(TEMPLATES / "default" / f"{doc_type.value}.template.json")
    assert template.definition.doc_type is doc_type
    assert template.shell_path.exists()


def test_there_are_exactly_16_default_files() -> None:
    files = [
        *(TEMPLATES / "default").glob("*.template.json"),
        *(TEMPLATES / "default").glob("*.xlsx"),
    ]
    assert len(files) == 16
    assert {spec.doc_type for spec in CATALOG} == set(DocType)


def test_committed_templates_match_the_generator(tmp_path: Path) -> None:
    write_default_templates(tmp_path)
    for spec in CATALOG:
        name = spec.doc_type.value
        committed_json = (TEMPLATES / "default" / f"{name}.template.json").read_text("utf-8")
        assert committed_json == (tmp_path / f"{name}.template.json").read_text("utf-8")
        committed = load_workbook(TEMPLATES / "default" / f"{name}.xlsx")
        fresh = load_workbook(tmp_path / f"{name}.xlsx")
        assert committed.sheetnames == fresh.sheetnames
        for sheet in committed.sheetnames:
            a, b = committed[sheet], fresh[sheet]
            assert [[c.value for c in row] for row in a.iter_rows()] == [
                [c.value for c in row] for row in b.iter_rows()
            ]
            assert {k: d.width for k, d in a.column_dimensions.items()} == {
                k: d.width for k, d in b.column_dimensions.items()
            }


def test_binding_to_an_unknown_item_field_fails_at_load(templates: Path) -> None:
    path = templates / "default" / "BRD.template.json"

    def mutate(data: dict[str, Any]) -> None:
        text = json.dumps(data).replace('"title"', '"no_such_field"')
        data.update(json.loads(text))

    edit_json(path, mutate)
    with pytest.raises(InvalidTemplateError, match="no_such_field"):
        load_template(path)


def test_binding_to_a_sheet_missing_from_sheet_map_fails_at_load(templates: Path) -> None:
    path = templates / "default" / "SRS.template.json"
    edit_json(path, lambda data: data["sheet_map"].pop("functional"))
    with pytest.raises(InvalidTemplateError, match="not in sheet_map"):
        load_template(path)


def test_unknown_header_source_fails_at_load(templates: Path) -> None:
    path = templates / "default" / "SRS.template.json"
    edit_json(path, lambda d: d["cell_bindings"]["header"][0].update(source="$secret"))
    with pytest.raises(InvalidTemplateError, match="unknown header source"):
        load_template(path)


def test_unknown_validation_rule_fails_at_load(templates: Path) -> None:
    path = templates / "default" / "SRS.template.json"
    edit_json(path, lambda d: d.update(validation_rules=[{"rule": "run_code"}]))
    with pytest.raises(InvalidTemplateError):
        load_template(path)


def test_file_name_must_match_doc_type(templates: Path) -> None:
    wrong = templates / "default" / "SRS.template.json"
    shutil.copy(TEMPLATES / "default" / "BRD.template.json", wrong)
    with pytest.raises(InvalidTemplateError, match="does not match"):
        load_template(wrong)


def test_missing_shell_fails_at_load(templates: Path) -> None:
    (templates / "default" / "TEST_UAT.xlsx").unlink()
    with pytest.raises(InvalidTemplateError, match="missing workbook shell"):
        load_template(templates / "default" / "TEST_UAT.template.json")


def make_company(templates: Path, source: str, confirmed: bool) -> Path:
    company = templates / "companies" / "acme"
    company.mkdir(parents=True)
    for suffix in (".xlsx", ".template.json"):
        shutil.copy(TEMPLATES / "default" / f"BRD{suffix}", company / f"BRD{suffix}")
    edit_json(
        company / "BRD.template.json",
        lambda d: d.update(company_id="acme", source=source),
    )
    if confirmed:
        (company / "BRD.confirmed").write_text("", encoding="utf-8")
    return company


def test_default_company_uses_the_default_template() -> None:
    assert resolve_template(TEMPLATES, "default", DocType.BRD).definition.company_id == "default"


def test_confirmed_calibrated_company_template_wins(templates: Path) -> None:
    make_company(templates, "calibrated_from_sample", confirmed=True)
    assert resolve_template(templates, "acme", DocType.BRD).definition.company_id == "acme"


def test_unconfirmed_calibrated_company_template_is_ignored(templates: Path) -> None:
    make_company(templates, "calibrated_from_sample", confirmed=False)
    assert resolve_template(templates, "acme", DocType.BRD).definition.company_id == "default"


def test_baseline_company_template_needs_no_confirmation(templates: Path) -> None:
    make_company(templates, "baseline", confirmed=False)
    assert resolve_template(templates, "acme", DocType.BRD).definition.company_id == "acme"


def test_company_without_template_falls_back_to_default(templates: Path) -> None:
    assert resolve_template(templates, "other", DocType.SRS).definition.company_id == "default"


def test_no_template_anywhere_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TemplateNotFoundError):
        resolve_template(tmp_path, "default", DocType.BRD)


@pytest.mark.parametrize("company_id", ["../evil", "a/b", "..", ""])
def test_company_id_cannot_escape_the_templates_folder(company_id: str) -> None:
    with pytest.raises(InvalidTemplateError, match="invalid company id"):
        resolve_template(TEMPLATES, company_id, DocType.BRD)
