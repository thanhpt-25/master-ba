"""Offline stand-in for a model, used by every automated test."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from masterba.llm.base import LLMResult, T


@dataclass(frozen=True)
class FakeCall:
    system: str
    user: str
    tool_name: str


@dataclass
class FakeLLM:
    """Returns queued responses in order; a queued exception is raised instead."""

    responses: Sequence[BaseModel | Exception]
    calls: list[FakeCall] = field(default_factory=list)

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        self.calls.append(FakeCall(system, user, tool_name))
        if len(self.calls) > len(self.responses):
            raise AssertionError("FakeLLM has no more queued responses")
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, output):
            raise AssertionError(f"queued {type(response).__name__}, wanted {output.__name__}")
        return LLMResult(response, input_tokens=100, output_tokens=50)
