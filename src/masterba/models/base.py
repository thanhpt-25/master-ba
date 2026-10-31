"""Base class for all contract models: immutable, unknown fields rejected."""

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
