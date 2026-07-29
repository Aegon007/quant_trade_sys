from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping, Sequence

import pandas as pd


AI_INFRA_SYMBOLS = {"NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AVGO", "TSM", "ASML", "AMD", "MU", "SMCI", "ANET", "VRT"}
CAPEX_KEYWORDS = ("capex", "capital expenditure", "data center", "ai infrastructure", "cash flow", "free cash flow", "debt", "borrow", "bond")


def _close(frame) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()


def _first_history(histories: Mapping[str, pd.DataFrame], *symbols: str):
    for symbol in symbols:
        frame = histories.get(symbol)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            return frame
    return None


def _return(series: pd.Series, periods: int) -> float | None:
    if len(series) <= periods:
        return None
    start = float(series.iloc[-periods - 1])
    end = float(series.iloc[-1])
    if start <= 0 or not math.isfinite(start) or not math.isfinite(end):
        return None
    return end / start - 1.0


def _rolling_corr(histories: Mapping[str, pd.DataFrame], symbols: Sequence[str], periods: int = 63) -> float | None:
    returns = []
    names = []
    for symbol in symbols:
        series = _close(histories.get(symbol))
        if len(series) <= periods:
            continue
        returns.append(series.tail(periods + 1).pct_change().dropna().rename(symbol))
        names.append(symbol)
    if len(returns) < 3:
        return None
    frame = pd.concat(returns, axis=1).dropna(how="any")
    if frame.shape[0] < 20 or frame.shape[1] < 3:
        return None
    corr = frame.corr().to_numpy()
    values = []
    for i in range(corr.shape[0]):
        for j in range(i + 1, corr.shape[1]):
            if math.isfinite(float(corr[i, j])):
                values.append(float(corr[i, j]))
    return sum(values) / len(values) if values else None


def _news_capex_pressure(news_intelligence: Mapping | None) -> tuple[float, list[str]]:
    payload = dict(news_intelligence or {})
    drivers = []
    pressure = 0.0
    for impact in list(payload.get("portfolio_impacts", []) or [])[:12]:
        row = dict(impact or {})
        text = f"{row.get('summary') or ''} " + " ".join(
            str(dict(item or {}).get("title") or "") for item in list(row.get("evidence", []) or [])
        )
        lowered = text.lower()
        keyword_hits = sum(1 for keyword in CAPEX_KEYWORDS if keyword in lowered)
        if keyword_hits <= 0:
            continue
        direction = str(row.get("direction") or "NEUTRAL").upper()
        confidence = float(row.get("confidence") or 0.0)
        symbol = str(row.get("symbol") or "").strip().upper()
        if direction in {"NEGATIVE", "MIXED"}:
            pressure += min(12.0, keyword_hits * 3.0 + confidence * 6.0)
        else:
            pressure += min(4.0, keyword_hits * 1.0 + confidence * 2.0)
        if symbol:
            drivers.append(f"{symbol} capex/cash-flow news pressure")
    return min(pressure, 30.0), drivers[:5]


