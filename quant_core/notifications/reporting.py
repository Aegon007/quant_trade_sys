from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import time as unix_time
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from quant_core import paths as qpaths


US_MARKET_TZ = ZoneInfo("America/New_York")
DEFAULT_REPORTS_DIR = str(qpaths.PROJECT_ROOT / "reports")


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
        return float(value)
    except (TypeError, ValueError):
        return default


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


def is_us_market_session(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now().astimezone()
    if not isinstance(now, datetime):
        return False
    market_now = _with_local_timezone(now).astimezone(US_MARKET_TZ)
    if market_now.weekday() >= 5:
        return False
    start_minutes = 9 * 60 + 30
    current_minutes = market_now.hour * 60 + market_now.minute
    end_minutes = 16 * 60
    return start_minutes <= current_minutes < end_minutes


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
    source_name = _mapping_value(_mapping_value(data_sources, "prices", {}), "last_source", "unknown")
    fallback_count = int(_float(_mapping_value(_mapping_value(data_sources, "prices", {}), "fallback_symbols", 0), 0) or 0)

    lines = [
        "Hourly Market Refresh",
        f"Time: {now.strftime('%Y-%m-%d %H:%M')}",
        f"Holdings: {len((after_data or {}).get('holdings', []) or [])} | Watchlist: {len((after_data or {}).get('watchlist', []) or [])}",
        f"Capital: {_format_money(account_snapshot.get('total_capital'))} | Cash: {_format_money(account_snapshot.get('cash_available'))} | Exposure: {_format_pct(_float(account_snapshot.get('exposure_pct'), None), scale=1.0)}",
        f"Risk regime: {risk_regime} | Allocation regime: {allocation_name}",
        f"Price source: {source_name} | Fallback symbols: {fallback_count}",
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
    alerts = list(snapshot.get("alerts", []) or [])
    strategy_rows = list(performance.get("strategy_comparison", []) or [])

    lines = [
        "Nightly Portfolio Report",
        f"Generated: {str(snapshot.get('generated_at') or '')}",
        f"Capital: {_format_money(account.get('total_capital'))} | Cash: {_format_money(account.get('cash_available'))} | Exposure: {_format_pct(_float(account.get('exposure_pct'), None), scale=1.0)}",
        f"Risk regime: {risk.get('regime', 'UNKNOWN')} (score={risk.get('risk_score', '-')})",
        f"Allocation regime: {allocation_regime.get('regime', 'UNKNOWN')}",
        f"Closed trades: {int(_float(scoreboard.get('completed_trades'), 0) or 0)} | Win rate: {_format_pct(scoreboard.get('win_rate'))} | Expectancy: {_format_pct(scoreboard.get('expectancy_return_pct'), digits=2)} | Profit factor: {(_float(scoreboard.get('profit_factor')) or 0.0):.2f}" if scoreboard else "Closed trades: 0",
        f"Daily recap: trades={int(_float(recap.get('trade_count'), 0) or 0)}, buys={int(_float(recap.get('buy_count'), 0) or 0)}, sells={int(_float(recap.get('sell_count'), 0) or 0)}, events={int(_float(recap.get('portfolio_event_count'), 0) or 0)}, realized P/L={_format_money(recap.get('realized_pl'))}",
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

    if strategy_rows:
        leader = strategy_rows[0]
        strategy_name = leader.get("strategy_name") or leader.get("strategy") or leader.get("name") or "n/a"
        metric = leader.get("total_return_pct")
        if metric is None:
            metric = leader.get("total_return")
        metric_text = _format_pct(metric, digits=2) if metric is not None else "-"
        lines.append(f"Strategy leader: {strategy_name} ({metric_text})")

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
