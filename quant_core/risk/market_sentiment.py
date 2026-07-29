from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping, Sequence

import pandas as pd


def _close(frame) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    return series.sort_index()


def _first_history(histories: Mapping[str, pd.DataFrame], *symbols: str):
    for symbol in symbols:
        frame = histories.get(symbol)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            return frame
    return None


def _pct_change(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    old = float(series.iloc[-periods - 1])
    new = float(series.iloc[-1])
    if old <= 0 or not math.isfinite(old) or not math.isfinite(new):
        return None
    return new / old - 1.0


def _ma_state(series: pd.Series, window: int) -> bool | None:
    if len(series) < window:
        return None
    latest = float(series.iloc[-1])
    average = float(series.tail(window).mean())
    if average <= 0 or not math.isfinite(latest) or not math.isfinite(average):
        return None
    return latest >= average


def _event_sentiment(news_intelligence: Mapping | None) -> tuple[float, list[str]]:
    payload = dict(news_intelligence or {})
    impacts = [dict(row or {}) for row in list(payload.get("portfolio_impacts", []) or [])]
    if not impacts:
        return 0.0, []
    score = 0.0
    drivers = []
    for row in impacts[:8]:
        direction = str(row.get("direction") or "NEUTRAL").upper()
        confidence = float(row.get("confidence") or 0.0)
        if direction == "POSITIVE":
            score += 6.0 * confidence
        elif direction == "NEGATIVE":
            score -= 8.0 * confidence
        elif direction == "MIXED":
            score -= 3.0 * confidence
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            drivers.append(f"{symbol}:{direction}")
    return max(min(score, 15.0), -20.0), drivers[:4]


def build_market_sentiment_snapshot(
    histories: Mapping[str, pd.DataFrame] | None,
    *,
    symbols: Sequence[str] | None = None,
    news_intelligence: Mapping | None = None,
    now: datetime | None = None,
) -> dict:
    histories = {str(k).upper(): v for k, v in dict(histories or {}).items()}
    symbols = [str(symbol or "").strip().upper() for symbol in list(symbols or []) if str(symbol or "").strip()]
    now = now or datetime.now()

    score = 50.0
    drivers: list[str] = []
    warnings: list[str] = []

    spy = _close(histories.get("SPY"))
    qqq = _close(_first_history(histories, "QQQ", "QQQM"))
    voo = _close(_first_history(histories, "VOO", "SPY"))
    vix = _close(_first_history(histories, "^VIX", "VIX"))

    spy_63 = _pct_change(spy, 63)
    if spy_63 is not None:
        adjustment = max(min(spy_63 * 80.0, 12.0), -16.0)
        score += adjustment
        drivers.append(f"SPY 63d return {spy_63:+.1%}")
    else:
        warnings.append("SPY trend unavailable")

    if len(qqq) > 63 and len(voo) > 63:
        qqq_rel = (_pct_change(qqq, 63) or 0.0) - (_pct_change(voo, 63) or 0.0)
        score += max(min(qqq_rel * 70.0, 8.0), -8.0)
        drivers.append(f"QQQ/VOO relative strength {qqq_rel:+.1%}")

    if len(vix) >= 20:
        latest_vix = float(vix.iloc[-1])
        vix_ma = float(vix.tail(20).mean())
        if latest_vix >= 30:
            score -= 20.0
            drivers.append(f"VIX stress {latest_vix:.1f}")
        elif latest_vix >= 22:
            score -= 10.0
            drivers.append(f"VIX elevated {latest_vix:.1f}")
        if vix_ma > 0 and latest_vix > vix_ma * 1.2:
            score -= 8.0
            drivers.append("VIX rising faster than 20d average")

    breadth_candidates = []
    for symbol in symbols:
        series = _close(histories.get(symbol))
        above_50 = _ma_state(series, 50)
        above_200 = _ma_state(series, 200)
        if above_50 is None or above_200 is None:
            continue
        breadth_candidates.append((above_50, above_200))
    if breadth_candidates:
        above_50_pct = sum(1 for row in breadth_candidates if row[0]) / len(breadth_candidates)
        above_200_pct = sum(1 for row in breadth_candidates if row[1]) / len(breadth_candidates)
        score += (above_50_pct - 0.5) * 18.0 + (above_200_pct - 0.5) * 14.0
        drivers.append(f"breadth 50d {above_50_pct:.0%}, 200d {above_200_pct:.0%}")
    else:
        above_50_pct = None
        above_200_pct = None
        warnings.append("breadth unavailable")

    event_adjustment, event_drivers = _event_sentiment(news_intelligence)
    score += event_adjustment
    drivers.extend(event_drivers)

    score = round(max(min(score, 100.0), 0.0), 1)
    if score >= 65:
        risk_appetite = "RISK_ON"
    elif score <= 38:
        risk_appetite = "RISK_OFF"
    else:
        risk_appetite = "NEUTRAL"

    if above_50_pct is not None and above_200_pct is not None:
        if above_50_pct >= 0.62 and above_200_pct >= 0.55:
            breadth_state = "BROAD_PARTICIPATION"
        elif above_50_pct < 0.42 or above_200_pct < 0.38:
            breadth_state = "DETERIORATING"
        else:
            breadth_state = "NARROW_OR_MIXED"
    else:
        breadth_state = "UNKNOWN"

    confidence = 0.85 - 0.12 * len(warnings)
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": "READY" if confidence > 0.4 else "PARTIAL",
        "market_sentiment_score": score,
        "risk_appetite_state": risk_appetite,
        "breadth_state": breadth_state,
        "breadth_above_50d_pct": above_50_pct,
        "breadth_above_200d_pct": above_200_pct,
        "sentiment_confidence": round(max(confidence, 0.1), 2),
        "main_sentiment_drivers": drivers[:8],
        "warnings": warnings,
    }
