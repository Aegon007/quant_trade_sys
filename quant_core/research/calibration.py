from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Optional

import pandas as pd

from quant_core import paths as qpaths


def _close(frame) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()


def _forward_return(series: pd.Series, start: datetime, days: int):
    if series.empty:
        return None
    index = pd.to_datetime(series.index)
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    values = pd.Series(series.to_numpy(), index=index)
    future = values[values.index >= pd.Timestamp(start)]
    if len(future) <= days:
        return None
    return float(future.iloc[days] / future.iloc[0] - 1.0)


def calibrate_recommendations(
    journal: Iterable[Mapping],
    *,
    history_loader,
    horizons=(63, 126, 252, 504),
    market_symbol="SPY",
    risk_free_symbol="SGOV",
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    journal_rows = [dict(row or {}) for row in list(journal or [])]
    market_benchmark = _close(history_loader(market_symbol, period="5y"))
    risk_free_benchmark = _close(history_loader(risk_free_symbol, period="5y"))
    observations = []
    cache = {}
    for row in journal_rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            generated = datetime.fromisoformat(str(row.get("generated_at")).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if symbol not in cache:
            cache[symbol] = _close(history_loader(symbol, period="5y"))
        for horizon in horizons:
            security_return = _forward_return(cache[symbol], generated, int(horizon))
            if security_return is None:
                continue
            market_return = _forward_return(market_benchmark, generated, int(horizon))
            risk_free_return = _forward_return(risk_free_benchmark, generated, int(horizon))
            observations.append({
                "symbol": symbol,
                "generated_at": generated.isoformat(),
                "horizon_days": int(horizon),
                "recommendation": row.get("recommendation"),
                "margin_of_safety": row.get("margin_of_safety"),
                "return": round(security_return, 4),
                "market_return": round(market_return, 4) if market_return is not None else None,
                "risk_free_return": round(risk_free_return, 4) if risk_free_return is not None else None,
                "excess_over_market": round(security_return - market_return, 4) if market_return is not None else None,
                "excess_over_risk_free": round(security_return - risk_free_return, 4) if risk_free_return is not None else None,
            })
    horizon_summary = {}
    for horizon in horizons:
        rows = [row for row in observations if row["horizon_days"] == int(horizon)]
        market_values = [row["excess_over_market"] for row in rows if row["excess_over_market"] is not None]
        risk_free_values = [row["excess_over_risk_free"] for row in rows if row["excess_over_risk_free"] is not None]
        horizon_summary[str(horizon)] = {
            "count": len(rows),
            "market_count": len(market_values),
            "risk_free_count": len(risk_free_values),
            "market_win_rate": round(sum(value > 0 for value in market_values) / len(market_values), 3) if market_values else None,
            "risk_free_win_rate": round(sum(value > 0 for value in risk_free_values) / len(risk_free_values), 3) if risk_free_values else None,
            "median_excess_over_market": round(median(market_values), 4) if market_values else None,
            "median_excess_over_risk_free": round(median(risk_free_values), 4) if risk_free_values else None,
        }
    return {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "status": "READY" if observations else "COLLECTING_DATA",
        "benchmarks": {"market": market_symbol, "risk_free": risk_free_symbol},
        "summary": {"recommendation_count": len(journal_rows), "matured_observation_count": len(observations)},
        "horizons": horizon_summary,
        "observations": observations[-2000:],
    }


def load_recommendation_journal(path: str = qpaths.RECOMMENDATION_JOURNAL_FILE) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def record_recommendations(snapshot: Mapping, *, path: str = qpaths.RECOMMENDATION_JOURNAL_FILE) -> str:
    """Keep the latest observation for each symbol/day to avoid rerun bias."""
    generated_at = str(dict(snapshot or {}).get("generated_at") or datetime.now().isoformat())
    day = generated_at[:10]
    indexed = {}
    for row in load_recommendation_journal(path):
        key = (str(row.get("generated_at") or "")[:10], str(row.get("symbol") or "").upper())
        if key[0] and key[1]:
            indexed[key] = row
    for row in list(dict(snapshot or {}).get("recommendations", []) or []):
        symbol = str(dict(row or {}).get("symbol") or "").strip().upper()
        if symbol:
            indexed[(day, symbol)] = {"generated_at": generated_at, **dict(row or {}), "symbol": symbol}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for _, row in sorted(indexed.items())), encoding="utf-8")
    temporary.replace(target)
    return str(target)


def save_calibration(snapshot: Mapping, path: str = qpaths.VALUATION_CALIBRATION_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
