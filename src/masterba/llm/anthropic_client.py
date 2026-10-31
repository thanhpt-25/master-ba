"""Anthropic Messages API adapter: one forced tool call returns the structured output."""

import os
from typing import Any

import anthropic
from pydantic import ValidationError

from masterba.llm.base import LLMConfigError, LLMError, LLMOutputError, LLMResult, T

DEFAULT_MODEL = "claude-sonnet-5-5"
API_KEY_ENV = "ANTHROPIC_API_KEY"


class AnthropicLLM:
    def __init__(
        self, model: str = DEFAULT_MODEL, max_tokens: int = 16000, client: Any = None
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        if client is None:
            api_key = os.environ.get(API_KEY_ENV)
            if not api_key:
                raise LLMConfigError(f"{API_KEY_ENV} is not set")
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        tool = {
            "name": tool_name,
            "description": f"Submit the result as a {output.__name__} object.",
            "input_schema": output.model_json_schema(),
        }
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            )
        except anthropic.APIError as exc:
            raise LLMError(f"model request failed: {type(exc).__name__}: {exc}") from exc
        block = next(
            (b for b in response.content if b.type == "tool_use" and b.name == tool_name), None
        )
        if block is None:
            raise LLMOutputError(f"model did not call {tool_name}")
        try:
            value = output.model_validate(block.input)
        except ValidationError as exc:
            raise LLMOutputError(f"model output does not fit {output.__name__}: {exc}") from exc
        return LLMResult(value, response.usage.input_tokens, response.usage.output_tokens)
