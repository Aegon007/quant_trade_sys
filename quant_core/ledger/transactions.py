import json
import os
import hashlib
from datetime import datetime
from quant_core.common.share_utils import validate_share_quantity
from quant_core import paths as qpaths

qpaths.bootstrap_storage_paths()

TRANS_FILE = qpaths.TRANSACTIONS_FILE

def load_transactions():
    if os.path.exists(TRANS_FILE):
        with open(TRANS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_transactions(transactions):
    with open(TRANS_FILE, "w", encoding="utf-8") as f:
        json.dump(transactions, f, indent=2, ensure_ascii=False)


def _safe_backup_label(label):
    text = str(label or "manual-reset").strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in text)
    return cleaned.strip("-") or "manual-reset"


def backup_transactions(*, label="manual-reset"):
    rows = list(load_transactions() or [])
    if not rows:
        return ""
    parent = os.path.dirname(TRANS_FILE) or "."
    os.makedirs(parent, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(parent, f"transactions_backup_{_safe_backup_label(label)}_{timestamp}.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    return backup_path


def clear_transactions(*, backup=True, label="manual-reset"):
    old_count = len(load_transactions() or [])
    backup_path = backup_transactions(label=label) if backup else ""
    save_transactions([])
    return {
        "cleared_count": old_count,
        "backup_path": backup_path,
    }


def normalize_transaction_record(record):
    record = dict(record or {})
    symbol = str(record.get("symbol", "")).strip().upper()
    event_type = str(record.get("event_type", "")).strip().upper()
    side = str(record.get("side", "")).strip().upper()
    record_type = str(record.get("record_type", "TRADE")).strip().upper()
    if not event_type:
        event_type = "SELL" if record_type == "TRADE" else "UNKNOWN"
    if not side:
        if record_type == "CASH_EVENT":
            side = ""
        else:
            side = "SELL" if event_type in {"SELL", "SELL_ALL", "MOVE_TO_WATCH"} else "BUY"
    price = record.get("price")
    if price is None:
        price = record.get("sell_price")
    notes = str(record.get("notes", "") or "")

    return {
        "record_type": record_type,
        "event_type": event_type,
        "side": side,
        "date": str(record.get("date", "") or ""),
        "symbol": symbol,
        "shares": record.get("shares"),
        "price": price,
        "sell_price": record.get("sell_price"),
        "cost_basis": record.get("cost_basis"),
        "proceeds": record.get("proceeds"),
        "pl": record.get("pl"),
        "pl_pct": record.get("pl_pct"),
        "notes": notes,
        "source": str(record.get("source", "") or ""),
        "import_key": str(record.get("import_key", "") or ""),
        "source_file": str(record.get("source_file", "") or ""),
    }


def normalize_transactions(records):
    return [normalize_transaction_record(record) for record in (records or [])]


def filter_transactions(records, *, event_type=None, side=None, symbol=None):
    normalized = normalize_transactions(records)
    event_type = str(event_type or "").strip().upper()
    side = str(side or "").strip().upper()
    symbol = str(symbol or "").strip().upper()

    filtered = []
    for record in normalized:
        if event_type and record.get("event_type") != event_type:
            continue
        if side and record.get("side") != side:
            continue
        if symbol and record.get("symbol") != symbol:
            continue
        filtered.append(record)
    return filtered


def _parse_record_datetime(value):
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


def summarize_daily_activity(records, *, day=None):
    normalized = normalize_transactions(records)
    if day is None:
        target_day = datetime.now().date()
    elif isinstance(day, datetime):
        target_day = day.date()
    else:
        parsed = _parse_record_datetime(day)
        if parsed is None:
            parsed = datetime.fromisoformat(f"{str(day).strip()}T00:00:00")
        target_day = parsed.date()

    todays = []
    for record in normalized:
        record_dt = _parse_record_datetime(record.get("date"))
        if record_dt is None or record_dt.date() != target_day:
            continue
        todays.append(record)

    trade_rows = [record for record in todays if str(record.get("record_type", "")).upper() == "TRADE"]
    buy_rows = [record for record in trade_rows if str(record.get("side", "")).upper() == "BUY"]
    sell_rows = [record for record in trade_rows if str(record.get("side", "")).upper() == "SELL"]
    event_rows = [record for record in todays if str(record.get("record_type", "")).upper() == "PORTFOLIO_EVENT"]

    realized_pl = 0.0
    winning_trades = []
    losing_trades = []
    symbols = []
    for record in todays:
        symbol = str(record.get("symbol", "")).strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    for record in sell_rows:
        try:
            pl_value = float(record.get("pl")) if record.get("pl") is not None else 0.0
        except (TypeError, ValueError):
            pl_value = 0.0
        realized_pl += pl_value
        summary = {
            "symbol": str(record.get("symbol", "")).strip().upper(),
            "pl": pl_value,
            "shares": record.get("shares"),
        }
        if pl_value > 0:
            winning_trades.append(summary)
        elif pl_value < 0:
            losing_trades.append(summary)

    return {
        "day": target_day.isoformat(),
        "transaction_count": len(todays),
        "trade_count": len(trade_rows),
        "buy_count": len(buy_rows),
        "sell_count": len(sell_rows),
        "portfolio_event_count": len(event_rows),
        "realized_pl": round(realized_pl, 4),
        "symbols": symbols,
        "largest_win": max(winning_trades, key=lambda item: float(item.get("pl") or 0.0), default=None),
        "largest_loss": min(losing_trades, key=lambda item: float(item.get("pl") or 0.0), default=None),
    }

def _append_record(record):
    trans = load_transactions()
    trans.append(record)
    save_transactions(trans)


def _canonical_number_text(value):
    if value is None:
        return ""
    try:
        return f"{float(value):.8f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def transaction_identity_key(record):
    normalized = normalize_transaction_record(record)
    import_key = str(normalized.get("import_key", "") or "").strip()
    if import_key:
        return f"import:{import_key}"

    record_dt = _parse_record_datetime(normalized.get("date"))
    date_key = record_dt.isoformat(timespec="seconds") if record_dt is not None else str(normalized.get("date", "") or "").strip()
    payload = {
        "record_type": str(normalized.get("record_type", "") or "").strip().upper(),
        "event_type": str(normalized.get("event_type", "") or "").strip().upper(),
        "side": str(normalized.get("side", "") or "").strip().upper(),
        "date": date_key,
        "symbol": str(normalized.get("symbol", "") or "").strip().upper(),
        "shares": _canonical_number_text(normalized.get("shares")),
        "price": _canonical_number_text(normalized.get("price")),
        "proceeds": _canonical_number_text(normalized.get("proceeds")),
        "notes": str(normalized.get("notes", "") or "").strip(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def append_imported_trade_records(records):
    existing_rows = list(load_transactions() or [])
    existing_keys = {transaction_identity_key(row) for row in existing_rows}
    imported_rows = []
    duplicate_count = 0

    for record in list(records or []):
        key = transaction_identity_key(record)
        if key in existing_keys:
            duplicate_count += 1
            continue
        existing_rows.append(record)
        imported_rows.append(record)
        existing_keys.add(key)

    if imported_rows:
        save_transactions(existing_rows)

    return {
        "imported_count": len(imported_rows),
        "duplicate_count": duplicate_count,
        "records": imported_rows,
    }


def import_robinhood_activity_csv(content, *, filename=""):
    from quant_core.ledger import robinhood_csv as rhcsv

    parsed = rhcsv.parse_robinhood_activity_csv(content, filename=filename)
    appended = append_imported_trade_records(parsed.get("records", []))
    return {
        **parsed,
        **appended,
    }


def replace_with_robinhood_activity_csv(content, *, filename="", backup=True):
    from quant_core.ledger import robinhood_csv as rhcsv

    parsed = rhcsv.parse_robinhood_activity_csv(content, filename=filename)
    parsed_records = list(parsed.get("records", []) or [])
    if not parsed_records:
        raise ValueError("CSV did not contain supported Robinhood activity records; existing transactions were not cleared.")

    backup_path = backup_transactions(label="pre-robinhood-rebuild") if backup else ""
    save_transactions([])
    appended = append_imported_trade_records(parsed_records)
    return {
        **parsed,
        **appended,
        "mode": "replace",
        "cleared_existing": True,
        "backup_path": backup_path,
    }


def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def add_transaction(symbol, sell_price, shares, cost_basis, *, event_type="SELL"):
    """记录卖出交易"""
    normalized_shares = validate_share_quantity(shares, field_name="shares")
    proceeds = sell_price * normalized_shares
    cost = cost_basis * normalized_shares
    pl = proceeds - cost
    pl_pct = (pl / cost * 100) if cost != 0 else 0

    _append_record({
        "record_type": "TRADE",
        "event_type": str(event_type or "SELL").strip().upper(),
        "side": "SELL",
        "date": _now_text(),
        "symbol": symbol.upper(),
        "shares": normalized_shares,
        "price": sell_price,
        "sell_price": sell_price,
        "cost_basis": cost_basis,
        "proceeds": proceeds,
        "pl": pl,
        "pl_pct": pl_pct,
        "notes": "",
    })


def add_buy_transaction(symbol, buy_price, shares, *, event_type="BUY", notes=""):
    """记录买入交易。"""
    normalized_shares = validate_share_quantity(shares, field_name="shares")
    _append_record(
        {
            "record_type": "TRADE",
            "event_type": str(event_type or "BUY").strip().upper(),
            "side": "BUY",
            "date": _now_text(),
            "symbol": symbol.upper(),
            "shares": normalized_shares,
            "price": float(buy_price),
            "sell_price": None,
            "cost_basis": float(buy_price),
            "proceeds": None,
            "pl": None,
            "pl_pct": None,
            "notes": str(notes or ""),
        }
    )


def add_portfolio_event(event_type, symbol, shares, *, price=None, side="", notes=""):
    """记录组合层动作事件（例如转到关注/转到持仓）"""
    normalized_shares = validate_share_quantity(shares, field_name="shares")
    resolved_price = None if price is None else float(price)
    side_text = str(side or "").strip().upper()
    _append_record(
        {
            "record_type": "PORTFOLIO_EVENT",
            "event_type": str(event_type or "").strip().upper(),
            "side": side_text,
            "date": _now_text(),
            "symbol": symbol.upper(),
            "shares": normalized_shares,
            "price": resolved_price,
            "sell_price": None,
            "cost_basis": None,
            "proceeds": None,
            "pl": None,
            "pl_pct": None,
            "notes": str(notes or ""),
        }
    )
