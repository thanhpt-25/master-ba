"""An LLM wrapper that checks a usage limit before each call and records the tokens after it.

The limit and the ledger live behind the `Meter` protocol (spec 23 section 5), so this module
knows nothing about users or storage.
"""

from typing import Protocol

from masterba.llm.base import LLM, LLMError, LLMOutputError, LLMResult, T


class UsageLimitError(LLMError):
    """The user's usage limit is reached; the run escalates and can resume after the reset."""


class Meter(Protocol):
    def check(self) -> None:
        """Raise UsageLimitError when no further call is allowed."""

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None: ...


class MeteredLLM:
    def __init__(self, inner: LLM, meter: Meter, model: str) -> None:
        self._inner = inner
        self._meter = meter
        self._model = model

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        self._meter.check()
        try:
            result = self._inner.generate(
                system=system, user=user, output=output, tool_name=tool_name
            )
        except LLMOutputError as exc:
            # An unusable answer still used tokens (spec 23 section 5).
            self._meter.record(self._model, exc.input_tokens, exc.output_tokens)
            raise
        self._meter.record(self._model, result.input_tokens, result.output_tokens)
        return result
