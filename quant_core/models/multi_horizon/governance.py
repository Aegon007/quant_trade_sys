from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from quant_core import paths as qpaths

from .validation import rank_information_coefficient, top_k_excess_return


DEFAULT_PREDICTION_JOURNAL_FILE = qpaths.MULTI_HORIZON_PREDICTION_JOURNAL_FILE
DEFAULT_GOVERNANCE_FILE = qpaths.MULTI_HORIZON_GOVERNANCE_FILE


def _compact_prediction_snapshot(snapshot: Mapping) -> dict:
    snapshot = dict(snapshot or {})
    rows = []
    for raw_row in list(snapshot.get("symbols", []) or []):
        row = dict(raw_row or {})
        long_horizon = dict(row.get("long_horizon", {}) or {})
        horizons = dict(long_horizon.get("horizons", {}) or {})
        rows.append(
            {
                "symbol": str(row.get("symbol") or "").strip().upper(),
                "reference_price": row.get("latest_price"),
                "blended_rank": long_horizon.get("blended_rank"),
                "horizon_ranks": {
                    str(horizon): dict(values or {}).get("rank")
                    for horizon, values in horizons.items()
                },
                "horizon_forecasts": {
                    str(horizon): {
                        "rank": dict(values or {}).get("rank"),
                        "positive_return_probability": dict(values or {}).get(
                            "positive_return_probability"
                        ),
                        "risk_free_outperformance_probability": dict(values or {}).get(
                            "risk_free_outperformance_probability"
                        ),
                        "market_outperformance_probability": dict(values or {}).get(
                            "market_outperformance_probability"
                        ),
                        "median_return": dict(
                            dict(values or {}).get("return_range", {}) or {}
                        ).get("p50"),
                    }
                    for horizon, values in horizons.items()
                },
                "timing_state": dict(row.get("timing", {}) or {}).get("state"),
                "action": dict(row.get("decision", {}) or {}).get("action"),
            }
        )
    return {
        "generated_at": snapshot.get("generated_at"),
        "model": {
            "model_id": dict(snapshot.get("model", {}) or {}).get("model_id"),
            "version": dict(snapshot.get("model", {}) or {}).get("version"),
            "trained_at": dict(snapshot.get("model", {}) or {}).get("trained_at"),
        },
        "predictions": rows,
    }


def append_prediction_journal(
    snapshot: Mapping,
    *,
    path: str = DEFAULT_PREDICTION_JOURNAL_FILE,
) -> str:
    entry = _compact_prediction_snapshot(snapshot)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    signature = (
        str(entry.get("generated_at") or ""),
        str(dict(entry.get("model", {}) or {}).get("version") or ""),
    )
    existing = load_prediction_journal(path=path)
    if existing:
        last = existing[-1]
        last_signature = (
            str(last.get("generated_at") or ""),
            str(dict(last.get("model", {}) or {}).get("version") or ""),
        )
        if signature == last_signature:
            return str(target)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    return str(target)


def load_prediction_journal(*, path: str = DEFAULT_PREDICTION_JOURNAL_FILE) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _forward_return(frame, *, as_of, horizon: int):
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()
    observation_day = pd.Timestamp(as_of).normalize()
    after = close.loc[observation_day:]
    if len(after) <= horizon:
        return None
    return float(after.iloc[horizon] / after.iloc[0] - 1.0)


def _forward_excess_return(asset, benchmark, *, as_of, horizon: int):
    asset_return = _forward_return(asset, as_of=as_of, horizon=horizon)
    benchmark_return = _forward_return(benchmark, as_of=as_of, horizon=horizon)
    if asset_return is None or benchmark_return is None:
        return None
    return asset_return - benchmark_return


