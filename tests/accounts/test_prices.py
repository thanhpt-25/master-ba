from pathlib import Path

import pytest

from masterba.accounts import PriceStore, PriceTable


def test_prices_round_trip_and_cost_per_million_tokens(tmp_path: Path) -> None:
    store = PriceStore(tmp_path / "prices.json")
    assert store.get().empty
    table = PriceTable.from_json({"currency": "JPY", "models": {"m-1": {"input": 3, "output": 15}}})
    store.set(table)
    again = store.get()
    assert again.to_json() == {"currency": "JPY", "models": {"m-1": {"input": 3.0, "output": 15.0}}}
    assert again.cost("m-1", 1_000_000, 100_000) == pytest.approx(4.5)
    assert again.cost("other", 1, 1) is None
    assert again.cost(None, 1, 1) is None


@pytest.mark.parametrize(
    "data",
    [
        {"currency": "yen"},
        {"models": {"bad id!": {"input": 1, "output": 1}}},
        {"models": {"m": {"input": -1, "output": 1}}},
        {"models": {"m": {"input": True, "output": 1}}},
        {"models": {"m": "free"}},
        {"models": [1]},
    ],
)
def test_invalid_prices_are_refused(data: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PriceTable.from_json(data)
