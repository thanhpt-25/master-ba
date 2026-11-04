"""Static checks on the web app: it must stay safe by construction (spec 08 sections 4 and 6)."""

import json
import re
import shutil
import subprocess
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


def test_the_knowledge_tab_is_registered_and_safe() -> None:
    app = (FRONTEND / "app.js").read_text("utf-8")
    assert 'knowledge: () => import("./views/knowledge.js")' in app
    assert '["knowledge", "Knowledge"]' in app
    view = (FRONTEND / "views" / "knowledge.js").read_text("utf-8")
    # Only approvers and admins get upload, replace and remove controls (Requirement 14.9).
    assert 'const canAct = ["approver", "admin"].includes(me.role);' in view
    assert view.count("canAct") >= 3
    assert "No passages found." in view and "The knowledge base is empty." in view
    # Errors are shown with the API detail and the table is not redrawn (Requirement 14.11).
    assert 'toast(error.message, "error")' in view
    assert not re.search(r"\son[a-z]+=", view)  # no inline handlers in markup strings
    api = (FRONTEND / "api.js").read_text("utf-8")
    assert 'del: (path) => request("DELETE", path)' in api


def test_the_overview_offers_review_controls_and_explains_the_gate() -> None:
    # Spec 15 section 7: approve or reject a phase in review; the next Run waits with a reason.
    view = (FRONTEND / "views" / "overview.js").read_text("utf-8")
    assert "/stages/${stage}/approve" in view and "/stages/${stage}/reject" in view
    assert 'info.review === "in_review"' in view and "info.waiting_for" in view
    assert "export function parseComments" in view
    assert "customer question(s) are still open" in view  # approval warns about open questions
    assert "in_review:" in (FRONTEND / "dom.js").read_text("utf-8")


def test_the_overview_opens_with_a_workflow_strip() -> None:
    # Spec 15 section 7: phases in order, the gate between them, the next action, side loops.
    view = (FRONTEND / "views" / "overview.js").read_text("utf-8")
    assert "export function workflowSteps" in view and "workflowStrip(overview, pid)" in view
    for link in ("/questions", "/drs", "/knowledge"):
        assert f"#/p/${{pid}}{link}" in view
    dom = (FRONTEND / "dom.js").read_text("utf-8")
    assert "ready:" in dom and "locked:" in dom
    # Run is offered only for the phase whose turn it is; the page prints no stray "null".
    assert "ctx.locked.has(stage.key)" in view and "append(clear(main), [" in view


WORKFLOW_SCRIPT = """
import { workflowSteps } from "%s";
const st = (stage, status, review, waiting = null) =>
  ({ stage, status, review, waiting_for: waiting, documents: [] });
const none = (s) => st(s, "not_started", "not_started");
const cases = {
  fresh: [none("brd"), none("srs"), none("basic"), none("detail")],
  inReview: [st("brd", "done", "in_review"), st("srs", "not_started", "not_started", "brd"),
             none("basic"), none("detail")],
  approved: [st("brd", "done", "approved"), none("srs"), none("basic"), none("detail")],
  finished: ["brd", "srs", "basic", "detail"].map((s) => st(s, "done", "approved")),
};
const out = {};
for (const [name, stages] of Object.entries(cases)) out[name] = workflowSteps(stages, true);
const offStages = [st("brd", "done", "draft"), none("srs"), none("basic"), none("detail")];
out.off = workflowSteps(offStages, false);
console.log(JSON.stringify(out));
"""


def test_workflow_steps_follow_the_review_gates(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(WORKFLOW_SCRIPT % (FRONTEND / "views" / "overview.js").as_uri(), "utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, check=True)
    flows = json.loads(done.stdout)

    def states(name: str) -> list[str]:
        return [s["state"] for s in flows[name]["steps"]]

    assert states("fresh") == ["ready", "locked", "locked", "locked"]
    assert states("inReview") == ["in_review", "locked", "locked", "locked"]
    assert flows["inReview"]["gates"] == ["waiting", "closed", "closed"]
    assert flows["inReview"]["next"].startswith("Review the BRD phase")
    assert states("approved") == ["approved", "ready", "locked", "locked"]
    assert flows["approved"]["gates"][0] == "open" and flows["approved"]["current"] == "srs"
    assert flows["finished"]["current"] is None
    assert "Decision Record" in flows["finished"]["next"]
    assert flows["off"]["gates"] == [] and states("off")[:2] == ["done", "ready"]
