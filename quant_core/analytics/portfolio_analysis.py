from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from quant_core import paths as qpaths
from quant_core.analytics.monte_carlo import simulate_return_distribution
from quant_core.portfolio.metrics import summarize_holdings
from quant_core.portfolio.position import recommend_position_action, summarize_backtest_guidance
from quant_core.common.share_utils import format_share_quantity
from quant_core.common.signal_approval import approve_signal
from quant_core.analytics.signal_scoreboard import build_signal_scoreboard


DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE = qpaths.QUANT_ANALYSIS_SNAPSHOT_FILE


def _clone_runtime_strategy(strategy: Mapping, *, history_period: str) -> dict:
    runtime_strategy = dict(strategy or {})
    params = dict(runtime_strategy.get("params", {}) or {})
    params["period"] = history_period or params.get("period", "2y")
    runtime_strategy["params"] = params
    return runtime_strategy


def load_default_runtime_strategy(
    *,
    history_period: str = "2y",
    strategies: Optional[Iterable[Mapping]] = None,
) -> Optional[dict]:
    from strategies import ui as su

    strategy_list = list(strategies or su.load_strategies())
    if not strategy_list:
        return None
    default_strategy_id = su.get_default_strategy_id(strategy_list)
    strategy = next((item for item in strategy_list if item.get("id") == default_strategy_id), strategy_list[0])
    return _clone_runtime_strategy(strategy, history_period=history_period)


