import json
import os
from datetime import datetime

TRANS_FILE = "transactions.json"

def load_transactions():
    if os.path.exists(TRANS_FILE):
        with open(TRANS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_transactions(transactions):
    with open(TRANS_FILE, "w", encoding="utf-8") as f:
        json.dump(transactions, f, indent=2, ensure_ascii=False)

def add_transaction(symbol, sell_price, shares, cost_basis):
    """记录卖出交易"""
    trans = load_transactions()
    proceeds = sell_price * shares
    cost = cost_basis * shares
    pl = proceeds - cost
    pl_pct = (pl / cost * 100) if cost != 0 else 0

    trans.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "symbol": symbol.upper(),
        "shares": shares,
        "sell_price": sell_price,
        "cost_basis": cost_basis,
        "proceeds": proceeds,
        "pl": pl,
        "pl_pct": pl_pct
    })
    save_transactions(trans)