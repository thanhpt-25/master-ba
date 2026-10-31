from pathlib import Path

from masterba.schema_export import SCHEMA_DIR, render_schemas, write_schemas


def test_committed_schemas_match_the_models() -> None:
    expected = render_schemas()
    committed = {p.name: p.read_text(encoding="utf-8") for p in SCHEMA_DIR.glob("*.schema.json")}
    assert committed == expected, "run: PYTHONPATH=src uv run python -m masterba.schema_export"


def test_write_schemas_creates_every_file(tmp_path: Path) -> None:
    written = write_schemas(tmp_path / "out")
    assert {p.name for p in written} == set(render_schemas())
    assert all(p.read_text(encoding="utf-8").endswith("\n") for p in written)
