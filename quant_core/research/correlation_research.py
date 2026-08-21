from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

import pandas as pd

from quant_core import paths as qpaths


DEFAULT_CORRELATION_RESEARCH_FILE = qpaths.WEEKEND_CORRELATION_RESEARCH_FILE
DEFAULT_BENCHMARKS = ("SPY", "QQQ", "BIL", "GLD", "TLT", "USO")


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _symbol(value) -> str:
    return str(value or "").strip().upper()


def _close_series(history: pd.DataFrame, symbol: str) -> Optional[pd.Series]:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    series = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if len(series) < 4:
        return None
    series.name = symbol
    return series


def _portfolio_weights(holdings: Iterable[Mapping]) -> dict[str, float]:
    values = {}
    for row in list(holdings or []):
        symbol = _symbol(dict(row or {}).get("symbol"))
        if not symbol:
            continue
        shares = _safe_float(dict(row or {}).get("shares") or dict(row or {}).get("current_shares"), 0.0) or 0.0
        price = _safe_float(dict(row or {}).get("current_price") or dict(row or {}).get("last_price"), 0.0) or 0.0
        values[symbol] = values.get(symbol, 0.0) + max(shares * price, 0.0)
    total = sum(values.values())
    if total <= 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: value / total * 100.0 for symbol, value in values.items()}


def build_correlation_research_snapshot(
    *,
    symbols: Iterable[str],
    holdings: Iterable[Mapping] = (),
    load_history_fn: Callable[[str, str], pd.DataFrame],
    now: Optional[datetime] = None,
    period: str = "2y",
    benchmarks: Iterable[str] = DEFAULT_BENCHMARKS,
    high_correlation_threshold: float = 0.82,
    min_observations: int = 20,
) -> dict:
    now = now or datetime.now()
    ordered_symbols = []
    seen = set()
    for symbol in [*list(symbols or []), *list(benchmarks or [])]:
        normalized = _symbol(symbol)
        if normalized and normalized not in seen:
            ordered_symbols.append(normalized)
            seen.add(normalized)

    prices = []
    missing = []
    for symbol in ordered_symbols:
        try:
            history = load_history_fn(symbol, period)
        except TypeError:
            history = load_history_fn(symbol)
        except Exception:
            missing.append(symbol)
            continue
        series = _close_series(history, symbol)
        if series is None:
            missing.append(symbol)
            continue
        prices.append(series)

    if len(prices) < 2:
        return {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "status": "NO_DATA",
            "summary": {
                "status": "NO_DATA",
                "research_role": "RISK_AND_OPPORTUNITY_CLUES",
                "message": "可用历史数据不足，无法生成周末相关性研究。",
            },
            "missing_symbols": missing,
            "high_correlation_pairs": [],
            "portfolio_redundancy": [],
            "independent_strength": [],
        }

    price_frame = pd.concat(prices, axis=1).sort_index().ffill().dropna(how="all")
    returns = price_frame.pct_change().dropna(how="all")
    returns = returns.dropna(axis=1, thresh=max(3, min(min_observations, len(returns))))
    corr = returns.corr() if not returns.empty else pd.DataFrame()
    weights = _portfolio_weights(holdings)
    portfolio_symbols = [symbol for symbol in weights if symbol in corr.columns]

    high_pairs = []
    columns = list(corr.columns)
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1:]:
            value = _safe_float(corr.loc[left, right])
            if value is None or value < high_correlation_threshold:
                continue
            combined_weight = weights.get(left, 0.0) + weights.get(right, 0.0)
            high_pairs.append(
                {
                    "left": left,
                    "right": right,
                    "correlation": round(value, 4),
                    "combined_weight_pct": round(combined_weight, 4),
                    "research_note": "高度相关，工作日只作为重复押注/集中度风险线索，不直接触发交易。",
                }
            )
    high_pairs.sort(key=lambda row: (row["combined_weight_pct"], row["correlation"]), reverse=True)

    redundancy = [
        row for row in high_pairs
        if row["left"] in portfolio_symbols and row["right"] in portfolio_symbols
    ]

    independent_strength = []
    benchmark = "SPY" if "SPY" in returns.columns else None
    if benchmark:
        benchmark_return = float((1.0 + returns[benchmark].dropna()).prod() - 1.0)
        for symbol in columns:
            if symbol == benchmark:
                continue
            symbol_returns = returns[symbol].dropna()
            if symbol_returns.empty:
                continue
            total_return = float((1.0 + symbol_returns).prod() - 1.0)
            beta_corr = _safe_float(corr.loc[symbol, benchmark], 0.0) or 0.0
            independent_score = (total_return - benchmark_return) * (1.0 - abs(beta_corr))
            independent_strength.append(
                {
                    "symbol": symbol,
                    "period_return": round(total_return, 6),
                    "excess_vs_spy": round(total_return - benchmark_return, 6),
                    "correlation_to_spy": round(beta_corr, 4),
                    "independent_strength_score": round(independent_score, 6),
                    "research_note": "若同时具备基本面/行业确认，可进入卫星仓研究候选；单独不构成买入。",
                }
            )
    independent_strength.sort(key=lambda row: row["independent_strength_score"], reverse=True)

    status = "READY" if not corr.empty else "NO_DATA"
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": status,
        "period": period,
        "summary": {
            "status": status,
            "research_role": "RISK_AND_OPPORTUNITY_CLUES",
            "symbol_count": len(columns),
            "missing_symbol_count": len(missing),
            "high_correlation_pair_count": len(high_pairs),
            "portfolio_redundancy_count": len(redundancy),
            "independent_strength_count": len(independent_strength),
            "message": "周末相关性研究只提供风险和机会线索，工作日不直接产生买卖指令。",
        },
        "missing_symbols": missing,
        "high_correlation_pairs": high_pairs[:50],
        "portfolio_redundancy": redundancy[:20],
        "independent_strength": independent_strength[:25],
        "correlation_matrix": corr.round(4).to_dict() if not corr.empty else {},
    }


def save_correlation_research_snapshot(snapshot: Mapping, *, path: str = DEFAULT_CORRELATION_RESEARCH_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def load_correlation_research_snapshot(*, path: str = DEFAULT_CORRELATION_RESEARCH_FILE) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}

