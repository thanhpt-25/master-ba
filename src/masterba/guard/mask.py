"""Masking model requests and restoring answers (spec 30 section 2)."""

import re
from collections.abc import Sequence
from typing import Any

from masterba.guard.detect import Finding, find
from masterba.llm.base import LLM, LLMResult, T

_TOKEN = re.compile(r"⟦([A-Z_]+)-(\d+)⟧")
_LABELS = {"secret": "SECRET", "term": "TERM"}


class Masker:
    """One table of value to token for a run; equal values always get the same token."""

    def __init__(self, *, pii: bool = True, terms: Sequence[str] = ()) -> None:
        self.pii = pii
        self.terms = tuple(terms)
        self._tokens: dict[str, str] = {}
        self._values: dict[str, str] = {}
        self._restorable: set[str] = set()
        self._counts: dict[str, int] = {}

    def _token(self, finding: Finding) -> str:
        known = self._tokens.get(finding.value)
        if known is not None:
            return known
        label = _LABELS.get(finding.category, finding.kind.upper())
        self._counts[label] = self._counts.get(label, 0) + 1
        token = f"⟦{label}-{self._counts[label]}⟧"
        self._tokens[finding.value] = token
        self._values[token] = finding.value
        if finding.category != "secret":
            self._restorable.add(token)
        return token

    def _replace(self, text: str, keep: bool) -> str:
        findings = find(text, self.terms)
        if not findings:
            return text
        parts: list[str] = []
        cursor = 0
        for finding in findings:
            if keep and finding.category != "secret":
                continue
            parts.append(text[cursor : finding.start])
            # Newlines inside a finding stay, so line numbers do not move.
            parts.append(self._token(finding) + "\n" * finding.value.count("\n"))
            cursor = finding.end
        parts.append(text[cursor:])
        return "".join(parts)

    def mask(self, text: str) -> str:
        """Secrets always; personal data and terms when `pii` is on."""
        return self._replace(text, keep=not self.pii)

    def redact(self, text: str) -> str:
        """Every finding, whatever `pii` says (for anything written to disk)."""
        return self._replace(text, keep=False)

    def unmask(self, text: str) -> str:
        """Personal data and terms back in; a secret token stays a token."""
        if "⟦" not in text:
            return text
        return _TOKEN.sub(
            lambda m: self._values[m.group()] if m.group() in self._restorable else m.group(),
            text,
        )

    def unmask_model(self, value: T) -> T:
        if not self._restorable:
            return value
        data = _walk(value.model_dump(mode="json"), self.unmask)
        return type(value).model_validate(data)


def _walk(data: Any, change: Any) -> Any:
    if isinstance(data, str):
        return change(data)
    if isinstance(data, list):
        return [_walk(item, change) for item in data]
    if isinstance(data, dict):
        return {key: _walk(item, change) for key, item in data.items()}
    return data


class GuardedLLM:
    """A model whose user prompt is masked and whose answer is restored."""

    def __init__(self, inner: LLM, masker: Masker) -> None:
        self._inner = inner
        self._masker = masker

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        result = self._inner.generate(
            system=system, user=self._masker.mask(user), output=output, tool_name=tool_name
        )
        return LLMResult(
            self._masker.unmask_model(result.value), result.input_tokens, result.output_tokens
        )


def masker_for(config: Any) -> Masker:
    """The masker of a project config (anything with `pii_masking` and `masking_terms`)."""
    return Masker(
        pii=bool(getattr(config, "pii_masking", True)),
        terms=tuple(getattr(config, "masking_terms", ()) or ()),
    )
