"""Static checks on the web app: it must stay safe by construction (spec 08 sections 4 and 6)."""

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).parents[1] / "frontend"
SCRIPTS = sorted(FRONTEND.rglob("*.js"))
FORBIDDEN = [
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
]
IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["'](\.{1,2}/[^"']+)["']""")


def test_the_expected_files_exist() -> None:
    names = {p.relative_to(FRONTEND).as_posix() for p in FRONTEND.rglob("*") if p.is_file()}
    assert {"index.html", "app.css", "app.js", "api.js", "dom.js"} <= names
    for view in (
        "login",
        "projects",
        "overview",
        "documents",
        "trace",
        "activity",
        "drs",
        "templates",
    ):
        assert f"views/{view}.js" in names


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.relative_to(FRONTEND).as_posix())
def test_no_script_can_inject_markup_or_run_strings(script: Path) -> None:
    text = script.read_text("utf-8")
    for word in FORBIDDEN:
        assert word not in text, f"{script.name} uses {word}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.relative_to(FRONTEND).as_posix())
def test_every_relative_import_resolves(script: Path) -> None:
    for target in IMPORT.findall(script.read_text("utf-8")):
        assert (script.parent / target).resolve().exists(), f"{script.name}: {target}"


def test_the_page_has_no_inline_script_or_style_and_no_external_resources() -> None:
    html = (FRONTEND / "index.html").read_text("utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert "style=" not in html
    assert "http://" not in html
    assert "https://" not in html
    css = (FRONTEND / "app.css").read_text("utf-8")
    assert "url(http" not in css
    assert "@import" not in css


def test_scripts_never_set_a_style_attribute_directly() -> None:
    for script in SCRIPTS:
        assert 'setAttribute("style"' not in script.read_text("utf-8")
