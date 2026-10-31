"""Server settings: where the data lives and how models are reached (spec 08 section 1)."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from masterba.llm import DEFAULT_MODEL, LLM, AnthropicLLM

MAX_UPLOAD_CHARS = 200_000
LLMFactory = Callable[[str], LLM]


def _default_factory(model: str) -> LLM:
    return AnthropicLLM(model)


@dataclass(frozen=True)
class Settings:
    root: Path
    llm_factory: LLMFactory = _default_factory
    model: str = DEFAULT_MODEL
    qa_model: str | None = None
    test_model: str | None = None
    session_hours: int = 8
    hash_iterations: int = 600_000

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def templates(self) -> Path:
        return self.root / "templates"

    @property
    def state_dir(self) -> Path:
        return self.root / ".masterba"

    @property
    def uploads_dir(self) -> Path:
        return self.state_dir / "uploads"


def settings_from_env(root: Path) -> Settings:
    """Models come from the server environment only; the browser never sees a key."""
    return Settings(
        root=root,
        model=os.environ.get("MASTERBA_MODEL") or DEFAULT_MODEL,
        qa_model=os.environ.get("MASTERBA_QA_MODEL") or None,
        test_model=os.environ.get("MASTERBA_TEST_MODEL") or None,
    )
