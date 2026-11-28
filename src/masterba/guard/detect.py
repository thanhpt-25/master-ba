"""Deterministic detection of secrets and personal data in text (spec 30 section 1)."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Category = Literal["secret", "pii", "term"]

# A number rule needs a boundary that is neither a digit nor an ASCII letter on both sides,
# and no hyphen or dot right before it (so `REQ-0001`, `L3-L5` and `1.2.3.4.5` never match).
_B = r"(?<![0-9A-Za-z_.\-])"
_E = r"(?![0-9A-Za-z_])"

_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?"
            r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("anthropic_key", re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("aws_key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    (
        "github_token",
        re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    ),
    ("slack_token", re.compile(r"(?<![A-Za-z0-9])xox[bpars]-[A-Za-z0-9\-]{10,}")),
    ("google_key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])")),
    (
        "jwt",
        re.compile(
            r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
        ),
    ),
)

_CREDENTIAL = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api[_\-]?key|access[_\-]?key|パスワード)"
    r"[\"']?\s*[:=：]\s*[\"']?(?P<value>[!-~]{8,})"
)

_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9\-])"
)
_PHONE = re.compile(
    _B + r"(?:"
    r"\+81[\- ]?\d{1,4}[\- ]?\d{1,4}[\- ]?\d{3,4}"  # Japan, international
    r"|0\d{1,4}-\d{1,4}-\d{3,4}"  # Japan, hyphenated (03-1234-5678, 0120-123-456)
    r"|0[5789]0\d{8}"  # Japan mobile and IP phones, no hyphens
    r"|\+84[\- ]?[35789]\d{8}"  # Vietnam mobile, international
    r"|0[35789]\d{8}"  # Vietnam mobile
    r")" + _E
)
_MY_NUMBER = re.compile(_B + r"(?:\d{12}|\d{4}[\- ]\d{4}[\- ]\d{4})" + _E)
_CARD = re.compile(_B + r"(?:\d{13,19}|\d{4}(?:[\- ]\d{4}){2,3}(?:[\- ]\d{1,3})?)" + _E)
_IPV4 = re.compile(
    r"(?<![0-9A-Za-z_.\-])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![0-9A-Za-z_]|\.\d)"
)

MAX_TERMS = 200
MIN_TERM_CHARS = 2
MAX_TERM_CHARS = 80


@dataclass(frozen=True)
class Finding:
    kind: str
    category: Category
    start: int
    end: int
    value: str
    line: int


def _my_number_ok(digits: str) -> bool:
    """The check digit of a Japanese Individual Number (12 digits)."""
    body = [int(d) for d in digits[:11]]
    total = 0
    for n in range(1, 12):
        p = body[11 - n]
        q = n + 1 if n <= 6 else n - 5
        total += p * q
    rest = total % 11
    check = 0 if rest <= 1 else 11 - rest
    return check == int(digits[11])


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _credential_ok(value: str) -> bool:
    value = value.rstrip("\"',;.)")
    return (
        len(value) >= 8
        and any(c.isalpha() for c in value)
        and any(c.isdigit() for c in value)
        and not value.startswith(("http://", "https://"))
        and not value.startswith("⟦")
    )


def _raw(text: str, terms: Sequence[str]) -> Iterable[tuple[str, Category, int, int]]:
    for kind, pattern in _SECRET_RULES:
        for m in pattern.finditer(text):
            yield kind, "secret", m.start(), m.end()
    for m in _CREDENTIAL.finditer(text):
        value = m.group("value").rstrip("\"',;.)")
        if _credential_ok(value):
            start = m.start("value")
            yield "credential", "secret", start, start + len(value)
    for m in _EMAIL.finditer(text):
        yield "email", "pii", m.start(), m.end()
    for m in _PHONE.finditer(text):
        if 10 <= len(_digits(m.group())) <= 12:  # 01-02-2026 is a date, not a phone
            yield "phone", "pii", m.start(), m.end()
    for m in _MY_NUMBER.finditer(text):
        if _my_number_ok(_digits(m.group())):
            yield "my_number", "pii", m.start(), m.end()
    for m in _CARD.finditer(text):
        digits = _digits(m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            yield "card", "pii", m.start(), m.end()
    for m in _IPV4.finditer(text):
        yield "ipv4", "pii", m.start(), m.end()
    for term in clean_terms(terms):
        for m in re.finditer(re.escape(term), text, re.IGNORECASE):
            yield "term", "term", m.start(), m.end()


_RANK = {"secret": 0, "pii": 1, "term": 2}


def find(text: str, terms: Sequence[str] = ()) -> list[Finding]:
    """Non-overlapping findings in text order (a secret, then the longer finding, wins)."""
    candidates = sorted(_raw(text, terms), key=lambda c: (_RANK[c[1]], -(c[3] - c[2]), c[2]))
    taken: list[tuple[int, int]] = []
    kept: list[tuple[str, Category, int, int]] = []
    for kind, category, start, end in candidates:
        if any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        kept.append((kind, category, start, end))
    kept.sort(key=lambda c: c[2])
    return [
        Finding(kind, category, start, end, text[start:end], text.count("\n", 0, start) + 1)
        for kind, category, start, end in kept
    ]


def has_secret(text: str) -> Finding | None:
    """The first secret in `text`, or None."""
    return next((f for f in find(text) if f.category == "secret"), None)


def clean_terms(terms: Iterable[str]) -> list[str]:
    """Distinct, stripped terms of an allowed length, longest first (so longer terms win)."""
    seen: dict[str, str] = {}
    for term in terms:
        word = " ".join(term.split())
        if MIN_TERM_CHARS <= len(word) <= MAX_TERM_CHARS:
            seen.setdefault(word.casefold(), word)
    return sorted(seen.values(), key=len, reverse=True)[:MAX_TERMS]


def preview(finding: Finding) -> str:
    """The finding without its value: a secret as its kind, others shortened around `***`."""
    if finding.category == "secret":
        return f"[{finding.kind}]"
    value = finding.value
    if finding.kind == "email":
        local, _, domain = value.partition("@")
        host, _, tld = domain.rpartition(".")
        return f"{local[:1]}***@{host[:1]}***.{tld}"
    if len(value) <= 2:
        return "***"
    return f"{value[0]}***{value[-1]}"


def describe(finding: Finding) -> str:
    """`<kind>, line <n>` for messages."""
    return f"{finding.kind}, line {finding.line}"
