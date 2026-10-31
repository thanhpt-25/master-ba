"""Generate JSON Schema files from the Pydantic models (single source of truth).

Run ``PYTHONPATH=src uv run python -m masterba.schema_export`` after changing any model.
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from masterba.agents import (
    BasicDesignDraft,
    BrdDraft,
    DetailDesignDraft,
    QaReport,
    SrsDraft,
    TestDraft,
    UnitTestDraft,
)
from masterba.calibration import MappingDraft
from masterba.change import RevisionPatch
from masterba.diff import ItemChange
from masterba.models import (
    BasicDesignContent,
    BrdContent,
    DecisionRecord,
    DetailDesignContent,
    Document,
    ProjectConfig,
    RequirementItem,
    SrsContent,
    TeamRun,
    TemplateDefinition,
    TestSpecContent,
    TraceLink,
)
from masterba.team import TeamMessage, TeamTask

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    RequirementItem,
    Document,
    TraceLink,
    DecisionRecord,
    TemplateDefinition,
    ProjectConfig,
    TeamRun,
    BrdContent,
    SrsContent,
    BasicDesignContent,
    DetailDesignContent,
    TestSpecContent,
    ItemChange,
    BrdDraft,
    SrsDraft,
    BasicDesignDraft,
    TestDraft,
    DetailDesignDraft,
    UnitTestDraft,
    RevisionPatch,
    MappingDraft,
    QaReport,
    TeamTask,
    TeamMessage,
)


def render_schemas() -> dict[str, str]:
    """Return ``{file name: file text}`` for every contract model."""
    return {
        f"{model.__name__}.schema.json": json.dumps(
            model.model_json_schema(), sort_keys=True, indent=2, ensure_ascii=False
        )
        + "\n"
        for model in SCHEMA_MODELS
    }


def write_schemas(out_dir: Path = SCHEMA_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in render_schemas().items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    for path in write_schemas():
        sys.stdout.write(f"{path}\n")


if __name__ == "__main__":
    main()
