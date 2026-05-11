import json
import os
from datetime import datetime
from share_utils import validate_share_quantity
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


def normalize_transaction_record(record):
    record = dict(record or {})
    symbol = str(record.get("symbol", "")).strip().upper()
    event_type = str(record.get("event_type", "")).strip().upper()
    side = str(record.get("side", "")).strip().upper()
    record_type = str(record.get("record_type", "TRADE")).strip().upper()
    if not event_type:
        event_type = "SELL" if record_type == "TRADE" else "UNKNOWN"
    if not side:
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

def _append_record(record):
    trans = load_transactions()
    trans.append(record)
    save_transactions(trans)


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
