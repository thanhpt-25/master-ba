from pathlib import Path

import pytest
from pydantic import BaseModel

from masterba.accounts import Limits, LimitStore, UsageLedger, UserMeter
from masterba.llm import FakeLLM, LLMOutputError, MeteredLLM, UsageLimitError

HOUR = 3600.0


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class Answer(BaseModel):
    text: str


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ledger(tmp_path: Path, clock: Clock) -> UsageLedger:
    return UsageLedger(tmp_path / "usage.sqlite3", LimitStore(tmp_path / "limits.json"), clock)


def call(ledger: UsageLedger, user: str, tokens: int, project: str = "PRJ-001") -> None:
    ledger.record(
        user, project=project, kind="stage:brd", model="m", input_tokens=tokens, output_tokens=0
    )


def windows(ledger: UsageLedger, user: str) -> dict[str, tuple[int, float | None]]:
    return {w.window: (w.used, w.resets_at) for w in ledger.status(user)}


def test_windows_start_at_the_first_call_and_reset_after_their_length(
    ledger: UsageLedger, clock: Clock
) -> None:
    start = clock.now
    assert windows(ledger, "alice") == {"session": (0, None), "weekly": (0, None)}
    call(ledger, "alice", 100)
    clock.now += HOUR
    call(ledger, "alice", 50)
    assert windows(ledger, "alice") == {
        "session": (150, start + 5 * HOUR),
        "weekly": (150, start + 7 * 24 * HOUR),
    }
    clock.now = start + 5 * HOUR
    assert windows(ledger, "alice")["session"] == (0, None)
    assert windows(ledger, "alice")["weekly"][0] == 150
    call(ledger, "alice", 10)
    assert windows(ledger, "alice")["session"] == (10, clock.now + 5 * HOUR)
    assert windows(ledger, "alice")["weekly"] == (160, start + 7 * 24 * HOUR)
    assert windows(ledger, "bob") == {"session": (0, None), "weekly": (0, None)}


def test_a_reached_limit_blocks_until_the_window_resets(ledger: UsageLedger, clock: Clock) -> None:
    ledger.limits.set_default(Limits(session=100, weekly=None))
    ledger.check("alice")
    call(ledger, "alice", 120)
    with pytest.raises(UsageLimitError, match="5-hour window; it resets at"):
        ledger.check("alice")
    reached = ledger.blocking("alice")
    assert reached is not None
    assert reached.to_json()["percent"] == 100
    clock.now += 5 * HOUR
    ledger.check("alice")


def test_user_limits_replace_the_defaults_and_zero_stops_every_call(
    ledger: UsageLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MASTERBA_LIMIT_WEEKLY_TOKENS", "5000")
    assert ledger.limits.default() == Limits(session=None, weekly=5000)
    ledger.limits.set_default(Limits(session=1000, weekly=None))
    assert ledger.limits.effective("alice") == Limits(session=1000, weekly=None)
    ledger.limits.set_override("alice", Limits(session=0, weekly=None))
    with pytest.raises(UsageLimitError, match="limit is 0 tokens"):
        ledger.check("alice")
    ledger.check("bob")
    ledger.limits.set_override("alice", None)
    ledger.check("alice")
    with pytest.raises(ValueError, match="whole number"):
        Limits.from_json({"session": -1})


def test_reset_starts_new_windows_and_reports_group_by_project(
    ledger: UsageLedger, clock: Clock
) -> None:
    call(ledger, "alice", 100, "PRJ-001")
    call(ledger, "alice", 300, "PRJ-002")
    assert [p["project_id"] for p in ledger.by_project("alice")] == ["PRJ-002", "PRJ-001"]
    assert len(ledger.recent("alice")) == 2
    ledger.reset("alice")
    assert windows(ledger, "alice")["session"] == (0, None)
    clock.now += 8 * 24 * HOUR
    assert ledger.by_project("alice") == []


def test_metered_model_checks_first_and_charges_every_call(ledger: UsageLedger) -> None:
    meter = UserMeter(ledger, "alice", "PRJ-001", "stage:brd")
    inner = FakeLLM([Answer(text="ok"), LLMOutputError("bad", 7, 3)])
    model = MeteredLLM(inner, meter, "writer-model")
    model.generate(system="s", user="u", output=Answer, tool_name="t")
    with pytest.raises(LLMOutputError):
        model.generate(system="s", user="u", output=Answer, tool_name="t")
    assert windows(ledger, "alice")["session"][0] == 150 + 10
    assert ledger.recent("alice")[0]["model"] == "writer-model"
    ledger.limits.set_override("alice", Limits(session=100, weekly=None))
    with pytest.raises(UsageLimitError):
        model.generate(system="s", user="u", output=Answer, tool_name="t")
    assert len(inner.calls) == 2  # the refused call never reached the model
