"""Smoke checks for spec 12 (Requirements 8.1, 11.1, 11.2, 15.1, 15.3)."""

import importlib
import pkgutil
import subprocess
import sys
import tomllib
from pathlib import Path

import masterba
from masterba.agents.qa_reviewer import checklist_path, load_checklist

REPO = Path(__file__).parents[1]
RAG = ("sentence-transformers", "lancedb", "huggingface-hub")
CHECKLISTS = ("brd", "srs", "basic_design", "detail_design", "tests", "unit_tests")


def test_rag_packages_are_only_in_the_extra() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))["project"]
    base = " ".join(project["dependencies"])
    assert not any(name in base for name in RAG)
    extra = " ".join(project["optional-dependencies"]["rag"])
    assert all(name in extra for name in RAG)


def test_every_module_imports_without_the_rag_packages() -> None:
    # `__main__` modules run the CLI when imported, so they are left out.
    names = [
        m.name
        for m in pkgutil.walk_packages(masterba.__path__, "masterba.")
        if not m.name.endswith("__main__")
    ]
    code = (
        "import sys\n"
        "for blocked in ('lancedb', 'sentence_transformers', 'huggingface_hub'):\n"
        "    sys.modules[blocked] = None\n"
        "import importlib\n"
        f"for name in {names!r}:\n"
        "    importlib.import_module(name)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert importlib.import_module("masterba.knowledge")


def test_every_checklist_has_the_contradiction_check() -> None:
    for name in CHECKLISTS:
        checks = [c for c in load_checklist(checklist_path(name)).checks if c.requires_reference]
        assert len(checks) == 1, name
        assert checks[0].severity == "blocking"
        assert "contradicts a passage in the knowledge block" in checks[0].text
        assert (
            "A statement on a subject no passage mentions is not a contradiction" in checks[0].text
        )
