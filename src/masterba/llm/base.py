"""LLM access protocol (specs/03-requirements-analyst-agent.md section 4)."""

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for model-access failures."""


class LLMConfigError(LLMError):
    """The client cannot be set up (for example a missing API key)."""


class LLMOutputError(LLMError):
    """The model returned nothing usable or output that does not fit the schema."""


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    value: T
    input_tokens: int
    output_tokens: int


class LLM(Protocol):
    def generate(
        self, *, system: str, user: str, output: type[T], tool_name: str
    ) -> LLMResult[T]: ...
