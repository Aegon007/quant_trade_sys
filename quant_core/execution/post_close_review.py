from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.ledger import transactions as tx


DEFAULT_POST_CLOSE_REVIEW_FILE = qpaths.POST_CLOSE_REVIEW_FILE


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


def _parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
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


def _expected_side(plan_action: str) -> str:
    action = str(plan_action or "").strip().upper()
    if action in {"TRIM", "EXIT", "RISK_EXIT"}:
        return "SELL"
    return "BUY"


def _trade_rows_for_day(records, *, target_day):
    rows = []
    for record in tx.normalize_transactions(records):
        if str(record.get("record_type", "")).upper() != "TRADE":
            continue
        record_dt = _parse_datetime(record.get("date"))
        if record_dt is None or record_dt.date() != target_day:
            continue
        rows.append(record)
    return rows


def _executed_in_zone(item: Mapping, prices) -> Optional[bool]:
    if not prices:
        return None
    zone_low = item.get("buy_zone_low")
    zone_high = item.get("buy_zone_high")
    if zone_low is None or zone_high is None:
        zone_low = item.get("trim_zone_low")
        zone_high = item.get("trim_zone_high")
    if zone_low is None or zone_high is None:
        return None
    return all(float(zone_low) <= float(price) <= float(zone_high) for price in prices)


def _resolve_plan_zone(item: Mapping):
    zone_low = item.get("buy_zone_low")
    zone_high = item.get("buy_zone_high")
    if zone_low is None or zone_high is None:
        zone_low = item.get("trim_zone_low")
        zone_high = item.get("trim_zone_high")
    if zone_low is None or zone_high is None:
        return None, None
    try:
        return float(zone_low), float(zone_high)
    except (TypeError, ValueError):
        return None, None


def _plan_opportunity(item: Mapping, market_day_range: Optional[Mapping]) -> dict:
    market_day_range = dict(market_day_range or {})
    session_open = _safe_float(market_day_range.get("open"))
    session_high = _safe_float(market_day_range.get("high"))
    session_low = _safe_float(market_day_range.get("low"))
    session_close = _safe_float(market_day_range.get("close"))
    zone_low, zone_high = _resolve_plan_zone(item)

    result = {
        "session_open": session_open,
        "session_high": session_high,
        "session_low": session_low,
        "session_close": session_close,
        "plan_zone_reachable": None,
        "invalidated_before_entry": None,
        "opportunity_status": "UNKNOWN",
    }
    if zone_low is None or zone_high is None or session_high is None or session_low is None:
        return result

    reachable = session_low <= zone_high and session_high >= zone_low
    result["plan_zone_reachable"] = bool(reachable)
    action = str(item.get("plan_action") or "").strip().upper()
    if action in {"ADD", "ACCUMULATE", "PROBE"}:
        max_chase_price = _safe_float(item.get("max_chase_price"))
        invalidated_before_entry = False
        if max_chase_price is not None and session_low is not None and session_low > max_chase_price:
            invalidated_before_entry = True
        result["invalidated_before_entry"] = invalidated_before_entry
        if invalidated_before_entry:
            result["opportunity_status"] = "INVALIDATED"
        elif reachable:
            result["opportunity_status"] = "REACHABLE"
        else:
            result["opportunity_status"] = "UNREACHABLE"
        return result

    result["invalidated_before_entry"] = False
    result["opportunity_status"] = "REACHABLE" if reachable else "UNREACHABLE"
    return result


