"""Optional model prices for a cost estimate (spec 24 section 4).

`.masterba/prices.json`: `{"currency": "USD", "models": {"<model id>": {"input": 3.0,
"output": 15.0}}}`, prices per million tokens. A model without a price is reported as unpriced.
"""

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CURRENCY = re.compile(r"^[A-Z]{3}$")
MODEL = re.compile(r"^[A-Za-z0-9._:/@\[\]-]{1,100}$")
MAX_MODELS = 50


@dataclass(frozen=True)
class Price:
    input: float
    output: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input + output_tokens * self.output) / 1_000_000


@dataclass(frozen=True)
class PriceTable:
    currency: str
    models: dict[str, Price]

    def to_json(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "models": {
                m: {"input": p.input, "output": p.output} for m, p in sorted(self.models.items())
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "PriceTable":
        data = data or {}
        currency = str(data.get("currency") or "USD")
        if not CURRENCY.match(currency):
            raise ValueError("currency is a three-letter code such as USD or JPY")
        raw = data.get("models") or {}
        if not isinstance(raw, dict) or len(raw) > MAX_MODELS:
            raise ValueError(f"give prices for at most {MAX_MODELS} models")
        models: dict[str, Price] = {}
        for model, price in raw.items():
            if not MODEL.match(str(model)):
                raise ValueError(f"{model!r} is not a model id")
            values = []
            for key in ("input", "output"):
                value = price.get(key) if isinstance(price, dict) else None
                if (
                    not isinstance(value, int | float)
                    or isinstance(value, bool)
                    or not 0 <= value <= 10_000
                ):
                    raise ValueError(f"{model}: {key} price per million tokens is 0 to 10000")
                values.append(float(value))
            models[str(model)] = Price(*values)
        return cls(currency, models)

    @property
    def empty(self) -> bool:
        return not self.models

    def cost(self, model: str | None, input_tokens: int, output_tokens: int) -> float | None:
        price = self.models.get(model or "")
        return price.cost(input_tokens, output_tokens) if price else None


class PriceStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def get(self) -> PriceTable:
        if not self._path.exists():
            return PriceTable("USD", {})
        return PriceTable.from_json(json.loads(self._path.read_text("utf-8")))

    def set(self, table: PriceTable) -> PriceTable:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(table.to_json(), indent=2) + "\n", "utf-8")
            tmp.replace(self._path)
        return table
