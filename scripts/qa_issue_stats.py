"""List recorded QA issues of a project by stage and checklist id (spec 11 section 2.2).

Development only: `uv run python scripts/qa_issue_stats.py projects/PRJ-001`
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ISSUE = re.compile(r"^\[([^\]]+)\] ")


def count_issues(project: Path) -> Counter[tuple[str, str]]:
    """(stage, checklist id) -> how often QA raised it; downgrade notes are not issues."""
    counts: Counter[tuple[str, str]] = Counter()
    for mailbox in sorted(project.glob("runs/RUN-*/mailbox.json")):
        summary = json.loads((mailbox.parent / "team-summary.json").read_text("utf-8"))
        for message in json.loads(mailbox.read_text("utf-8")):
            body = message["body"]
            match = ISSUE.match(body)
            if message["sender"] == "qa" and match and ": downgraded (" not in body:
                counts[(summary["stage"], match[1])] += 1
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: qa_issue_stats.py PROJECT_DIR\n")
        return 2
    for (stage, checklist_id), n in count_issues(Path(argv[0])).most_common():
        sys.stdout.write(f"{n:4d}  {stage:<14} {checklist_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