def build_execution_review(plan: Optional[Mapping], records, *, day=None, market_day_ranges: Optional[Mapping] = None) -> dict:
    target_day = _resolve_day(day)
    plan = dict(plan or {})
    trade_rows = _trade_rows_for_day(records, target_day=target_day)
    market_day_ranges = dict(market_day_ranges or {})

    if not plan or not list(plan.get("items", []) or []):
        return {
            "status": "NO_PLAN",
            "review_day": target_day.isoformat(),
            "decision_signature": str(plan.get("decision_signature") or "").strip() or None,
            "executed_count": 0,
            "missed_count": 0,
            "unplanned_trade_count": len(trade_rows),
            "items": [],
            "unplanned_trades": [
                {
                    "symbol": str(row.get("symbol", "")).strip().upper(),
                    "side": str(row.get("side", "")).strip().upper(),
                    "price": row.get("price"),
                    "shares": row.get("shares"),
                }
                for row in trade_rows
            ],
        }

    results = []
    matched_trade_indexes = set()
    reachable_count = 0
    missed_reachable_count = 0
    unreachable_count = 0
    invalidated_count = 0
    price_failure_count = 0
    for item in list(plan.get("items", []) or []):
        symbol = str(item.get("symbol", "")).strip().upper()
        expected_side = _expected_side(item.get("plan_action"))
        opportunity = _plan_opportunity(item, market_day_ranges.get(symbol))
        plan_zone_reachable = opportunity["plan_zone_reachable"]
        invalidated_before_entry = opportunity["invalidated_before_entry"]
        if plan_zone_reachable is True:
            reachable_count += 1
        elif plan_zone_reachable is False:
            unreachable_count += 1
        if invalidated_before_entry:
            invalidated_count += 1
        matching_rows = []
        for idx, row in enumerate(trade_rows):
            if idx in matched_trade_indexes:
                continue
            if str(row.get("symbol", "")).strip().upper() != symbol:
                continue
            if str(row.get("side", "")).strip().upper() != expected_side:
                continue
            matching_rows.append((idx, row))

        if matching_rows:
            for idx, _row in matching_rows:
                matched_trade_indexes.add(idx)
            prices = [float(row.get("price") or 0.0) for _, row in matching_rows if row.get("price") is not None]
            shares = [float(row.get("shares") or 0.0) for _, row in matching_rows if row.get("shares") is not None]
            results.append(
                {
                    "symbol": symbol,
                    "plan_action": item.get("plan_action"),
                    "expected_side": expected_side,
                    "status": "EXECUTED",
                    "matched_trade_count": len(matching_rows),
                    "avg_execution_price": round(mean(prices), 4) if prices else None,
                    "executed_shares": round(sum(shares), 4) if shares else None,
                    "executed_in_plan_zone": _executed_in_zone(item, prices),
                    "plan_zone_reachable": plan_zone_reachable,
                    "invalidated_before_entry": invalidated_before_entry,
                    "opportunity_status": "EXECUTED",
                    "session_open": opportunity["session_open"],
                    "session_high": opportunity["session_high"],
                    "session_low": opportunity["session_low"],
                    "session_close": opportunity["session_close"],
                }
            )
        else:
            opportunity_status = str(opportunity["opportunity_status"] or "UNKNOWN").strip().upper()
            if opportunity_status == "REACHABLE":
                missed_reachable_count += 1
            if opportunity_status in {"UNREACHABLE", "INVALIDATED"}:
                price_failure_count += 1
            results.append(
                {
                    "symbol": symbol,
                    "plan_action": item.get("plan_action"),
                    "expected_side": expected_side,
                    "status": "MISSED",
                    "matched_trade_count": 0,
                    "avg_execution_price": None,
                    "executed_shares": None,
                    "executed_in_plan_zone": None,
                    "plan_zone_reachable": plan_zone_reachable,
                    "invalidated_before_entry": invalidated_before_entry,
                    "opportunity_status": opportunity_status,
                    "session_open": opportunity["session_open"],
                    "session_high": opportunity["session_high"],
                    "session_low": opportunity["session_low"],
                    "session_close": opportunity["session_close"],
                }
            )

    unplanned_trades = []
    for idx, row in enumerate(trade_rows):
        if idx in matched_trade_indexes:
            continue
        unplanned_trades.append(
            {
                "symbol": str(row.get("symbol", "")).strip().upper(),
                "side": str(row.get("side", "")).strip().upper(),
                "price": row.get("price"),
                "shares": row.get("shares"),
            }
        )

    executed_count = sum(1 for row in results if row["status"] == "EXECUTED")
    missed_count = sum(1 for row in results if row["status"] == "MISSED")
    return {
        "status": "OK",
        "review_day": target_day.isoformat(),
        "plan_date": plan.get("plan_date"),
        "decision_signature": str(plan.get("decision_signature") or "").strip() or None,
        "executed_count": executed_count,
        "missed_count": missed_count,
        "unplanned_trade_count": len(unplanned_trades),
        "reachable_count": reachable_count,
        "missed_reachable_count": missed_reachable_count,
        "unreachable_count": unreachable_count,
        "invalidated_count": invalidated_count,
        "price_failure_count": price_failure_count,
        "items": results,
        "unplanned_trades": unplanned_trades,
    }


def save_post_close_review(review: Mapping, *, path: Optional[str] = None) -> str:
    target = Path(path or DEFAULT_POST_CLOSE_REVIEW_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(review or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def load_post_close_review(*, path: Optional[str] = None):
    target = Path(path or DEFAULT_POST_CLOSE_REVIEW_FILE)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