def score_shadow_outcomes(
    journal_entries,
    *,
    histories: Mapping[str, pd.DataFrame],
    horizons: Sequence[int] = (63, 126, 252),
    benchmark_symbol: str = "SPY",
    risk_free_symbol: str = "BIL",
    top_k: int = 3,
) -> dict:
    normalized_histories = {
        str(symbol).strip().upper(): frame
        for symbol, frame in dict(histories or {}).items()
        if isinstance(frame, pd.DataFrame) and not frame.empty
    }
    benchmark = normalized_histories.get(str(benchmark_symbol).strip().upper())
    risk_free = normalized_histories.get(str(risk_free_symbol).strip().upper())
    horizon_reports = {}
    for horizon in (int(value) for value in horizons):
        observation_ics = []
        observation_top = []
        absolute_errors = []
        positive_predictions = []
        positive_outcomes = []
        risk_free_predictions = []
        risk_free_outcomes = []
        matured = 0
        if benchmark is not None:
            for entry in list(journal_entries or []):
                as_of = entry.get("generated_at")
                scores = []
                outcomes = []
                for prediction in list(dict(entry or {}).get("predictions", []) or []):
                    symbol = str(dict(prediction or {}).get("symbol") or "").strip().upper()
                    asset = normalized_histories.get(symbol)
                    score = dict(dict(prediction or {}).get("horizon_ranks", {}) or {}).get(str(horizon))
                    forecast = dict(
                        dict(prediction or {}).get("horizon_forecasts", {}).get(str(horizon), {})
                        or {}
                    )
                    if asset is None or score is None:
                        continue
                    outcome = _forward_excess_return(asset, benchmark, as_of=as_of, horizon=horizon)
                    if outcome is None:
                        continue
                    scores.append(float(score))
                    outcomes.append(float(outcome))
                    absolute_outcome = _forward_return(asset, as_of=as_of, horizon=horizon)
                    if absolute_outcome is not None:
                        median = forecast.get("median_return")
                        if median is not None:
                            absolute_errors.append(abs(float(median) - float(absolute_outcome)))
                        probability = forecast.get("positive_return_probability")
                        if probability is not None:
                            positive_predictions.append(float(probability))
                            positive_outcomes.append(float(absolute_outcome > 0))
                    if risk_free is not None:
                        risk_free_outcome = _forward_excess_return(
                            asset,
                            risk_free,
                            as_of=as_of,
                            horizon=horizon,
                        )
                        probability = forecast.get("risk_free_outperformance_probability")
                        if risk_free_outcome is not None and probability is not None:
                            risk_free_predictions.append(float(probability))
                            risk_free_outcomes.append(float(risk_free_outcome > 0))
                if len(scores) < 2:
                    continue
                matured += 1
                ic = rank_information_coefficient(scores, outcomes)
                top_return = top_k_excess_return(scores, outcomes, k=top_k)
                if ic is not None:
                    observation_ics.append(ic)
                if top_return is not None:
                    observation_top.append(top_return)
        horizon_reports[str(horizon)] = {
            "matured_observations": matured,
            "rank_ic": float(np.mean(observation_ics)) if observation_ics else None,
            "top_k_excess_return": float(np.mean(observation_top)) if observation_top else None,
            "median_return_mae": float(np.mean(absolute_errors)) if absolute_errors else None,
            "directional_accuracy": (
                float(
                    np.mean(
                        (np.asarray(positive_predictions) >= 0.5)
                        == (np.asarray(positive_outcomes) >= 0.5)
                    )
                )
                if positive_outcomes
                else None
            ),
            "brier_score": (
                float(
                    np.mean(
                        (np.asarray(positive_predictions) - np.asarray(positive_outcomes)) ** 2
                    )
                )
                if positive_outcomes
                else None
            ),
            "risk_free_directional_accuracy": (
                float(
                    np.mean(
                        (np.asarray(risk_free_predictions) >= 0.5)
                        == (np.asarray(risk_free_outcomes) >= 0.5)
                    )
                )
                if risk_free_outcomes
                else None
            ),
            "risk_free_brier_score": (
                float(
                    np.mean(
                        (np.asarray(risk_free_predictions) - np.asarray(risk_free_outcomes)) ** 2
                    )
                )
                if risk_free_outcomes
                else None
            ),
        }
    return {
        "generated_at": datetime.now().isoformat(),
        "status": "OBSERVING" if not any(row["matured_observations"] for row in horizon_reports.values()) else "HAS_OUTCOMES",
        "horizons": horizon_reports,
    }


