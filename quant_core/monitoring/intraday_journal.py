from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_INTRADAY_EVENT_JOURNAL_FILE = qpaths.INTRADAY_EVENT_JOURNAL_FILE


def _safe_float(value, default=None):
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


def _resolve_day(review_day=None):
    if review_day is None:
        return datetime.now().date()
    if isinstance(review_day, datetime):
        return review_day.date()
    parsed = _parse_datetime(review_day)
    if parsed is not None:
        return parsed.date()
    return datetime.fromisoformat(f"{str(review_day).strip()}T00:00:00").date()


def _normalize_symbol(value) -> str:
    return str(value or "").strip().upper()


def _infer_event_side(event: Mapping) -> Optional[str]:
    payload = dict((event or {}).get("payload", {}) or {})
    explicit = str(payload.get("action_side") or (event or {}).get("action_side") or "").strip().upper()
    if explicit in {"BUY", "SELL"}:
        return explicit
    event_type = str((event or {}).get("event_type") or "").strip().upper()
    if event_type in {"PLAN_BUY_ZONE_TRIGGER"}:
        return "BUY"
    if event_type in {"PLAN_RISK_BREAK", "POSITION_SHARP_DROP", "MARKET_RISK_OFF"}:
        return "SELL"
    return None


def _trigger_price(event: Mapping):
    payload = dict((event or {}).get("payload", {}) or {})
    for key in ("trigger_price", "reference_price", "current_price", "last_price"):
        value = _safe_float(payload.get(key))
        if value is not None and value > 0:
            return value
    return None


def build_intraday_event_entry(
    *,
    event_type: str,
    priority: str,
    now: Optional[datetime] = None,
    symbol: Optional[str] = None,
    trigger_reason: str = "",
    was_alert_sent: bool = False,
    send_context: Optional[str] = None,
    skip_reason: str = "",
    payload: Optional[Mapping] = None,
):
    now = now or datetime.now()
    normalized_payload = dict(payload or {})
    return {
        "timestamp": now.isoformat(),
        "event_type": str(event_type or "").strip().upper(),
        "priority": str(priority or "medium").strip().lower(),
        "symbol": str(symbol or "").strip().upper() or None,
        "trigger_reason": str(trigger_reason or "").strip(),
        "was_alert_sent": bool(was_alert_sent),
        "send_context": str(send_context or "").strip() or None,
        "skip_reason": str(skip_reason or "").strip() or None,
        "payload": normalized_payload,
    }


def append_intraday_event(entry: Mapping, *, journal_path: str = DEFAULT_INTRADAY_EVENT_JOURNAL_FILE) -> str:
    target = Path(journal_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(entry or {}), ensure_ascii=False) + "\n")
    return str(target)


