"""`masterba doctor`: check that a root can run MasterBA and how to fix it (spec 11 section 6)."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from masterba.api.auth import UserStore
from masterba.models.enums import DocType
from masterba.rendering.errors import InvalidTemplateError
from masterba.rendering.template import load_template
from masterba.trace_store.errors import GitError
from masterba.trace_store.git import ensure_ready

SOURCE_TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "default"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def line(self) -> str:
        mark = "ok  " if self.ok else ("FAIL" if self.required else "warn")
        return f"{mark} {self.name}: {self.detail}"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def init_root(root: Path) -> None:
    """Prepare an empty folder: git init, one empty commit and the default templates."""
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{root} is not empty; --init only prepares an empty folder")
    root.mkdir(parents=True, exist_ok=True)
    # Users, the session secret and uploads live in .masterba/ and must never be committed.
    (root / ".gitignore").write_text(".masterba/\n", encoding="utf-8")
    steps = (["init", "-q"], ["add", ".gitignore"], ["commit", "-q", "-m", "chore: init work tree"])
    for args in steps:
        done = _git(args, root)
        if done.returncode != 0:
            raise ValueError(done.stderr.strip() or f"git {args[0]} failed")
    if SOURCE_TEMPLATES.is_dir():
        shutil.copytree(SOURCE_TEMPLATES, root / "templates" / "default")


def _check_git(root: Path) -> list[Check]:
    if shutil.which("git") is None:
        return [Check("git", False, "git is not on PATH; install git")]
    try:
        ensure_ready(root)
    except GitError as exc:
        if "work tree" in str(exc):
            fix = "run `masterba --root DIR doctor --init` on an empty folder, or `git init`"
            return [Check("git", True, "found"), Check("work tree", False, f"{exc}; {fix}")]
        fix = "set git config user.name/user.email, or GIT_AUTHOR_NAME/GIT_AUTHOR_EMAIL"
        return [Check("git", False, f"{exc}; {fix}")]
    if _git(["rev-parse", "--verify", "-q", "HEAD"], root).returncode != 0:
        return [
            Check("git", True, "found, author set"),
            Check("work tree", False, "no commit yet; make one, e.g. an empty commit"),
        ]
    return [Check("git", True, "found, author set"), Check("work tree", True, str(root))]


def _check_templates(root: Path) -> Check:
    folder = root / "templates" / "default"
    broken = []
    for doc_type in DocType:
        try:
            load_template(folder / f"{doc_type.value}.template.json")
        except InvalidTemplateError:
            broken.append(doc_type.value)
    if broken:
        fix = f"copy {SOURCE_TEMPLATES} to {folder}"
        return Check("templates", False, f"missing or invalid: {', '.join(broken)}; {fix}")
    return Check("templates", True, f"{len(DocType)} default templates")


def _check_state(root: Path) -> Check:
    state = root / ".masterba"
    try:
        state.mkdir(exist_ok=True)
    except OSError as exc:
        return Check("state", False, f"{state} is not writable: {exc}")
    if not os.access(state, os.W_OK):
        return Check("state", False, f"{state} is not writable")
    try:
        users = UserStore(state / "users.json").list()
    except (OSError, ValueError, KeyError) as exc:
        return Check("state", False, f"{state / 'users.json'} is unreadable: {exc}")
    if not users:
        return Check(
            "state", False, "no dashboard user; `masterba user add NAME --role admin`", False
        )
    return Check("state", True, "writable, dashboard users exist")


def _check_model() -> Check:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Check("model", True, "ANTHROPIC_API_KEY is set", False)
    fix = "export ANTHROPIC_API_KEY (and ANTHROPIC_BASE_URL, MASTERBA_MODEL for a gateway)"
    return Check("model", False, f"no model key; {fix}", False)


def run_checks(root: Path) -> list[Check]:
    checks = _check_git(root)
    if all(c.ok for c in checks):
        checks += [_check_templates(root), _check_state(root)]
    return [*checks, _check_model()]
