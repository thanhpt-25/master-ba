"""Development scripts under scripts/."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "qa_issue_stats.py"


def test_qa_issue_stats_counts_issues_but_not_downgrade_notes(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "RUN-0001"
    run.mkdir(parents=True)
    (run / "team-summary.json").write_text(json.dumps({"stage": "BASIC_DESIGN"}), "utf-8")
    ref = "DOC-BASIC_DESIGN-0001#item.2"
    messages = [
        {"sender": "qa", "body": f"[BD-03] {ref}: No error case."},
        {"sender": "qa", "body": f"[BD-03] {ref}: Still no error case."},
        {"sender": "qa", "body": f"[BD-05] {ref}: downgraded (no action required)"},
        {"sender": "gate", "body": "[BD-01] not a QA issue"},
    ]
    (run / "mailbox.json").write_text(json.dumps(messages), "utf-8")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, check=True
    )
    assert done.stdout.split() == ["2", "BASIC_DESIGN", "BD-03"]
