from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from time import time as unix_time
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from quant_core import paths as qpaths


US_MARKET_TZ = ZoneInfo("America/New_York")
DEFAULT_REPORTS_DIR = str(qpaths.PROJECT_ROOT / "reports")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    offset = (current.weekday() - weekday) % 7
    return current - timedelta(days=offset)


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _easter_date(year: int) -> date:
    # Gregorian computus. Good Friday is an NYSE holiday.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def us_market_holidays(year: int) -> set[date]:
    return {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_date(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_fixed_holiday(year, 6, 19),  # Juneteenth
        _observed_fixed_holiday(year, 7, 4),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed_holiday(year, 12, 25),  # Christmas
    }


def _mapping_value(payload, key, default=None):
    if payload is None:
        return default
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            return None


def _resolve_day(day=None):
    if day is None:
        return datetime.now().date()
    if isinstance(day, datetime):
        return day.date()
    parsed = _parse_datetime(day)
    if parsed is not None:
        return parsed.date()
    return datetime.fromisoformat(f"{str(day).strip()}T00:00:00").date()


def _with_local_timezone(now: datetime) -> datetime:
    if now.tzinfo is not None:
        return now
    local_tz = datetime.now().astimezone().tzinfo
    return now.replace(tzinfo=local_tz)


def _format_money(value) -> str:
    amount = _float(value)
    if amount is None:
        return "-"
    return f"${amount:,.2f}"


def _format_pct(value, *, scale=100.0, digits=1) -> str:
    number = _float(value)
    if number is None:
        return "-"
    return f"{number * scale:.{digits}f}%"


def _format_source_with_role(source_name, *, primary_source=None) -> str:
    source = str(source_name or "").strip().lower()
    primary = str(primary_source or "").strip().lower()
    if not source:
        return "unknown"
    if primary and source == primary:
        return f"{source} (primary)"
    if primary:
        return f"{source} (fallback)"
    return source


def is_us_market_session(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now().astimezone()
    if not isinstance(now, datetime):
        return False
    market_now = _with_local_timezone(now).astimezone(US_MARKET_TZ)
    if not is_us_market_trading_day(market_now):
        return False
    start_minutes = 9 * 60 + 30
    current_minutes = market_now.hour * 60 + market_now.minute
    end_minutes = 16 * 60
    return start_minutes <= current_minutes < end_minutes


def is_us_market_trading_day(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now().astimezone()
    if isinstance(now, datetime):
        market_day = _with_local_timezone(now).astimezone(US_MARKET_TZ).date()
    elif isinstance(now, date):
        market_day = now
    else:
        return False
    if market_day.weekday() >= 5:
        return False
    holiday_dates = (
        us_market_holidays(market_day.year - 1)
        | us_market_holidays(market_day.year)
        | us_market_holidays(market_day.year + 1)
    )
    return market_day not in holiday_dates


def nightly_cycle_trading_day(now: Optional[datetime] = None) -> date:
    now = now or datetime.now()
    if isinstance(now, datetime):
        local_now = _with_local_timezone(now)
        return (local_now.date() if local_now.hour == 23 else (local_now - timedelta(days=1)).date())
    if isinstance(now, date):
        return now
    return datetime.now().date()


def is_us_market_nightly_cycle_trading_day(now: Optional[datetime] = None) -> bool:
    return is_us_market_trading_day(nightly_cycle_trading_day(now))


def _extract_price_map(data):
    price_map = {}
    data = data or {}
    for record in data.get("holdings", []) or []:
        symbol = str(record.get("symbol", "")).strip().upper()
        price = _float(record.get("current_price"))
        if symbol and price is not None:
            price_map[symbol] = price
    for record in data.get("watchlist", []) or []:
        symbol = str(record.get("symbol", "")).strip().upper()
        price = _float(record.get("last_price"))
        if symbol and price is not None and symbol not in price_map:
            price_map[symbol] = price
    return price_map


def _format_top_movers(before_data, after_data, *, limit=3) -> str:
    before_prices = _extract_price_map(before_data)
    after_prices = _extract_price_map(after_data)
    movers = []
    for symbol, after_price in after_prices.items():
        before_price = before_prices.get(symbol)
        if before_price is None or before_price <= 0:
            continue
        pct_change = after_price / before_price - 1.0
        movers.append((abs(pct_change), symbol, pct_change, after_price))
    movers.sort(reverse=True)
    if not movers:
        return "No tracked price changes captured in this refresh."
    top = []
    for _, symbol, pct_change, price in movers[:limit]:
        top.append(f"{symbol} {pct_change:+.2%} -> {_format_money(price)}")
    return "; ".join(top)


def build_signal_attribution(records, *, day=None):
    target_day = _resolve_day(day)
    effective = []
    ineffective = []
    flat = []
    buy_symbols = []
    sold_symbols = set()

    for record in records or []:
        record_type = str(record.get("record_type", "TRADE")).strip().upper()
        if record_type not in {"", "TRADE"}:
            continue
        record_dt = _parse_datetime(record.get("date"))
        if record_dt is None or record_dt.date() != target_day:
            continue
        symbol = str(record.get("symbol", "")).strip().upper()
        side = str(record.get("side", record.get("event_type", ""))).strip().upper()
        if side == "BUY":
            if symbol and symbol not in buy_symbols:
                buy_symbols.append(symbol)
            continue
        if side != "SELL":
            continue
        sold_symbols.add(symbol)
        pl_value = _float(record.get("pl"), 0.0) or 0.0
        detail = {
            "symbol": symbol,
            "pl": pl_value,
            "shares": _float(record.get("shares")),
            "price": _float(record.get("price")),
        }
        if pl_value > 0:
            effective.append(detail)
        elif pl_value < 0:
            ineffective.append(detail)
        else:
            flat.append(detail)

    pending_symbols = [symbol for symbol in buy_symbols if symbol not in sold_symbols]
    return {
        "day": target_day.isoformat(),
        "effective_count": len(effective),
        "ineffective_count": len(ineffective),
        "flat_count": len(flat),
        "pending_count": len(pending_symbols),
        "effective_symbols": [row["symbol"] for row in effective],
        "ineffective_symbols": [row["symbol"] for row in ineffective],
        "flat_symbols": [row["symbol"] for row in flat],
        "pending_symbols": pending_symbols,
        "best_signal": max(effective, key=lambda row: float(row.get("pl") or 0.0), default=None),
        "worst_signal": min(ineffective, key=lambda row: float(row.get("pl") or 0.0), default=None),
    }


def build_market_refresh_report(
    *,
    before_data,
    after_data,
    account_snapshot=None,
    risk_gate=None,
    allocation_regime=None,
    data_sources=None,
    now: Optional[datetime] = None,
) -> str:
    now = now or datetime.now()
    account_snapshot = account_snapshot or {}
    risk_gate = risk_gate or {}
    allocation_regime = allocation_regime or {}
    data_sources = data_sources or {}

    risk_regime = _mapping_value(risk_gate, "regime", "UNKNOWN")
    allocation_name = _mapping_value(allocation_regime, "regime", "UNKNOWN")
    prices_status = _mapping_value(data_sources, "prices", {})
    source_name = _mapping_value(prices_status, "last_source", "unknown")
    primary_source = _mapping_value(prices_status, "primary_source", None)
    fallback_count = int(_float(_mapping_value(prices_status, "fallback_symbols", 0), 0) or 0)

    lines = [
        "Hourly Market Refresh",
        f"Time: {now.strftime('%Y-%m-%d %H:%M')}",
        f"Holdings: {len((after_data or {}).get('holdings', []) or [])} | Watchlist: {len((after_data or {}).get('watchlist', []) or [])}",
        f"Capital: {_format_money(account_snapshot.get('total_capital'))} | Cash: {_format_money(account_snapshot.get('cash_available'))} | Exposure: {_format_pct(_float(account_snapshot.get('exposure_pct'), None), scale=1.0)}",
        f"Risk regime: {risk_regime} | Allocation regime: {allocation_name}",
        f"Price source: {_format_source_with_role(source_name, primary_source=primary_source)} | Fallback symbols: {fallback_count}",
        f"Top movers: {_format_top_movers(before_data, after_data)}",
    ]

    risk_reasons = list(_mapping_value(risk_gate, "reasons", []) or [])
    if risk_reasons:
        lines.append(f"Risk notes: {'; '.join(risk_reasons[:2])}")

    allocation_reasons = list(_mapping_value(allocation_regime, "reasons", []) or [])
    if allocation_reasons:
        lines.append(f"Allocation notes: {'; '.join(allocation_reasons[:2])}")

    return "\n".join(lines)


def build_nightly_report(snapshot: Mapping) -> str:
    snapshot = dict(snapshot or {})
    account = dict(snapshot.get("account", {}) or {})
    risk = dict(snapshot.get("risk", {}) or {})
    allocation_regime = dict(snapshot.get("allocation_regime", {}) or {})
    performance = dict(snapshot.get("performance", {}) or {})
    scoreboard = dict(performance.get("live_scoreboard", {}) or {})
    recap = dict(snapshot.get("daily_recap", {}) or {})
    signal_attribution = dict(snapshot.get("signal_attribution", {}) or {})
    trade_plan = dict(snapshot.get("trade_plan", {}) or {})
    execution_review = dict(snapshot.get("execution_review", {}) or {})
    core_etf_snapshot = dict(snapshot.get("core_etf_snapshot", {}) or {})
    satellite_candidate_snapshot = dict(snapshot.get("satellite_candidate_snapshot", {}) or {})
    discipline_snapshot = dict(snapshot.get("discipline_snapshot", {}) or {})
    monthly_discipline_review = dict(snapshot.get("monthly_discipline_review", {}) or {})
    strategy_validation_snapshot = dict(snapshot.get("strategy_validation_snapshot", {}) or {})
    data_health_snapshot = dict(snapshot.get("data_health_snapshot", {}) or {})
    plan_quality_snapshot = dict(snapshot.get("plan_quality_snapshot", {}) or {})
    market_monitor_snapshot = dict(snapshot.get("market_monitor_snapshot", {}) or {})
    strategy_governance_snapshot = dict(snapshot.get("strategy_governance_snapshot", {}) or {})
    multi_horizon_snapshot = dict(snapshot.get("multi_horizon_snapshot", {}) or {})
    news_intelligence = dict(snapshot.get("news_intelligence", {}) or {})
    decision_brief = dict(snapshot.get("decision_brief", {}) or {})
    intraday_event_summary = dict(snapshot.get("intraday_event_summary", {}) or {})
    change_feed = dict(snapshot.get("change_feed", {}) or {})
    nightly_manifest = dict(snapshot.get("nightly_manifest", {}) or {})
    alerts = list(snapshot.get("alerts", []) or [])

    if multi_horizon_snapshot:
        model_summary = dict(multi_horizon_snapshot.get("summary", {}) or {})
        model_info = dict(multi_horizon_snapshot.get("model", {}) or {})
        action_counts = dict(model_summary.get("action_counts", {}) or {})
        lines_model = (
            "Multi-horizon model: "
            f"status={multi_horizon_snapshot.get('status') or model_info.get('status') or 'UNKNOWN'} "
            f"version={model_info.get('version') or model_info.get('trained_at') or 'untrained'} "
            f"symbols={int(_float(model_summary.get('symbol_count'), 0) or 0)} "
            f"accumulate={int(_float(action_counts.get('ACCUMULATE'), 0) or 0)} "
            f"trim={int(_float(action_counts.get('TRIM'), 0) or 0)} "
            f"conflicts={int(_float(model_summary.get('conflict_count'), 0) or 0)}"
        )
    else:
        lines_model = "Multi-horizon model: status=MISSING"

    lines = [
        "Nightly Portfolio Report",
        f"Generated: {str(snapshot.get('generated_at') or '')}",
        f"Capital: {_format_money(account.get('total_capital'))} | Cash: {_format_money(account.get('cash_available'))} | Exposure: {_format_pct(_float(account.get('exposure_pct'), None), scale=1.0)}",
        f"Risk regime: {risk.get('regime', 'UNKNOWN')} (score={risk.get('risk_score', '-')})",
        f"Allocation regime: {allocation_regime.get('regime', 'UNKNOWN')}",
        f"Closed trades: {int(_float(scoreboard.get('completed_trades'), 0) or 0)} | Win rate: {_format_pct(scoreboard.get('win_rate'))} | Expectancy: {_format_pct(scoreboard.get('expectancy_return_pct'), digits=2)} | Profit factor: {(_float(scoreboard.get('profit_factor')) or 0.0):.2f}" if scoreboard else "Closed trades: 0",
        f"Daily recap: trades={int(_float(recap.get('trade_count'), 0) or 0)}, buys={int(_float(recap.get('buy_count'), 0) or 0)}, sells={int(_float(recap.get('sell_count'), 0) or 0)}, events={int(_float(recap.get('portfolio_event_count'), 0) or 0)}, realized P/L={_format_money(recap.get('realized_pl'))}",
        lines_model,
    ]

    symbols = ", ".join(recap.get("symbols", []) or [])
    if symbols:
        lines.append(f"Symbols touched: {symbols}")

    if signal_attribution:
        lines.append(
            "Signal attribution: "
            f"effective={int(_float(signal_attribution.get('effective_count'), 0) or 0)} "
            f"({', '.join(signal_attribution.get('effective_symbols', []) or []) or '-'}) | "
            f"ineffective={int(_float(signal_attribution.get('ineffective_count'), 0) or 0)} "
            f"({', '.join(signal_attribution.get('ineffective_symbols', []) or []) or '-'}) | "
            f"pending={int(_float(signal_attribution.get('pending_count'), 0) or 0)} "
            f"({', '.join(signal_attribution.get('pending_symbols', []) or []) or '-'})"
        )

    if strategy_validation_snapshot:
        validation_summary = dict(strategy_validation_snapshot.get("summary", {}) or {})
        lines.append(
            "Strategy validation: "
            f"status={validation_summary.get('status') or '—'} "
            f"coverage={int(_float(validation_summary.get('symbol_count'), 0) or 0)} "
            f"validated={int(_float(validation_summary.get('validated_count'), 0) or 0)} "
            f"warnings={len(list(validation_summary.get('warning_symbols', []) or []))}"
        )
        validation_message = str(validation_summary.get("message") or "").strip()
        if validation_message:
            lines.append(f"Strategy validation notes: {validation_message}")

    if strategy_governance_snapshot:
        governance_summary = dict(strategy_governance_snapshot.get("summary", {}) or {})
        lines.append(
            "Strategy governance: "
            f"status={governance_summary.get('status') or '—'} "
            f"default={governance_summary.get('default_strategy_id') or '—'} "
            f"review={int(_float(governance_summary.get('review_count'), 0) or 0)} "
            f"promotion_watch={int(_float(governance_summary.get('promotion_watch_count'), 0) or 0)}"
        )

    if data_health_snapshot:
        data_health_summary = dict(data_health_snapshot.get("summary", {}) or {})
        lines.append(
            "Data health: "
            f"status={data_health_summary.get('status') or data_health_snapshot.get('status') or '—'} "
            f"tracked={int(_float(data_health_summary.get('tracked_symbol_count'), 0) or 0)} "
            f"missing={int(_float(data_health_summary.get('missing_price_count'), 0) or 0)} "
            f"invalid={int(_float(data_health_summary.get('invalid_price_count'), 0) or 0)} "
            f"stale={int(_float(data_health_summary.get('stale_price_count'), 0) or 0)} "
            f"fallback={int(_float(data_health_summary.get('fallback_symbol_count'), 0) or 0)}"
        )

    if plan_quality_snapshot:
        plan_quality_summary = dict(plan_quality_snapshot.get("summary", {}) or {})
        lines.append(
            "Plan quality: "
            f"status={plan_quality_summary.get('status') or plan_quality_snapshot.get('status') or '—'} "
            f"reviews={int(_float(plan_quality_summary.get('review_count'), 0) or 0)} "
            f"executed={int(_float(plan_quality_summary.get('executed_count'), 0) or 0)} "
            f"missed_reachable={int(_float(plan_quality_summary.get('missed_reachable_count'), 0) or 0)} "
            f"unplanned={int(_float(plan_quality_summary.get('unplanned_trade_count'), 0) or 0)}"
        )

    if market_monitor_snapshot:
        monitor_summary = dict(market_monitor_snapshot.get("summary", {}) or {})
        lines.append(
            "Market monitor: "
            f"status={market_monitor_snapshot.get('status') or '—'} "
            f"state={monitor_summary.get('state') or '—'} "
            f"action={monitor_summary.get('recommended_action') or '—'} "
            f"symbol={monitor_summary.get('recommended_symbol') or '—'}"
        )

    if news_intelligence:
        llm_meta = dict(news_intelligence.get("llm", {}) or {})
        source_meta = dict(news_intelligence.get("source_status", {}) or {})
        lines.append(
            "News intelligence: "
            f"status={news_intelligence.get('status') or 'UNKNOWN'} "
            f"risk={news_intelligence.get('market_risk_level') or 'UNKNOWN'} "
            f"sources={source_meta.get('status') or 'UNKNOWN'} "
            f"source_ok={int(_float(source_meta.get('successful_source_count'), 0) or 0)} "
            f"source_failed={int(_float(source_meta.get('failed_source_count'), 0) or 0)} "
            f"route={llm_meta.get('route_name') or 'structured'} "
            f"model={llm_meta.get('model') or '-'}"
        )
        executive_summary = str(news_intelligence.get("executive_summary") or "").strip()
        if executive_summary:
            lines.append(f"News summary: {executive_summary}")
        for impact in list(news_intelligence.get("portfolio_impacts", []) or [])[:3]:
            impact = dict(impact or {})
            lines.append(
                "News impact: "
                f"{impact.get('symbol') or '-'} "
                f"{impact.get('direction') or 'NEUTRAL'} "
                f"confidence={_format_pct(impact.get('confidence'))} "
                f"action={impact.get('risk_action') or 'NONE'} | "
                f"{str(impact.get('summary') or '').strip()}"
            )

    if decision_brief:
        llm_meta = dict(decision_brief.get("llm", {}) or {})
        lines.append(
            "LLM decision brief: "
            f"status={decision_brief.get('status') or 'UNKNOWN'} "
            f"trigger={decision_brief.get('trigger') or 'UNKNOWN'} "
            f"actions={int(_float(decision_brief.get('approved_action_count'), 0) or 0)} "
            f"conflicts={int(_float(decision_brief.get('conflict_count'), 0) or 0)} "
            f"route={llm_meta.get('route_name') or 'structured'} "
            f"model={llm_meta.get('model') or '-'}"
        )
        decision_summary = str(decision_brief.get("executive_summary") or "").strip()
        if decision_summary:
            lines.append(f"Decision summary: {decision_summary}")

    if core_etf_snapshot:
        core_summary = dict(core_etf_snapshot.get("summary", {}) or {})
        lines.append(
            "Core ETF engine: "
            f"accumulate={int(_float(core_summary.get('accumulate_count'), 0) or 0)} "
            f"trim={int(_float(core_summary.get('trim_count'), 0) or 0)} "
            f"focus={', '.join(core_summary.get('focus_symbols', []) or []) or '-'}"
        )

    if satellite_candidate_snapshot:
        satellite_summary = dict(satellite_candidate_snapshot.get("summary", {}) or {})
        lines.append(
            "Satellite radar: "
            f"scanned={int(_float(satellite_summary.get('scanned_symbols'), 0) or 0)} "
            f"pool={int(_float(satellite_summary.get('candidate_count'), 0) or 0)} "
            f"deep={int(_float(satellite_summary.get('deep_analysis_count'), 0) or 0)} "
            f"top={', '.join(satellite_summary.get('top_symbols', []) or []) or '-'}"
        )
        lines.append(
            "Satellite status mix: "
            f"confirmed={int(_float(satellite_summary.get('confirmed_count'), 0) or 0)} "
            f"probe={int(_float(satellite_summary.get('probe_count'), 0) or 0)} "
            f"watch={int(_float(satellite_summary.get('watch_count'), 0) or 0)} "
            f"overheated={int(_float(satellite_summary.get('overheated_count'), 0) or 0)}"
        )

    if discipline_snapshot:
        lines.append(
            "Discipline: "
            f"{discipline_snapshot.get('regime', 'UNKNOWN')} | "
            f"core_new={'yes' if discipline_snapshot.get('can_open_new_core_positions') else 'no'} | "
            f"satellite_new={'yes' if discipline_snapshot.get('can_open_new_satellite_positions') else 'no'}"
        )
        discipline_summary = str(discipline_snapshot.get("summary") or "").strip()
        if discipline_summary:
            lines.append(f"Discipline summary: {discipline_summary}")

    if monthly_discipline_review:
        lines.append(
            "Discipline month: "
            f"status={monthly_discipline_review.get('status', 'MONITOR')} | "
            f"follow={int(_float(monthly_discipline_review.get('follow_days'), 0) or 0)} | "
            f"ignore={int(_float(monthly_discipline_review.get('ignore_days'), 0) or 0)} | "
            f"follow_pnl={_format_money(monthly_discipline_review.get('follow_realized_pl'))} | "
            f"ignore_pnl={_format_money(monthly_discipline_review.get('ignore_realized_pl'))}"
        )
        lines.append(
            "Discipline metrics: "
            f"follow_hit={_format_pct(monthly_discipline_review.get('follow_directional_hit_rate'), scale=100.0)} | "
            f"ignore_hit={_format_pct(monthly_discipline_review.get('ignore_directional_hit_rate'), scale=100.0)} | "
            f"override_penalty={_format_pct(monthly_discipline_review.get('defensive_override_penalty_rate'), scale=100.0)}"
        )
        discipline_month_summary = str(monthly_discipline_review.get("summary") or "").strip()
        if discipline_month_summary:
            lines.append(f"Discipline month summary: {discipline_month_summary}")

    if intraday_event_summary:
        lines.append(
            "Intraday event review: "
            f"reviewed={int(_float(intraday_event_summary.get('reviewed_count'), 0) or 0)} | "
            f"favorable={int(_float(intraday_event_summary.get('favorable_count'), 0) or 0)} | "
            f"unfavorable={int(_float(intraday_event_summary.get('unfavorable_count'), 0) or 0)} | "
            f"neutral={int(_float(intraday_event_summary.get('neutral_count'), 0) or 0)} | "
            f"unscored={int(_float(intraday_event_summary.get('unscored_count'), 0) or 0)}"
        )

    if trade_plan:
        lines.append(
            f"Next-day plan: {'ACTION' if trade_plan.get('has_actions') else 'NO_ACTION'} | "
            f"items={int(_float(trade_plan.get('action_count'), 0) or 0)}"
        )
        if str(trade_plan.get("decision_signature") or "").strip():
            lines.append(f"Decision signature: {str(trade_plan.get('decision_signature') or '').strip()}")
        summary_reason = str(trade_plan.get("summary_reason") or "").strip()
        if summary_reason:
            lines.append(f"Plan summary: {summary_reason}")

    if execution_review:
        lines.append(
            "Execution review: "
            f"executed={int(_float(execution_review.get('executed_count'), 0) or 0)} | "
            f"missed={int(_float(execution_review.get('missed_count'), 0) or 0)} | "
            f"unplanned={int(_float(execution_review.get('unplanned_trade_count'), 0) or 0)}"
        )
        lines.append(
            "Plan feasibility: "
            f"reachable={int(_float(execution_review.get('reachable_count'), 0) or 0)} | "
            f"missed_reachable={int(_float(execution_review.get('missed_reachable_count'), 0) or 0)} | "
            f"price_failures={int(_float(execution_review.get('price_failure_count'), 0) or 0)}"
        )

    if change_feed:
        summary = dict(change_feed.get("summary", {}) or {})
        lines.append(
            "Change feed: "
            f"H={int(_float(summary.get('high_count'), 0) or 0)} "
            f"M={int(_float(summary.get('medium_count'), 0) or 0)} "
            f"L={int(_float(summary.get('low_count'), 0) or 0)}"
        )

    if nightly_manifest:
        lines.append(
            "Nightly manifest: "
            f"run_id={nightly_manifest.get('run_id', '-') } | "
            f"status={nightly_manifest.get('status', 'unknown')} | "
            f"steps={len(dict(nightly_manifest.get('steps', {}) or {}))}"
        )

    if alerts:
        lines.append(f"Active alerts: {len(alerts)}")

    risk_reasons = list(risk.get("reasons", []) or [])
    if risk_reasons:
        lines.append(f"Risk notes: {'; '.join(risk_reasons[:2])}")

    allocation_reasons = list(allocation_regime.get("reasons", []) or [])
    if allocation_reasons:
        lines.append(f"Allocation notes: {'; '.join(allocation_reasons[:2])}")

    return "\n".join(lines)


def save_nightly_report_files(snapshot: Mapping, *, report_text: Optional[str] = None, reports_dir: Optional[str] = None):
    reports_path = Path(reports_dir or DEFAULT_REPORTS_DIR)
    reports_path.mkdir(parents=True, exist_ok=True)

    generated_at = _parse_datetime((snapshot or {}).get("generated_at")) or datetime.now()
    stem = generated_at.strftime("nightly_report_%Y%m%d_%H%M%S")
    markdown_path = reports_path / f"{stem}.md"
    json_path = reports_path / f"{stem}.json"

    resolved_report_text = report_text or build_nightly_report(snapshot or {})
    markdown_path.write_text(resolved_report_text, encoding="utf-8")
    json_path.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2), encoding="utf-8")

    latest_markdown = reports_path / "nightly_report_latest.md"
    latest_json = reports_path / "nightly_report_latest.json"
    latest_markdown.write_text(resolved_report_text, encoding="utf-8")
    latest_json.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "latest_markdown_path": str(latest_markdown),
        "latest_json_path": str(latest_json),
        "saved_at_unix": int(unix_time()),
    }