def build_model_governance_snapshot(
    *,
    prediction_snapshot: Mapping | None,
    validation_snapshot: Mapping | None,
    shadow_outcomes: Mapping | None = None,
    now: datetime | None = None,
) -> dict:
    prediction_snapshot = dict(prediction_snapshot or {})
    validation_snapshot = dict(validation_snapshot or {})
    shadow_outcomes = dict(shadow_outcomes or {})
    validation_status = str(validation_snapshot.get("status") or "PENDING").upper()
    model = dict(prediction_snapshot.get("model", {}) or {})
    model_version = str(model.get("version") or model.get("trained_at") or "").strip() or None
    lifecycle = "SHADOW" if prediction_snapshot.get("status") == "READY" else "RESEARCH"
    eligible = validation_status == "PASS" and not bool(
        dict(validation_snapshot.get("governance", {}) or {}).get("moe_collapsed")
    )
    return {
        "schema_version": 1,
        "generated_at": (now or datetime.now()).isoformat(),
        "status": "ELIGIBLE_FOR_MANUAL_PROMOTION" if eligible else lifecycle,
        "lifecycle": lifecycle,
        "automatic_promotion": False,
        "production_authorized": False,
        "approved_model_version": None,
        "validation_status": validation_status,
        "shadow_outcomes": shadow_outcomes,
        "model": model,
        "model_version": model_version,
        "requirements": {
            "walk_forward_pass": validation_status == "PASS",
            "shadow_observations_available": any(
                int(dict(row or {}).get("matured_observations", 0) or 0) > 0
                for row in dict(shadow_outcomes.get("horizons", {}) or {}).values()
            ),
            "manual_approval_required": True,
        },
    }


def approve_model_for_production(
    prediction_snapshot: Mapping,
    governance_snapshot: Mapping,
    *,
    path: str = DEFAULT_GOVERNANCE_FILE,
    now: datetime | None = None,
    allow_initial_override: bool = False,
) -> dict:
    prediction_snapshot = dict(prediction_snapshot or {})
    governance = dict(governance_snapshot or {})
    model = dict(prediction_snapshot.get("model", {}) or {})
    version = str(model.get("version") or model.get("trained_at") or "").strip()
    eligible = (
        str(governance.get("status") or "").upper() == "ELIGIBLE_FOR_MANUAL_PROMOTION"
        or str(governance.get("candidate_status") or "").upper() == "ELIGIBLE_FOR_MANUAL_PROMOTION"
    )
    if not eligible and not allow_initial_override:
        raise ValueError("Model is not eligible for production promotion.")
    if not eligible and str(prediction_snapshot.get("status") or "").upper() != "READY":
        raise ValueError("Only a trained READY model can be deployed with an initial override.")
    if not allow_initial_override and str(governance.get("validation_status") or "").upper() != "PASS":
        raise ValueError("Walk-forward validation has not passed.")
    if not version:
        raise ValueError("Model version is missing; retrain before promotion.")
    promoted = {
        **governance,
        "status": "PRODUCTION",
        "lifecycle": "PRODUCTION",
        "production_authorized": True,
        "approved_at": (now or datetime.now()).isoformat(),
        "approved_model_version": version,
        "model_version": version,
        "approval_mode": "INITIAL_MANUAL_OVERRIDE" if not eligible else "VALIDATED_MANUAL_PROMOTION",
        "validation_override": bool(not eligible),
    }
    save_model_governance_snapshot(promoted, path=path)
    return promoted


def apply_production_gate(
    prediction_snapshot: Mapping | None,
    governance_snapshot: Mapping | None,
) -> dict:
    snapshot = deepcopy(dict(prediction_snapshot or {}))
    governance = dict(governance_snapshot or {})
    model = dict(snapshot.get("model", {}) or {})
    version = str(model.get("version") or model.get("trained_at") or "").strip()
    authorized = bool(
        governance.get("production_authorized")
        and str(governance.get("status") or "").upper() == "PRODUCTION"
        and version
        and version == str(governance.get("approved_model_version") or "").strip()
    )
    snapshot["production_authorized"] = authorized
    snapshot["governance"] = governance
    if authorized:
        for collection_name in ("symbols", "core_etfs", "satellite_top3", "satellite_ranked_pool"):
            for row in list(snapshot.get(collection_name, []) or []):
                shadow_decision = dict(row.get("shadow_decision", {}) or {})
                if shadow_decision:
                    row["decision"] = shadow_decision
        return snapshot
    seen = set()
    for collection_name in ("symbols", "core_etfs", "satellite_top3", "satellite_ranked_pool"):
        for row in list(snapshot.get(collection_name, []) or []):
            row_key = id(row)
            if row_key in seen:
                continue
            seen.add(row_key)
            decision = dict(row.get("shadow_decision", {}) or row.get("decision", {}) or {})
            if decision:
                row["shadow_decision"] = decision
                row["decision"] = {
                    **decision,
                    "action": "HOLD" if str(row.get("list_type") or "").lower() == "holding" else "WATCH",
                    "target_weight_range_pct": [float(row.get("current_weight_pct") or 0.0)] * 2,
                    "reason_codes": [*list(decision.get("reason_codes", []) or []), "MODEL_NOT_PROMOTED"],
                }
    snapshot["summary"] = {
        **dict(snapshot.get("summary", {}) or {}),
        "production_authorized": False,
        "message": "Model predictions are shadow-only until validation passes and manual promotion is approved.",
    }
    return snapshot


