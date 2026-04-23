import json
import os
from datetime import datetime
import yfinance as yf

DATA_FILE = "portfolio_data.json"
CACHE_FILE = "price_cache.json"

DEFAULT_DATA = {
    "holdings": [],
    "watchlist": [],
    "last_updated": None
}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_DATA.copy()

def save_data(data):
    data["last_updated"] = datetime.now().isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def fetch_prices(symbols, use_cache=True, cache_ttl=60):
    """批量获取价格，支持缓存（默认 60 秒 TTL）"""
    prices = {}
    if use_cache:
        cache = _load_cache()
    else:
        cache = {}
    
    now = datetime.now().timestamp()
    symbols_to_fetch = []
    
    for sym in symbols:
        if sym in cache:
            cached_time = cache[sym].get("timestamp", 0)
            if now - cached_time < cache_ttl:
                prices[sym] = cache[sym]["price"]
                continue
        symbols_to_fetch.append(sym)
    
    if symbols_to_fetch:
        try:
            tickers = yf.Tickers(" ".join(symbols_to_fetch))
            for sym in symbols_to_fetch:
                try:
                    ticker = tickers.tickers.get(sym)
                    if ticker:
                        current_price = ticker.fast_info.last_price
                        if current_price is not None:
                            prices[sym] = current_price
                            cache[sym] = {"price": current_price, "timestamp": now}
                except Exception:
                    continue
        except Exception:
            for sym in symbols_to_fetch:
                try:
                    ticker = yf.Ticker(sym)
                    current_price = ticker.fast_info.last_price
                    if current_price is not None:
                        prices[sym] = current_price
                        cache[sym] = {"price": current_price, "timestamp": now}
                except Exception:
                    continue
    
    if use_cache:
        _save_cache(cache)
    return prices

def update_all_prices(data):
    symbols_to_fetch = set()
    for h in data["holdings"]:
        symbols_to_fetch.add(h["symbol"])
    for w in data["watchlist"]:
        symbols_to_fetch.add(w["symbol"])
    if not symbols_to_fetch:
        return data
    prices = fetch_prices(list(symbols_to_fetch))
    for h in data["holdings"]:
        if h["symbol"] in prices:
            h["current_price"] = prices[h["symbol"]]
    for w in data["watchlist"]:
        if w["symbol"] in prices:
            w["last_price"] = prices[w["symbol"]]
    return data

def add_holding(symbol, shares, cost):
    data = load_data()
    data["holdings"].append({
        "symbol": symbol.upper(),
        "shares": shares,
        "cost": cost,
        "current_price": None
    })
    save_data(data)

def update_holding_price(index, price):
    data = load_data()
    data["holdings"][index]["current_price"] = price
    save_data(data)

def delete_holding(index):
    data = load_data()
    data["holdings"].pop(index)
    save_data(data)

def clear_holdings():
    data = load_data()
    data["holdings"] = []
    save_data(data)

def sell_partial_holding(index, sell_shares, sell_price):
    data = load_data()
    holding = data["holdings"][index]
    if sell_shares >= holding["shares"]:
        data["holdings"].pop(index)
    else:
        holding["shares"] -= sell_shares
    save_data(data)
    return holding["symbol"], holding["cost"]

def add_watch(symbol, notes="", target_buy=None):
    data = load_data()
    data["watchlist"].append({
        "symbol": symbol.upper(),
        "notes": notes,
        "target_buy": target_buy,
        "last_price": None
    })
    save_data(data)

def delete_watch(index):
    data = load_data()
    data["watchlist"].pop(index)
    save_data(data)

def clear_watchlist():
    data = load_data()
    data["watchlist"] = []
    save_data(data)

def delete_watch_batch(indices):
    data = load_data()
    for i in sorted(indices, reverse=True):
        data["watchlist"].pop(i)
    save_data(data)