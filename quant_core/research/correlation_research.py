from __future__ import annotations

import json
import math
from time import time as unix_time
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
    progress_callback=None,
) -> dict:
    now = now or datetime.now()
    started = unix_time()
    ordered_symbols = []
    seen = set()
    for symbol in [*list(symbols or []), *list(benchmarks or [])]:
        normalized = _symbol(symbol)
        if normalized and normalized not in seen:
            ordered_symbols.append(normalized)
            seen.add(normalized)

    prices = []
    missing = []
    if progress_callback:
        progress_callback(
            stage="load_history",
            progress_pct=5,
            detail=f"loading historical prices for {len(ordered_symbols)} symbols",
            symbol_count=len(ordered_symbols),
        )
    for index, symbol in enumerate(ordered_symbols, start=1):
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
        if progress_callback and (index == len(ordered_symbols) or index % 25 == 0):
            progress_callback(
                stage="load_history",
                progress_pct=min(45, 5 + int(index / max(len(ordered_symbols), 1) * 40)),
                detail=f"loaded {index}/{len(ordered_symbols)} histories",
                symbol_count=len(ordered_symbols),
                usable_symbol_count=len(prices),
                failed_symbol_count=len(missing),
            )

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
            "research_stages": [
                {"name": "load_history", "status": "completed", "symbols": len(ordered_symbols), "usable": len(prices)},
                {"name": "correlation_matrix", "status": "skipped", "reason": "not enough data"},
            ],
            "algorithms": ["history_loader"],
        }

    if progress_callback:
        progress_callback(stage="correlation_matrix", progress_pct=55, detail="building return correlation matrix")
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

    if progress_callback:
        progress_callback(stage="cross_sectional_mining", progress_pct=70, detail="ranking independent strength and return leaders")
    independent_strength = []
    return_leaders = []
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
            return_leaders.append(
                {
                    "symbol": symbol,
                    "period_return": round(total_return, 6),
                    "excess_vs_spy": round(total_return - benchmark_return, 6),
                    "correlation_to_spy": round(beta_corr, 4),
                }
            )
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
    return_leaders.sort(key=lambda row: row["period_return"], reverse=True)
    clusters = _build_correlation_clusters(high_pairs)

    status = "READY" if not corr.empty else "NO_DATA"
    elapsed = max(unix_time() - started, 0.0)
    if progress_callback:
        progress_callback(
            stage="completed",
            progress_pct=100,
            detail=f"correlation research completed in {elapsed:.1f}s",
            symbol_count=len(ordered_symbols),
            usable_symbol_count=len(columns),
            failed_symbol_count=len(missing),
        )
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": status,
        "period": period,
        "elapsed_seconds": round(elapsed, 3),
        "algorithms": [
            "cross_asset_return_correlation",
            "portfolio_redundancy_scan",
            "independent_strength_rank",
            "simple_correlation_cluster_mining",
        ],
        "research_stages": [
            {"name": "load_history", "status": "completed", "symbol_count": len(ordered_symbols), "usable_symbol_count": len(columns), "missing_symbol_count": len(missing)},
            {"name": "correlation_matrix", "status": "completed", "observation_count": int(len(returns)), "column_count": len(columns)},
            {"name": "portfolio_redundancy_scan", "status": "completed", "result_count": len(redundancy)},
            {"name": "independent_strength_rank", "status": "completed", "result_count": len(independent_strength)},
            {"name": "cluster_mining", "status": "completed", "result_count": len(clusters)},
        ],
        "summary": {
            "status": status,
            "research_role": "RISK_AND_OPPORTUNITY_CLUES",
            "symbol_count": len(columns),
            "requested_symbol_count": len(ordered_symbols),
            "missing_symbol_count": len(missing),
            "high_correlation_pair_count": len(high_pairs),
            "portfolio_redundancy_count": len(redundancy),
            "independent_strength_count": len(independent_strength),
            "return_leader_count": len(return_leaders),
            "cluster_count": len(clusters),
            "message": "周末相关性研究只提供风险和机会线索，工作日不直接产生买卖指令。",
        },
        "missing_symbols": missing,
        "high_correlation_pairs": high_pairs[:50],
        "portfolio_redundancy": redundancy[:20],
        "independent_strength": independent_strength[:25],
        "return_leaders": return_leaders[:25],
        "correlation_clusters": clusters[:20],
        "correlation_matrix": corr.round(4).to_dict() if not corr.empty else {},
    }


def _build_correlation_clusters(high_pairs: Iterable[Mapping]) -> list[dict]:
    graph: dict[str, set[str]] = {}
    for row in list(high_pairs or []):
        left = _symbol(dict(row or {}).get("left"))
        right = _symbol(dict(row or {}).get("right"))
        if not left or not right:
            continue
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    clusters = []
    seen = set()
    for symbol in sorted(graph):
        if symbol in seen:
            continue
        stack = [symbol]
        members = set()
        while stack:
            current = stack.pop()
            if current in members:
                continue
            members.add(current)
            stack.extend(sorted(graph.get(current, set()) - members))
        seen.update(members)
        if len(members) < 2:
            continue
        edge_count = 0
        correlations = []
        for row in list(high_pairs or []):
            left = _symbol(dict(row or {}).get("left"))
            right = _symbol(dict(row or {}).get("right"))
            if left in members and right in members:
                edge_count += 1
                value = _safe_float(dict(row or {}).get("correlation"))
                if value is not None:
                    correlations.append(value)
        clusters.append(
            {
                "members": sorted(members),
                "member_count": len(members),
                "edge_count": edge_count,
                "average_correlation": round(sum(correlations) / len(correlations), 4) if correlations else None,
                "research_note": "同一簇内标的可能代表相似风险暴露；用于减少重复押注或寻找主题扩散线索。",
            }
        )
    clusters.sort(key=lambda row: (row["member_count"], row["edge_count"], row.get("average_correlation") or 0), reverse=True)
    return clusters


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
