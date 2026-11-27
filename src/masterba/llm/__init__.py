"""Model access behind a thin protocol so tests run offline."""

from masterba.llm.anthropic_client import DEFAULT_MODEL, AnthropicLLM
from masterba.llm.base import LLM, LLMConfigError, LLMError, LLMOutputError, LLMResult
from masterba.llm.fake import FakeLLM
from masterba.llm.metered import Meter, MeteredLLM, UsageLimitError

__all__ = [
    "DEFAULT_MODEL",
    "LLM",
    "AnthropicLLM",
    "FakeLLM",
    "LLMConfigError",
    "LLMError",
    "LLMOutputError",
    "LLMResult",
    "Meter",
    "MeteredLLM",
    "UsageLimitError",
]
