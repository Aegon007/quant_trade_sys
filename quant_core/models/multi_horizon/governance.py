from __future__ import annotations

import json
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


def _forward_excess_return(asset, benchmark, *, as_of, horizon: int):
    asset_close = pd.to_numeric(asset["Close"], errors="coerce").dropna().sort_index()
    benchmark_close = pd.to_numeric(benchmark["Close"], errors="coerce").dropna().sort_index()
    observation_day = pd.Timestamp(as_of).normalize()
    asset_after = asset_close.loc[observation_day:]
    benchmark_after = benchmark_close.loc[observation_day:]
    if len(asset_after) <= horizon or len(benchmark_after) <= horizon:
        return None
    asset_return = float(asset_after.iloc[horizon] / asset_after.iloc[0] - 1.0)
    benchmark_return = float(benchmark_after.iloc[horizon] / benchmark_after.iloc[0] - 1.0)
    return asset_return - benchmark_return


def score_shadow_outcomes(
    journal_entries,
    *,
    histories: Mapping[str, pd.DataFrame],
    horizons: Sequence[int] = (63, 126, 252),
    benchmark_symbol: str = "SPY",
    top_k: int = 3,
) -> dict:
    normalized_histories = {
        str(symbol).strip().upper(): frame
        for symbol, frame in dict(histories or {}).items()
        if isinstance(frame, pd.DataFrame) and not frame.empty
    }
    benchmark = normalized_histories.get(str(benchmark_symbol).strip().upper())
    horizon_reports = {}
    for horizon in (int(value) for value in horizons):
        observation_ics = []
        observation_top = []
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
                    if asset is None or score is None:
                        continue
                    outcome = _forward_excess_return(asset, benchmark, as_of=as_of, horizon=horizon)
                    if outcome is None:
                        continue
                    scores.append(float(score))
                    outcomes.append(float(outcome))
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
        "validation_status": validation_status,
        "shadow_outcomes": shadow_outcomes,
        "model": dict(prediction_snapshot.get("model", {}) or {}),
        "requirements": {
            "walk_forward_pass": validation_status == "PASS",
            "shadow_observations_available": any(
                int(dict(row or {}).get("matured_observations", 0) or 0) > 0
                for row in dict(shadow_outcomes.get("horizons", {}) or {}).values()
            ),
            "manual_approval_required": True,
        },
    }


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
        symbols = sorted(
            {
                str(prediction.get("symbol") or "").strip().upper()
                for entry in entries
                for prediction in list(dict(entry or {}).get("predictions", []) or [])
                if str(dict(prediction or {}).get("symbol") or "").strip()
            }
        )
        histories = {}
        for symbol in [*symbols, "SPY"]:
            try:
                frame = load_history_fn(symbol, period="2y")
            except Exception:
                continue
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                histories[symbol] = frame
        outcomes = score_shadow_outcomes(entries, histories=histories)
    governance = build_model_governance_snapshot(
        prediction_snapshot=prediction_snapshot,
        validation_snapshot=validation,
        shadow_outcomes=outcomes,
        now=now,
    )
    save_model_governance_snapshot(governance, path=governance_path)
    return governance
