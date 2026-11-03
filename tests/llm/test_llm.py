from types import SimpleNamespace
from typing import Any, cast

import anthropic
import pytest

from factories import draft_for
from masterba.agents import BrdDraft
from masterba.llm import (
    AnthropicLLM,
    FakeLLM,
    LLMConfigError,
    LLMError,
    LLMOutputError,
)

DRAFT = draft_for("login_system.txt")


class StubMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def stub_client(messages: StubMessages) -> Any:
    return SimpleNamespace(messages=messages)


def tool_response(payload: Any, name: str = "submit_brd") -> Any:
    block = SimpleNamespace(type="tool_use", name=name, input=payload)
    return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=11, output_tokens=7))


def test_fake_returns_queued_values_and_records_calls() -> None:
    fake = FakeLLM([DRAFT])
    result = fake.generate(system="s", user="u", output=BrdDraft, tool_name="submit_brd")
    assert result.value == DRAFT
    assert (result.input_tokens, result.output_tokens) == (100, 50)
    assert [(c.system, c.user, c.tool_name) for c in fake.calls] == [("s", "u", "submit_brd")]


def test_fake_raises_queued_errors_and_complains_when_empty() -> None:
    fake = FakeLLM([LLMOutputError("bad")])
    with pytest.raises(LLMOutputError):
        fake.generate(system="s", user="u", output=BrdDraft, tool_name="t")
    with pytest.raises(AssertionError, match="no more queued"):
        fake.generate(system="s", user="u", output=BrdDraft, tool_name="t")


def test_fake_rejects_a_response_of_the_wrong_type() -> None:
    fake = FakeLLM([DRAFT.requirements[0]])
    with pytest.raises(AssertionError, match="wanted BrdDraft"):
        fake.generate(system="s", user="u", output=BrdDraft, tool_name="t")


def test_anthropic_request_forces_the_tool_and_sends_the_schema() -> None:
    messages = StubMessages(tool_response(DRAFT.model_dump(mode="json")))
    llm = AnthropicLLM("test-model", max_tokens=123, client=stub_client(messages))
    result = llm.generate(system="SYS", user="USER", output=BrdDraft, tool_name="submit_brd")
    kwargs = messages.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["max_tokens"] == 123
    assert kwargs["system"] == "SYS"
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_brd"}
    assert kwargs["tools"][0]["name"] == "submit_brd"
    assert kwargs["tools"][0]["input_schema"] == BrdDraft.model_json_schema()
    assert result.value == DRAFT
    assert (result.input_tokens, result.output_tokens) == (11, 7)


def test_anthropic_output_without_the_tool_call_is_an_output_error() -> None:
    text = SimpleNamespace(type="text", text="sorry")
    response = SimpleNamespace(
        content=[text], usage=SimpleNamespace(input_tokens=1, output_tokens=1)
    )
    llm = AnthropicLLM(client=stub_client(StubMessages(response)))
    with pytest.raises(LLMOutputError, match="did not call"):
        llm.generate(system="s", user="u", output=BrdDraft, tool_name="submit_brd")


def test_anthropic_output_that_does_not_fit_the_schema_is_an_output_error() -> None:
    llm = AnthropicLLM(client=stub_client(StubMessages(tool_response({"requirements": []}))))
    with pytest.raises(LLMOutputError, match="does not fit BrdDraft"):
        llm.generate(system="s", user="u", output=BrdDraft, tool_name="submit_brd")


def test_anthropic_api_errors_become_llm_errors() -> None:
    failure = anthropic.APIError("connection refused", cast(Any, None), body=None)
    llm = AnthropicLLM(client=stub_client(StubMessages(error=failure)))
    with pytest.raises(LLMError, match="model request failed") as caught:
        llm.generate(system="s", user="u", output=BrdDraft, tool_name="submit_brd")
    assert caught.value.__cause__ is failure


def test_missing_api_key_fails_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY is not set"):
        AnthropicLLM()


def test_api_key_comes_from_the_environment_and_is_not_echoed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-value")
    llm = AnthropicLLM("test-model")
    assert "sk-test-secret-value" not in repr(vars(llm).get("_model"))
    assert isinstance(llm, AnthropicLLM)


def test_requests_time_out_instead_of_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_client(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return stub_client(StubMessages())

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr(anthropic, "Anthropic", fake_client)
    AnthropicLLM("m")
    assert captured["timeout"] == 180.0
    AnthropicLLM("m", timeout=5.0)
    assert captured["timeout"] == 5.0


def test_request_limits_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTERBA_REQUEST_TIMEOUT", "600")
    monkeypatch.setenv("MASTERBA_MAX_TOKENS", "32000")
    llm = AnthropicLLM(client=stub_client(StubMessages(tool_response({}))))
    assert llm._max_tokens == 32000
    monkeypatch.setenv("MASTERBA_MAX_TOKENS", "zero")
    with pytest.raises(LLMConfigError, match="MASTERBA_MAX_TOKENS"):
        AnthropicLLM(client=stub_client(StubMessages(tool_response({}))))
    monkeypatch.delenv("MASTERBA_MAX_TOKENS")
    assert AnthropicLLM(client=stub_client(StubMessages(tool_response({}))))._max_tokens == 16000