def save_model_governance_snapshot(
    snapshot: Mapping,
    *,
    path: str = DEFAULT_GOVERNANCE_FILE,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return str(target)


def load_model_governance_snapshot(*, path: str = DEFAULT_GOVERNANCE_FILE) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def refresh_model_governance(
    prediction_snapshot: Mapping,
    *,
    load_history_fn=None,
    score_outcomes: bool = False,
    validation_path: str = qpaths.MULTI_HORIZON_VALIDATION_FILE,
    journal_path: str = DEFAULT_PREDICTION_JOURNAL_FILE,
    governance_path: str = DEFAULT_GOVERNANCE_FILE,
    now: datetime | None = None,
) -> dict:
    try:
        validation = json.loads(Path(validation_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        validation = {}
    previous = load_model_governance_snapshot(path=governance_path)
    outcomes = dict(previous.get("shadow_outcomes", {}) or {})
    if score_outcomes and load_history_fn is not None:
        entries = load_prediction_journal(path=journal_path)
        risk_free_symbol = str(
            dict(prediction_snapshot.get("benchmarks", {}) or {}).get("risk_free")
            or "BIL"
        ).strip().upper()
        symbols = sorted(
            {
                str(prediction.get("symbol") or "").strip().upper()
                for entry in entries
                for prediction in list(dict(entry or {}).get("predictions", []) or [])
                if str(dict(prediction or {}).get("symbol") or "").strip()
            }
        )
        histories = {}
        for symbol in [*symbols, "SPY", risk_free_symbol]:
            try:
                frame = load_history_fn(symbol, period="2y")
            except Exception:
                continue
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                histories[symbol] = frame
        outcomes = score_shadow_outcomes(
            entries,
            histories=histories,
            risk_free_symbol=risk_free_symbol,
        )
    governance = build_model_governance_snapshot(
        prediction_snapshot=prediction_snapshot,
        validation_snapshot=validation,
        shadow_outcomes=outcomes,
        now=now,
    )
    current_version = str(governance.get("model_version") or "").strip()
    if (
        bool(previous.get("production_authorized"))
        and str(previous.get("approved_model_version") or "").strip() == current_version
        and str(governance.get("validation_status") or "").upper() == "PASS"
    ):
        governance.update(
            {
                "status": "PRODUCTION",
                "lifecycle": "PRODUCTION",
                "production_authorized": True,
                "approved_at": previous.get("approved_at"),
                "approved_model_version": current_version,
            }
        )
    elif bool(previous.get("production_authorized")):
        governance.update(
            {
                "status": "PRODUCTION",
                "lifecycle": "PRODUCTION",
                "production_authorized": True,
                "approved_at": previous.get("approved_at"),
                "approved_model_version": previous.get("approved_model_version"),
                "approval_mode": previous.get("approval_mode"),
                "validation_override": previous.get("validation_override", False),
                "candidate_model_version": current_version,
                "candidate_status": (
                    "ELIGIBLE_FOR_MANUAL_PROMOTION"
                    if str(governance.get("status") or "").upper() == "ELIGIBLE_FOR_MANUAL_PROMOTION"
                    else "SHADOW"
                ),
            }
        )
    save_model_governance_snapshot(governance, path=governance_path)
    return governance
