"""`masterba guard scan`: findings in a project's stored files and git history (spec 30 s. 6)."""

import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from masterba.guard.detect import Finding, find, preview
from masterba.guard.upload import text_of

_TEXT = (".json", ".md", ".txt", ".csv", ".toml")
_BINARY = (".xlsx", ".docx", ".pdf")


@dataclass(frozen=True)
class ScanHit:
    path: str
    finding: Finding
    commit: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "line": self.finding.line,
            "kind": self.finding.kind,
            "category": self.finding.category,
            "preview": preview(self.finding),
        }
        if self.commit is not None:
            data["commit"] = self.commit
        return data

    def line(self) -> str:
        where = f"{self.commit} " if self.commit else ""
        f = self.finding
        return f"{where}{self.path}:{f.line}: {f.category} {f.kind} {preview(f)}"


@dataclass
class ScanReport:
    project_id: str
    hits: list[ScanHit] = field(default_factory=list)

    @property
    def secrets(self) -> int:
        return sum(1 for h in self.hits if h.finding.category == "secret")

    def counts(self) -> dict[str, int]:
        return dict(Counter(h.finding.category for h in self.hits))

    def to_json(self) -> dict[str, Any]:
        return {
            "project": self.project_id,
            "counts": self.counts(),
            "findings": [h.to_json() for h in self.hits],
        }


def _file_text(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _TEXT:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in _BINARY:
        return text_of(path.name, path.read_bytes())
    return None


def scan_files(project_dir: Path, root: Path, terms: tuple[str, ...] = ()) -> list[ScanHit]:
    hits: list[ScanHit] = []
    for path in sorted(p for p in project_dir.rglob("*") if p.is_file()):
        if ".git" in path.parts or "index" in path.relative_to(project_dir).parts[:2]:
            continue
        try:
            text = _file_text(path)
        except OSError:
            continue
        if not text:
            continue
        rel = path.relative_to(root).as_posix()
        hits += [ScanHit(rel, f) for f in find(text, terms)]
    return hits


def scan_history(root: Path, project_dir: Path) -> list[ScanHit]:
    """Findings in lines added by any commit to the project's files."""
    rel = project_dir.relative_to(root).as_posix()
    done = subprocess.run(
        ["git", "log", "--all", "-p", "--no-color", "--format=commit %h", "--", rel],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return []
    hits: list[ScanHit] = []
    commit = path = ""
    added = 0
    for raw in done.stdout.splitlines():
        if raw.startswith("commit "):
            commit = raw[7:].strip()
        elif raw.startswith("+++ b/"):
            path = raw[6:]
        elif raw.startswith("@@"):
            # @@ -a,b +c,d @@: the next added line is line c of the new file.
            try:
                added = int(raw.split("+", 1)[1].split(",")[0].split(" ")[0]) - 1
            except (IndexError, ValueError):
                added = 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            added += 1
            for f in find(raw[1:]):
                moved = Finding(f.kind, f.category, f.start, f.end, f.value, added)
                hits.append(ScanHit(path, moved, commit))
        elif not raw.startswith("-"):
            added += 1
    return hits


def scan_project(
    root: Path, project_dir: Path, *, history: bool = False, terms: tuple[str, ...] = ()
) -> ScanReport:
    report = ScanReport(project_dir.name, scan_files(project_dir, root, terms))
    if history:
        report.hits += scan_history(root, project_dir)
    return report
