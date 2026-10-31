"""Model access behind a thin protocol so tests run offline."""

from masterba.llm.anthropic_client import DEFAULT_MODEL, AnthropicLLM
from masterba.llm.base import LLM, LLMConfigError, LLMError, LLMOutputError, LLMResult
from masterba.llm.fake import FakeLLM

__all__ = [
    "DEFAULT_MODEL",
    "LLM",
    "AnthropicLLM",
    "FakeLLM",
    "LLMConfigError",
    "LLMError",
    "LLMOutputError",
    "LLMResult",
]