def build_systemic_risk_snapshot(
    histories: Mapping[str, pd.DataFrame] | None,
    *,
    symbols: Sequence[str] | None = None,
    news_intelligence: Mapping | None = None,
    financials_intelligence: Mapping | None = None,
    market_sentiment: Mapping | None = None,
    now: datetime | None = None,
) -> dict:
    histories = {str(k).upper(): v for k, v in dict(histories or {}).items()}
    symbols = [str(symbol or "").strip().upper() for symbol in list(symbols or []) if str(symbol or "").strip()]
    now = now or datetime.now()
    drivers: list[str] = []
    warnings: list[str] = []
    score = 10.0

    ai_symbols = [symbol for symbol in symbols if symbol in AI_INFRA_SYMBOLS and symbol in histories]
    ai_corr = _rolling_corr(histories, ai_symbols)
    if ai_corr is not None:
        if ai_corr >= 0.72:
            score += 22.0
            drivers.append(f"AI infrastructure correlation elevated {ai_corr:.2f}")
        elif ai_corr >= 0.55:
            score += 12.0
            drivers.append(f"AI infrastructure correlation rising {ai_corr:.2f}")
    else:
        warnings.append("AI supply-chain correlation unavailable")

    spy = _close(histories.get("SPY"))
    qqq = _close(_first_history(histories, "QQQ", "QQQM"))
    spy_63 = _return(spy, 63)
    qqq_63 = _return(qqq, 63)
    if spy_63 is not None and qqq_63 is not None:
        concentration_gap = qqq_63 - spy_63
        if concentration_gap >= 0.12:
            score += 12.0
            drivers.append(f"growth concentration gap {concentration_gap:+.1%}")
        elif concentration_gap <= -0.08:
            score += 8.0
            drivers.append(f"growth leadership unwinding {concentration_gap:+.1%}")

    stress_symbols = []
    for symbol in ai_symbols:
        ret_21 = _return(_close(histories.get(symbol)), 21)
        ret_126 = _return(_close(histories.get(symbol)), 126)
        if ret_21 is not None and ret_126 is not None and ret_126 > 0.25 and ret_21 < -0.08:
            stress_symbols.append(symbol)
    if stress_symbols:
        score += min(18.0, len(stress_symbols) * 5.0)
        drivers.append(f"AI winners rolling over: {', '.join(stress_symbols[:5])}")

    sentiment = dict(market_sentiment or {})
    if str(sentiment.get("risk_appetite_state") or "").upper() == "RISK_OFF":
        score += 12.0
        drivers.append("market sentiment risk-off")
    if str(sentiment.get("breadth_state") or "").upper() == "DETERIORATING":
        score += 10.0
        drivers.append("market breadth deteriorating")

    news_pressure, news_drivers = _news_capex_pressure(news_intelligence)
    score += news_pressure
    drivers.extend(news_drivers)

    financials = dict(financials_intelligence or {})
    financial_summary = dict(financials.get("summary", {}) or {})
    financial_stress_rows = [
        dict(row or {})
        for row in list(financials.get("stress", []) or [])
        if str(dict(row or {}).get("symbol") or "").strip().upper() in set(symbols)
    ]
    stressed = [row for row in financial_stress_rows if str(row.get("stress_state") or "").upper() == "STRESS"]
    cautious = [row for row in financial_stress_rows if str(row.get("stress_state") or "").upper() == "CAUTION"]
    if stressed:
        score += min(24.0, len(stressed) * 8.0)
        drivers.append("financial statement stress: " + ", ".join(str(row.get("symbol") or "") for row in stressed[:5]))
    if cautious:
        score += min(12.0, len(cautious) * 3.0)
        drivers.append("financial statement caution: " + ", ".join(str(row.get("symbol") or "") for row in cautious[:5]))

    score = round(max(min(score, 100.0), 0.0), 1)
    if score >= 75:
        state = "CRISIS_WATCH"
    elif score >= 55:
        state = "STRESS"
    elif score >= 35:
        state = "CAUTION"
    else:
        state = "LOW"

    hard_financial_data = str(financial_summary.get("hard_financial_data") or "").upper()
    if not hard_financial_data:
        hard_financial_data = "MISSING"
    if hard_financial_data == "MISSING":
        warnings.append("Reported capex, debt, and free-cash-flow metrics are not yet available from a financial statement source.")

    confidence = 0.8 - 0.12 * len(warnings)
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": "READY" if confidence > 0.4 else "PARTIAL",
        "ai_capex_stress": state,
        "systemic_risk_score": score,
        "ai_supply_chain_correlation": ai_corr,
        "ai_infra_symbols_observed": ai_symbols,
        "top_drivers": drivers[:8],
        "financial_statement_stress": {
            "hard_financial_data": hard_financial_data,
            "stress_count": int(financial_summary.get("stress_count", 0) or 0),
            "caution_count": int(financial_summary.get("caution_count", 0) or 0),
            "covered_count": int(financial_summary.get("covered_count", 0) or 0),
            "top_stress_symbols": list(financial_summary.get("top_stress_symbols", []) or [])[:8],
        },
        "confidence": round(max(confidence, 0.1), 2),
        "data_freshness": {
            "hard_financial_data": hard_financial_data,
            "market_data": "AVAILABLE" if histories else "MISSING",
            "llm_text_extraction": "AVAILABLE" if news_intelligence else "MISSING",
        },
        "warnings": warnings,
    }