def save_intraday_events(rows, *, journal_path: str = DEFAULT_INTRADAY_EVENT_JOURNAL_FILE) -> str:
    target = Path(journal_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in list(rows or []):
            handle.write(json.dumps(dict(row or {}), ensure_ascii=False) + "\n")
    return str(target)


def load_intraday_events(*, journal_path: str = DEFAULT_INTRADAY_EVENT_JOURNAL_FILE, limit: Optional[int] = None):
    target = Path(journal_path)
    if not target.exists():
        return []
    rows = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = str(line or "").strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except Exception:
                continue
    if limit is not None and limit >= 0:
        rows = rows[-int(limit) :]
    return rows


def summarize_intraday_events(rows, *, review_day=None):
    target_day = _resolve_day(review_day) if review_day is not None else None
    filtered = []
    for row in list(rows or []):
        row_dt = _parse_datetime((row or {}).get("timestamp"))
        if target_day is not None and (row_dt is None or row_dt.date() != target_day):
            continue
        filtered.append(dict(row or {}))
    reviewed = [row for row in filtered if str(row.get("outcome_label") or "").strip()]
    recent_rows = filtered[-8:]
    return {
        "review_day": target_day.isoformat() if target_day is not None else None,
        "total_count": len(filtered),
        "sent_count": sum(1 for row in filtered if bool(row.get("was_alert_sent"))),
        "high_count": sum(1 for row in filtered if str(row.get("priority") or "").strip().lower() == "high"),
        "favorable_count": sum(1 for row in reviewed if str(row.get("outcome_label") or "").strip().upper() == "FAVORABLE"),
        "unfavorable_count": sum(1 for row in reviewed if str(row.get("outcome_label") or "").strip().upper() == "UNFAVORABLE"),
        "neutral_count": sum(1 for row in reviewed if str(row.get("outcome_label") or "").strip().upper() == "NEUTRAL"),
        "recent_rows": recent_rows,
        "latest_timestamp": recent_rows[-1]["timestamp"] if recent_rows else None,
    }


def annotate_intraday_event_outcomes(
    *,
    journal_path: str = DEFAULT_INTRADAY_EVENT_JOURNAL_FILE,
    review_day=None,
    end_of_day_prices: Optional[Mapping] = None,
    transactions=None,
):
    target_day = _resolve_day(review_day)
    rows = load_intraday_events(journal_path=journal_path)
    if not rows:
        return {
            "review_day": target_day.isoformat(),
            "reviewed_count": 0,
            "favorable_count": 0,
            "unfavorable_count": 0,
            "neutral_count": 0,
            "unscored_count": 0,
        }

    end_of_day_prices = {
        _normalize_symbol(symbol): float(price)
        for symbol, price in dict(end_of_day_prices or {}).items()
        if _normalize_symbol(symbol) and _safe_float(price) is not None
    }
    normalized_transactions = []
    for row in list(transactions or []):
        record_dt = _parse_datetime((row or {}).get("date"))
        if record_dt is None or record_dt.date() != target_day:
            continue
        normalized_transactions.append(
            {
                "symbol": _normalize_symbol((row or {}).get("symbol")),
                "side": str((row or {}).get("side") or (row or {}).get("event_type") or "").strip().upper(),
            }
        )

    summary = {
        "review_day": target_day.isoformat(),
        "reviewed_count": 0,
        "favorable_count": 0,
        "unfavorable_count": 0,
        "neutral_count": 0,
        "unscored_count": 0,
    }
    updated = False

    for row in rows:
        row_dt = _parse_datetime((row or {}).get("timestamp"))
        if row_dt is None or row_dt.date() != target_day:
            continue
        symbol = _normalize_symbol((row or {}).get("symbol"))
        trigger_price = _trigger_price(row)
        end_of_day_price = end_of_day_prices.get(symbol) if symbol else None
        action_side = _infer_event_side(row)
        matched_trades = [
            tx_row for tx_row in normalized_transactions
            if tx_row.get("symbol") == symbol and (
                not action_side or tx_row.get("side") == action_side
            )
        ]

        outcome_label = "UNSCORED"
        same_day_close_return_pct = None
        if trigger_price is not None and end_of_day_price is not None and trigger_price > 0:
            same_day_close_return_pct = end_of_day_price / trigger_price - 1.0
            if action_side == "BUY":
                if same_day_close_return_pct > 0.002:
                    outcome_label = "FAVORABLE"
                elif same_day_close_return_pct < -0.002:
                    outcome_label = "UNFAVORABLE"
                else:
                    outcome_label = "NEUTRAL"
            elif action_side == "SELL":
                if same_day_close_return_pct < -0.002:
                    outcome_label = "FAVORABLE"
                elif same_day_close_return_pct > 0.002:
                    outcome_label = "UNFAVORABLE"
                else:
                    outcome_label = "NEUTRAL"
            else:
                outcome_label = "NEUTRAL"

        row["review_day"] = target_day.isoformat()
        row["outcome_reviewed_at"] = datetime.now().isoformat()
        row["matched_trade_count"] = len(matched_trades)
        row["matched_trade_side"] = action_side
        row["same_day_close_price"] = end_of_day_price
        row["same_day_close_return_pct"] = same_day_close_return_pct
        row["outcome_label"] = outcome_label
        summary["reviewed_count"] += 1
        key = f"{outcome_label.lower()}_count"
        if key in summary:
            summary[key] += 1
        else:
            summary["unscored_count"] += 1
        updated = True

    if updated:
        save_intraday_events(rows, journal_path=journal_path)
    return summary
