import pytest

from masterba.guard import clean_terms, find, has_secret, preview
from masterba.guard.detect import Finding


def kinds(text: str, terms: tuple[str, ...] = ()) -> list[str]:
    return [f.kind for f in find(text, terms)]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("contact yamada.taro@example.co.jp today", "email"),
        ("電話: 03-1234-5678 まで", "phone"),
        ("携帯 090-1234-5678", "phone"),
        ("携帯 09012345678", "phone"),
        ("tel +81 3 1234 5678", "phone"),
        ("Toll free 0120-123-456", "phone"),
        ("Gọi 0912345678 nhé", "phone"),
        ("Gọi +84912345678", "phone"),
        ("My Number 123456789018", "my_number"),
        ("My Number 1234 5678 9018", "my_number"),
        ("card 4111 1111 1111 1111", "card"),
        ("card 4111111111111111", "card"),
        ("server 192.168.10.25 in DC", "ipv4"),
    ],
)
def test_personal_data_is_found(text: str, kind: str) -> None:
    assert kinds(text) == [kind]
    assert find(text)[0].category == "pii"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key sk-ant-api03-" + "a" * 30, "anthropic_key"),
        ("OPENAI sk-proj-" + "b1" * 20, "openai_key"),
        ("aws AKIAIOSFODNN7EXAMPLE here", "aws_key"),
        ("token ghp_" + "x" * 36, "github_token"),
        ("slack xoxb-1234567890-abcdef", "slack_token"),
        ("google AIza" + "c" * 35, "google_key"),
        ("jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "jwt"),
        ("password=Passw0rd123", "credential"),
        ("パスワード：abc12345xyz", "credential"),
    ],
)
def test_secrets_are_found(text: str, kind: str) -> None:
    found = find(text)
    assert [f.kind for f in found] == [kind]
    assert found[0].category == "secret"
    assert has_secret(text) is not None


def test_a_private_key_spans_its_lines() -> None:
    text = "x\n-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\ny"
    (found,) = find(text)
    assert (found.kind, found.line) == ("private_key", 2)
    assert found.value.count("\n") == 2


@pytest.mark.parametrize(
    "text",
    [
        "REQ-0001 traces to DOC-BRD-0001#item.12 (L3-L5)",
        "KB-0001#chunk.2 and TC-IT-0012",
        "Released on 2026-11-28 at 09:30, version 1.2.3",
        "予算は 12,000,000 円、2026年4月1日開始",
        "on 01-02-2026 we start",
        "パスワードは8文字以上とする",
        "password: required for every user",
        "ログイン画面でメールアドレスとパスワードを入力する",
        "SCR-0012 画面一覧 No. 123456789012",  # 12 digits with a wrong check digit
        "1234567890123456 is not a valid card",
    ],
)
def test_ordinary_project_text_has_no_finding(text: str) -> None:
    assert find(text) == []


def test_terms_match_case_insensitively_and_longest_first() -> None:
    found = find("ACME Bank and acme bank holdings", ("Acme Bank", "acme bank holdings"))
    assert [(f.kind, f.value) for f in found] == [
        ("term", "ACME Bank"),
        ("term", "acme bank holdings"),
    ]


def test_a_secret_wins_over_an_overlapping_finding() -> None:
    assert kinds("token=ab12cd34ef56@example.com") == ["credential"]


def test_clean_terms_drops_short_long_and_repeated_words() -> None:
    assert clean_terms(["  ACME  Bank ", "acme bank", "x", "y" * 81, "Fabrikam"]) == [
        "ACME Bank",
        "Fabrikam",
    ]


def test_preview_never_shows_the_value() -> None:
    (email,) = find("taro@example.co.jp")
    assert preview(email) == "t***@e***.jp"
    (secret,) = find("password=Passw0rd123")
    assert preview(secret) == "[credential]"
    assert preview(Finding("phone", "pii", 0, 2, "12", 1)) == "***"
    (phone,) = find("03-1234-5678")
    assert preview(phone) == "0***8"