def _tracked_items(data: Mapping) -> list[tuple[str, dict]]:
    records = []
    seen = set()

    for holding in data.get("holdings", []) or []:
        symbol = str(holding.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        records.append(("holding", dict(holding)))

    for watch in data.get("watchlist", []) or []:
        symbol = str(watch.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        records.append(("watchlist", dict(watch)))

    return records


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


def _parse_datetime(value) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_dict(value):
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    payload = {}
    for name in dir(value):
        if name.startswith("_"):
            continue
        attr = getattr(value, name)
        if callable(attr):
            continue
        payload[name] = attr
    return payload


def _scoreboard_to_dict(scoreboard):
    if scoreboard is None:
        return {}
    regime_breakdown = []
    for item in list(getattr(scoreboard, "regime_breakdown", []) or []):
        regime_breakdown.append(
            {
                "regime": getattr(item, "regime", None),
                "trades": int(getattr(item, "trades", 0) or 0),
                "win_rate": getattr(item, "win_rate", None),
                "avg_return_pct": getattr(item, "avg_return_pct", None),
            }
        )
    return {
        "completed_trades": int(getattr(scoreboard, "completed_trades", 0) or 0),
        "win_rate": getattr(scoreboard, "win_rate", None),
        "avg_return_pct": getattr(scoreboard, "avg_return_pct", None),
        "avg_win_return_pct": getattr(scoreboard, "avg_win_return_pct", None),
        "avg_loss_return_pct": getattr(scoreboard, "avg_loss_return_pct", None),
        "payoff_ratio": getattr(scoreboard, "payoff_ratio", None),
        "expectancy_return_pct": getattr(scoreboard, "expectancy_return_pct", None),
        "profit_factor": getattr(scoreboard, "profit_factor", None),
        "median_holding_days": getattr(scoreboard, "median_holding_days", None),
        "cumulative_return_pct": getattr(scoreboard, "cumulative_return_pct", None),
        "max_drawdown_pct": getattr(scoreboard, "max_drawdown_pct", None),
        "regime_breakdown": regime_breakdown,
    }


def _signal_bucket(signal: str) -> str:
    normalized = str(signal or "").strip().upper()
    if "BUY" in normalized:
        return "buy"
    if "SELL" in normalized:
        return "sell"
    return "hold"


def _expected_return_hint(record: Mapping) -> Optional[float]:
    for branch in ("monte_carlo", "guidance", "scoreboard"):
        payload = record.get(branch) or {}
        for key in ("expected_return_pct", "expected_return", "expectancy_return_pct"):
            value = _safe_float(payload.get(key))
            if value is not None:
                return value
    return None


def _build_position_advice_text(advice: Optional[Mapping]) -> str:
    if not advice:
        return "WATCH"
    action = str(advice.get("action", "HOLD")).upper()
    if action == "ADD":
        delta_text = format_share_quantity(abs(_safe_float(advice.get("delta_shares"), 0.0) or 0.0))
        return f"ADD {delta_text}"
    if action == "TRIM":
        delta_text = format_share_quantity(abs(_safe_float(advice.get("delta_shares"), 0.0) or 0.0))
        return f"TRIM {delta_text}"
    if action == "EXIT":
        return "EXIT"
    return "HOLD"


def _safe_holdings_summary(data: Optional[Mapping]):
    valid_holdings = []
    for row in list((data or {}).get("holdings", []) or []):
        try:
            if row.get("shares") is None or row.get("cost") is None:
                continue
            float(row.get("shares"))
            float(row.get("cost"))
        except (TypeError, ValueError):
            continue
        valid_holdings.append(row)
    return summarize_holdings(valid_holdings)


def _snapshot_symbol_map(snapshot: Optional[Mapping]) -> dict:
    mapped = {}
    for row in list((snapshot or {}).get("symbols", []) or []):
        symbol = str((row or {}).get("symbol", "")).strip().upper()
        if symbol:
            mapped[symbol] = dict(row or {})
    return mapped


def load_quant_analysis_snapshot(*, path: Optional[str] = None):
    snapshot_path = Path(path or DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE)
    if not snapshot_path.exists():
        return None
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_quant_analysis_snapshot(snapshot: Mapping, *, path: Optional[str] = None):
    snapshot_path = Path(path or DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(snapshot_path)


def build_quant_analysis_change_summary(previous_snapshot: Optional[Mapping], current_snapshot: Optional[Mapping], *, max_changes: int = 8):
    current_snapshot = dict(current_snapshot or {})
    current_map = _snapshot_symbol_map(current_snapshot)
    previous_map = _snapshot_symbol_map(previous_snapshot)

    signal_changes = []
    action_changes = []
    new_symbols = []
    changed_symbols = []

    for symbol, current_row in current_map.items():
        previous_row = previous_map.get(symbol)
        if previous_row is None:
            new_symbols.append(symbol)
            changed_symbols.append(symbol)
            continue

        prev_signal = str(previous_row.get("signal", "HOLD") or "HOLD").upper()
        curr_signal = str(current_row.get("signal", "HOLD") or "HOLD").upper()
        if prev_signal != curr_signal:
            signal_changes.append((symbol, prev_signal, curr_signal))
            changed_symbols.append(symbol)

        prev_action = str(((previous_row.get("position_advice") or {}).get("action")) or "HOLD").upper()
        curr_action = str(((current_row.get("position_advice") or {}).get("action")) or "HOLD").upper()
        if prev_action != curr_action:
            action_changes.append((symbol, prev_action, curr_action))
            if symbol not in changed_symbols:
                changed_symbols.append(symbol)

    prev_top_buys = list((previous_snapshot or {}).get("summary", {}).get("top_buy_symbols", []) or [])
    curr_top_buys = list((current_snapshot or {}).get("summary", {}).get("top_buy_symbols", []) or [])
    top_buy_changed = prev_top_buys != curr_top_buys
    has_changes = bool(new_symbols or signal_changes or action_changes or top_buy_changed)

    lines = [
        "Quant analysis change summary",
        f"Generated: {str(current_snapshot.get('generated_at') or '')}",
    ]
    if new_symbols:
        lines.append("New symbols: " + ", ".join(new_symbols[:max_changes]))
    if signal_changes:
        signal_fragments = [f"{symbol}: {before} -> {after}" for symbol, before, after in signal_changes[:max_changes]]
        lines.append("Signal changes: " + "; ".join(signal_fragments))
    if action_changes:
        action_fragments = [f"{symbol}: {before} -> {after}" for symbol, before, after in action_changes[:max_changes]]
        lines.append("Action changes: " + "; ".join(action_fragments))
    if top_buy_changed:
        lines.append("Top buys: " + (", ".join(curr_top_buys) if curr_top_buys else "-"))
    if not has_changes:
        lines.append("No material quant-analysis changes detected.")

    return {
        "has_changes": has_changes,
        "is_initial": previous_snapshot is None,
        "changed_symbols": changed_symbols,
        "signal_changes": signal_changes,
        "action_changes": action_changes,
        "new_symbols": new_symbols,
        "top_buy_changed": top_buy_changed,
        "message": "\n".join(lines),
    }


def _price_map_from_data(data: Optional[Mapping]) -> dict:
    prices = {}
    data = data or {}
    for row in list(data.get("holdings", []) or []):
        symbol = str(row.get("symbol", "")).strip().upper()
        price = _safe_float(row.get("current_price"))
        if symbol and price is not None and price > 0:
            prices[symbol] = price
    for row in list(data.get("watchlist", []) or []):
        symbol = str(row.get("symbol", "")).strip().upper()
        price = _safe_float(row.get("last_price"))
        if symbol and price is not None and price > 0 and symbol not in prices:
            prices[symbol] = price
    return prices


def _tracked_symbol_set(data: Optional[Mapping]) -> set[str]:
    return set(_price_map_from_data(data).keys())


def _snapshot_generated_at(snapshot: Optional[Mapping]) -> Optional[datetime]:
    return _parse_datetime((snapshot or {}).get("generated_at"))


def _snapshot_regime(snapshot: Optional[Mapping], key: str) -> str:
    branch = dict((snapshot or {}).get(key, {}) or {})
    return str(branch.get("regime") or "").strip().upper()


def _normalize_datetime_pair(now, other: Optional[datetime]) -> tuple[datetime, Optional[datetime]]:
    if not isinstance(now, datetime):
        now = datetime.now()
    if other is None:
        return now, None
    if now.tzinfo is None and other.tzinfo is not None:
        now = now.replace(tzinfo=other.tzinfo)
    elif now.tzinfo is not None and other.tzinfo is None:
        other = other.replace(tzinfo=now.tzinfo)
    return now, other


def evaluate_auto_refresh_trigger(
    before_data: Mapping,
    after_data: Mapping,
    *,
    previous_snapshot: Optional[Mapping] = None,
    risk_decision=None,
    event_decision=None,
    active_events: Optional[Iterable] = None,
    now: Optional[datetime] = None,
    price_jump_threshold: float = 0.03,
    min_interval_seconds: int = 7200,
):
    now = now or datetime.now()
    previous_generated_at = _snapshot_generated_at(previous_snapshot)
    now, previous_generated_at = _normalize_datetime_pair(now, previous_generated_at)
    snapshot_age_seconds = None
    if previous_generated_at is not None:
        snapshot_age_seconds = max((now - previous_generated_at).total_seconds(), 0.0)

    before_prices = _price_map_from_data(before_data)
    after_prices = _price_map_from_data(after_data)
    price_jumps = []
    for symbol, after_price in after_prices.items():
        before_price = before_prices.get(symbol)
        if before_price is None or before_price <= 0:
            continue
        pct_change = after_price / before_price - 1.0
        if abs(pct_change) >= float(price_jump_threshold):
            price_jumps.append({"symbol": symbol, "pct_change": pct_change})
    price_jumps.sort(key=lambda item: abs(float(item["pct_change"])), reverse=True)

    tracked_symbols = _tracked_symbol_set(after_data)
    snapshot_symbols = {
        str((row or {}).get("symbol", "")).strip().upper()
        for row in list((previous_snapshot or {}).get("symbols", []) or [])
        if (row or {}).get("symbol")
    }
    symbol_universe_changed = previous_snapshot is None or tracked_symbols != snapshot_symbols

    current_risk_regime = str(getattr(risk_decision, "regime", "") or "").strip().upper()
    previous_risk_regime = _snapshot_regime(previous_snapshot, "risk")
    risk_regime_changed = bool(current_risk_regime and current_risk_regime != previous_risk_regime)

    current_event_regime = str(getattr(event_decision, "regime", "") or "").strip().upper()
    previous_event_regime = _snapshot_regime(previous_snapshot, "event_risk")
    event_regime_changed = bool(current_event_regime and current_event_regime != previous_event_regime)
    high_impact_events = [
        event
        for event in list(active_events or [])
        if str(getattr(event, "severity", "") or "").strip().lower() == "high"
        or str(getattr(event, "event_type", "") or "").strip().lower() in {"fomc", "geopolitical", "policy"}
    ]

    bypass_cooldown = symbol_universe_changed or risk_regime_changed or event_regime_changed or bool(high_impact_events)
    cooldown_active = (
        snapshot_age_seconds is not None
        and snapshot_age_seconds < float(min_interval_seconds)
        and not bypass_cooldown
    )

    should_run = False
    reason_lines = []
    if previous_snapshot is None:
        should_run = True
        reason_lines.append("No previous quant-analysis snapshot found.")
    if symbol_universe_changed and previous_snapshot is not None:
        should_run = True
        reason_lines.append("Tracked symbol set changed.")
    if risk_regime_changed:
        should_run = True
        reason_lines.append(f"Risk regime changed: {previous_risk_regime or '-'} -> {current_risk_regime}.")
    if event_regime_changed and current_event_regime in {"CAUTION", "RISK_OFF"}:
        should_run = True
        reason_lines.append(f"Event risk regime changed: {previous_event_regime or '-'} -> {current_event_regime}.")
    if high_impact_events and current_event_regime in {"CAUTION", "RISK_OFF", "NORMAL"}:
        should_run = True
        event_titles = ", ".join(str(getattr(event, "title", "") or "") for event in high_impact_events[:3])
        reason_lines.append(f"High-impact active events: {event_titles}.")
    if price_jumps and not cooldown_active:
        should_run = True
        fragments = [f"{item['symbol']} {float(item['pct_change']):+.2%}" for item in price_jumps[:5]]
        reason_lines.append("Price jump detected: " + ", ".join(fragments) + ".")
    elif price_jumps and cooldown_active:
        reason_lines.append("Price jump detected but skipped by cooldown.")

    if not should_run:
        reason_lines.append("No auto full-analysis trigger fired.")

    return {
        "should_run": should_run,
        "cooldown_active": cooldown_active,
        "price_jumps": price_jumps,
        "symbol_universe_changed": symbol_universe_changed,
        "risk_regime_changed": risk_regime_changed,
        "event_regime_changed": event_regime_changed,
        "high_impact_event_count": len(high_impact_events),
        "message": "\n".join(["Auto full-analysis trigger"] + reason_lines),
    }


def build_portfolio_quant_analysis_snapshot(
    data: Mapping,
    *,
    strategy: Mapping,
    history_period: Optional[str] = None,
    engine_name: str = "backtrader",
    initial_cash: float = 100000.0,
    load_historical_data_fn: Optional[Callable[..., object]] = None,
    get_signal_fn: Optional[Callable[[Mapping, str], tuple[str, str]]] = None,
    create_strategy_fn: Optional[Callable[[Mapping], object]] = None,
    engine_factory_fn: Optional[Callable[[], object]] = None,
    scoreboard_builder: Callable[..., object] = build_signal_scoreboard,
    guidance_builder: Callable[..., object] = summarize_backtest_guidance,
    monte_carlo_fn: Callable[..., object] = simulate_return_distribution,
    recommend_position_action_fn: Callable[..., object] = recommend_position_action,
    risk_gate=None,
    allocation_regime=None,
    active_events: Optional[Iterable] = None,
    event_decision=None,
    now: Optional[datetime] = None,
):
    if not strategy:
        raise ValueError("strategy is required")

    now = now if isinstance(now, datetime) else datetime.now()
    history_period = history_period or str(dict(strategy.get("params", {}) or {}).get("period") or "2y")
    runtime_strategy = _clone_runtime_strategy(strategy, history_period=history_period)
    load_historical_data_fn = load_historical_data_fn or __import__(
        "quant_core.analytics.quant_analysis", fromlist=["get_historical_data"]
    ).get_historical_data
    if get_signal_fn is None:
        from strategies import ui as su

        get_signal_fn = su.get_signal
    if create_strategy_fn is None:
        from strategies.registry import create_strategy

        create_strategy_fn = create_strategy
    if engine_factory_fn is None:
        from engine import BacktraderEngine

        engine_factory_fn = lambda: BacktraderEngine(initial_cash=initial_cash)

    tracked_items = _tracked_items(data or {})
    holdings_summary = _safe_holdings_summary(data or {})
    symbols = []

    summary = {
        "total_symbols": len(tracked_items),
        "analyzed_symbols": 0,
        "buy_count": 0,
        "sell_count": 0,
        "hold_count": 0,
        "error_count": 0,
        "top_buy_symbols": [],
        "top_risk_symbols": [],
    }

    for list_type, item in tracked_items:
        symbol = str(item.get("symbol", "")).strip().upper()
        latest_price = _safe_float(item.get("current_price"))
        if latest_price is None:
            latest_price = _safe_float(item.get("last_price"))

        record = {
            "symbol": symbol,
            "list_type": list_type,
            "shares": _safe_float(item.get("shares")),
            "sector": str(item.get("sector", "") or "").strip(),
            "latest_price": latest_price,
            "signal": "HOLD",
            "raw_signal": "HOLD",
            "signal_reason": "",
            "error": None,
            "backtest": {},
            "scoreboard": {},
            "guidance": None,
            "monte_carlo": None,
            "position_advice": None,
        }

        try:
            history = load_historical_data_fn(symbol, period=history_period)
            if history is None or getattr(history, "empty", False):
                raise ValueError("history unavailable")

            latest_price = _safe_float(getattr(history["Close"], "iloc", history["Close"])[-1], latest_price)
            record["latest_price"] = latest_price

            raw_signal, signal_reason = get_signal_fn(runtime_strategy, symbol)
            approval = approve_signal(raw_signal, risk_gate=risk_gate)
            signal_reason = str(signal_reason or "").strip()
            if approval.blocked and approval.reason:
                signal_reason = f"{signal_reason} | {approval.reason}" if signal_reason else approval.reason
            record["raw_signal"] = approval.raw_signal
            record["signal"] = approval.approved_signal
            record["signal_reason"] = signal_reason

            strategy_config = dict(runtime_strategy)
            strategy_config["symbol"] = symbol
            strategy_obj = create_strategy_fn(strategy_config)
            engine = engine_factory_fn()
            engine.set_data(history)
            engine.set_strategy(strategy_obj)
            result = engine.run()

            guidance = guidance_builder(result.trade_log, current_price=latest_price)
            scoreboard = scoreboard_builder(
                result.trade_log,
                equity_curve=result.equity_curve,
                benchmark_history=history,
            )
            mc_dist = monte_carlo_fn(history, horizon_days=20, simulations=2000, seed=42)

            record["backtest"] = {
                "total_return": _safe_float(getattr(result, "total_return", None)),
                "sharpe_ratio": _safe_float(getattr(result, "sharpe_ratio", None)),
                "max_drawdown": _safe_float(getattr(result, "max_drawdown", None)),
                "win_rate": _safe_float(getattr(result, "win_rate", None)),
                "total_trades": int(_safe_float(getattr(result, "total_trades", 0), 0) or 0),
            }
            record["scoreboard"] = _scoreboard_to_dict(scoreboard)
            record["guidance"] = _to_dict(guidance)
            record["monte_carlo"] = _to_dict(mc_dist)

            if list_type == "holding" and holdings_summary.total_value > 0:
                holding_payload = dict(item)
                holding_payload["current_price"] = latest_price
                advice = recommend_position_action_fn(
                    holding=holding_payload,
                    portfolio_value=holdings_summary.total_value,
                    signal=record["signal"],
                    signal_reason=record["signal_reason"],
                    guidance=guidance,
                    risk_gate=risk_gate,
                    allocation_regime=allocation_regime,
                )
                record["position_advice"] = _to_dict(advice)

            summary["analyzed_symbols"] += 1
            summary[f"{_signal_bucket(record['signal'])}_count"] += 1
        except Exception as exc:
            record["error"] = str(exc)
            summary["error_count"] += 1

        symbols.append(record)

    ranked_records = sorted(
        [record for record in symbols if not record.get("error")],
        key=lambda item: _expected_return_hint(item) or float("-inf"),
        reverse=True,
    )
    summary["top_buy_symbols"] = [
        record["symbol"]
        for record in ranked_records
        if _signal_bucket(record.get("signal")) == "buy"
    ][:5]
    summary["top_risk_symbols"] = [
        record["symbol"]
        for record in symbols
        if record.get("error") or _signal_bucket(record.get("signal")) == "sell"
    ][:5]

    return {
        "generated_at": now.isoformat(),
        "strategy": {
            "id": runtime_strategy.get("id"),
            "name": runtime_strategy.get("name", runtime_strategy.get("id")),
            "params": dict(runtime_strategy.get("params", {}) or {}),
        },
        "engine": {"name": str(engine_name or "backtrader")},
        "history_period": history_period,
        "summary": summary,
        "symbols": symbols,
        "portfolio_overview": {
            "holdings_count": len((data or {}).get("holdings", []) or []),
            "watchlist_count": len((data or {}).get("watchlist", []) or []),
            "holdings_market_value": holdings_summary.total_value,
            "holdings_cost_basis": holdings_summary.total_cost,
        },
        "risk": _to_dict(risk_gate) or {},
        "allocation_regime": _to_dict(allocation_regime) or {},
        "event_risk": _to_dict(event_decision) or {},
        "active_events": [
            {
                "title": str(getattr(event, "title", "") or ""),
                "severity": str(getattr(event, "severity", "") or ""),
                "event_type": str(getattr(event, "event_type", "") or ""),
                "symbols": list(getattr(event, "symbols", []) or []),
            }
            for event in list(active_events or [])[:20]
        ],
    }
