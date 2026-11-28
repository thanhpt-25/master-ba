from pydantic import BaseModel

from masterba.guard import GuardedLLM, Masker, masker_for
from masterba.llm import FakeLLM


class Inner(BaseModel):
    text: str
    tags: list[str] = []


class Outer(BaseModel):
    title: str
    items: list[Inner]
    count: int = 0


def test_equal_values_get_the_same_token_and_come_back() -> None:
    masker = Masker(terms=("ACME",))
    masked = masker.mask("mail taro@example.com, again taro@example.com, ACME, 03-1234-5678")
    assert masked == "mail ⟦EMAIL-1⟧, again ⟦EMAIL-1⟧, ⟦TERM-1⟧, ⟦PHONE-1⟧"
    assert (
        masker.unmask(masked) == "mail taro@example.com, again taro@example.com, ACME, 03-1234-5678"
    )


def test_line_numbers_do_not_move() -> None:
    text = "a\n-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\nb"
    masked = Masker().mask(text)
    assert masked.count("\n") == text.count("\n")
    assert masked.splitlines()[-1] == "b"


def test_a_secret_is_never_restored() -> None:
    masker = Masker()
    masked = masker.mask("password=Passw0rd123")
    assert masked == "password=⟦SECRET-1⟧"
    assert masker.unmask(masked) == masked


def test_with_masking_off_only_secrets_are_masked_but_redact_takes_everything() -> None:
    masker = Masker(pii=False, terms=("ACME",))
    text = "ACME taro@example.com password=Passw0rd123"
    assert masker.mask(text) == "ACME taro@example.com password=⟦SECRET-1⟧"
    assert masker.redact(text) == "⟦TERM-1⟧ ⟦EMAIL-1⟧ password=⟦SECRET-1⟧"


def test_unmask_model_walks_nested_values() -> None:
    masker = Masker()
    masker.mask("taro@example.com")
    value = Outer(
        title="⟦EMAIL-1⟧", items=[Inner(text="to ⟦EMAIL-1⟧", tags=["⟦EMAIL-1⟧"])], count=2
    )
    restored = masker.unmask_model(value)
    assert restored.title == "taro@example.com"
    assert restored.items[0].tags == ["taro@example.com"]
    assert restored.count == 2
    assert Masker().unmask_model(value) is value  # nothing to restore


def test_guarded_llm_masks_the_prompt_and_restores_the_answer() -> None:
    fake = FakeLLM([Inner(text="reply to ⟦EMAIL-1⟧")])
    guarded = GuardedLLM(fake, Masker())
    result = guarded.generate(system="s", user="from taro@example.com", output=Inner, tool_name="t")
    assert fake.calls[0].user == "from ⟦EMAIL-1⟧"
    assert result.value.text == "reply to taro@example.com"
    assert (result.input_tokens, result.output_tokens) == (100, 50)


def test_masker_for_reads_the_project_settings() -> None:
    class Config:
        pii_masking = False
        masking_terms = ["ACME"]

    masker = masker_for(Config())
    assert (masker.pii, masker.terms) == (False, ("ACME",))
    assert masker_for(object()).pii is True
