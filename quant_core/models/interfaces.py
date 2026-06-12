from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True)
class ModelPrediction:
    symbol: str
    signal: str
    confidence: float | None = None
    expected_return: float | None = None
    metadata: Mapping = field(default_factory=dict)


class QuantModel(Protocol):
    """Minimal model contract for future TCN/LLM/SLM adapters."""

    model_id: str

    def predict(self, symbol: str, features: Mapping) -> ModelPrediction:
        """Return one model prediction for a symbol."""


@dataclass(frozen=True)
class ModelRegistryEntry:
    model_id: str
    display_name: str
    role: str
    adapter_path: str
    enabled: bool = True
    is_default: bool = False
    params: Mapping = field(default_factory=dict)

