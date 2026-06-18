from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
import torch

from .fusion import fuse_multi_horizon_decision


TIMING_STATES = ("EARLY", "CONFIRMED", "EXTENDED", "DETERIORATING", "FAILED")


def _to_numpy(value) -> np.ndarray:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def _cross_sectional_percentiles(values: np.ndarray) -> np.ndarray:
    frame = pd.DataFrame(values)
    return frame.rank(axis=0, pct=True, method="average").to_numpy(dtype=float)


def _long_horizon_state(blended_rank: float) -> str:
    if blended_rank >= 0.70:
        return "ATTRACTIVE"
    if blended_rank >= 0.40:
        return "NEUTRAL"
    return "WEAK"


def build_prediction_snapshot(
    outputs: Mapping,
    *,
    symbols: Sequence[str],
    horizons: Sequence[int],
    current_weights_pct: Mapping[str, float] | None = None,
    risk_regime: str = "NORMAL",
    model_metadata: Mapping | None = None,
    generated_at: str | None = None,
    max_weight_pct: float = 10.0,
) -> dict:
    normalized_symbols = [str(symbol).strip().upper() for symbol in symbols]
    normalized_horizons = [int(horizon) for horizon in horizons]
    current_weights_pct = {
        str(symbol).strip().upper(): float(weight or 0.0)
        for symbol, weight in dict(current_weights_pct or {}).items()
    }
    rank_scores = _to_numpy(outputs["rank_scores"])[0]
    rank_percentiles = _cross_sectional_percentiles(rank_scores)
    probabilities = 1.0 / (1.0 + np.exp(-_to_numpy(outputs["outperformance_logits"])[0]))
    quantiles = _to_numpy(outputs["return_quantiles"])[0]
    adverse = _to_numpy(outputs["adverse_excursion"])[0]
    favorable = _to_numpy(outputs["favorable_excursion"])[0]
    timing_indices = _to_numpy(outputs["timing_logits"])[0].argmax(axis=-1)
    expert_weights = _to_numpy(outputs["expert_weights"])[0]
    if len(normalized_horizons) == 3:
        blend_weights = np.asarray([0.25, 0.35, 0.40], dtype=float)
    else:
        blend_weights = np.full(len(normalized_horizons), 1.0 / max(len(normalized_horizons), 1))

    rows = []
    for index, symbol in enumerate(normalized_symbols):
        horizon_rows = {}
        for horizon_index, horizon in enumerate(normalized_horizons):
            horizon_rows[str(horizon)] = {
                "rank": round(float(rank_percentiles[index, horizon_index]), 6),
                "outperformance_probability": round(float(probabilities[index, horizon_index]), 6),
                "return_range": {
                    "p10": round(float(quantiles[index, horizon_index, 0]), 6),
                    "p50": round(float(quantiles[index, horizon_index, 1]), 6),
                    "p90": round(float(quantiles[index, horizon_index, 2]), 6),
                },
                "maximum_adverse_excursion": round(float(adverse[index, horizon_index]), 6),
                "maximum_favorable_excursion": round(float(favorable[index, horizon_index]), 6),
            }
        blended_rank = float(np.dot(rank_percentiles[index], blend_weights))
        state = _long_horizon_state(blended_rank)
        timing_state = TIMING_STATES[int(timing_indices[index])]
        decision = fuse_multi_horizon_decision(
            symbol=symbol,
            long_horizon_state=state,
            timing_state=timing_state,
            current_weight_pct=current_weights_pct.get(symbol, 0.0),
            risk_regime=risk_regime,
            max_weight_pct=max_weight_pct,
        )
        rows.append(
            {
                "symbol": symbol,
                "long_horizon": {
                    "state": state,
                    "blended_rank": round(blended_rank, 6),
                    "horizons": horizon_rows,
                },
                "timing": {
                    "state": timing_state,
                    "confidence": round(
                        float(torch.softmax(torch.tensor(_to_numpy(outputs["timing_logits"])[0, index]), dim=-1).max()),
                        6,
                    ),
                },
                "risk": {
                    "regime": str(risk_regime or "NORMAL").upper(),
                    "maximum_adverse_excursion": round(float(adverse[index, -1]), 6),
                },
                "decision": decision.to_dict(),
                "model_evidence": {
                    "expert_weights": [round(float(value), 6) for value in expert_weights[index]],
                },
            }
        )
    action_counts = {}
    for row in rows:
        action = str(row["decision"]["action"])
        action_counts[action] = action_counts.get(action, 0) + 1
    metadata = dict(model_metadata or {})
    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now().isoformat(),
        "model": {
            "model_id": metadata.get("model_id") or "finance_multi_asset_transformer",
            "trained_at": metadata.get("trained_at"),
            "version": metadata.get("version") or metadata.get("checkpoint_version"),
            "status": "PRODUCTION_CANDIDATE",
        },
        "horizons": normalized_horizons,
        "summary": {
            "symbol_count": len(rows),
            "attractive_count": sum(1 for row in rows if row["long_horizon"]["state"] == "ATTRACTIVE"),
            "conflict_count": sum(
                1
                for row in rows
                if row["long_horizon"]["state"] == "ATTRACTIVE"
                and row["timing"]["state"] in {"DETERIORATING", "FAILED"}
            ),
            "action_counts": action_counts,
        },
        "symbols": rows,
    }
