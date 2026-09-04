from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from quant_core import paths as qpaths


def load_watchlist(path: str = qpaths.WATCHLIST_FILE) -> list[str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        try:
            payload = json.loads(Path(qpaths.WATCHLIST_EXAMPLE_FILE).read_text(encoding="utf-8")) if Path(path) == Path(qpaths.WATCHLIST_FILE) else []
        except Exception:
            return []
    values = payload.get("symbols", []) if isinstance(payload, dict) else payload
    return list(dict.fromkeys(str(value or "").strip().upper() for value in list(values or []) if str(value or "").strip()))


def save_watchlist(symbols: Iterable[str], path: str = qpaths.WATCHLIST_FILE) -> list[str]:
    normalized = list(dict.fromkeys(str(value or "").strip().upper() for value in symbols if str(value or "").strip()))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"symbols": normalized}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def add_to_watchlist(symbol: str, path: str = qpaths.WATCHLIST_FILE) -> list[str]:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    return save_watchlist([*load_watchlist(path), symbol], path)


def remove_from_watchlist(symbol: str, path: str = qpaths.WATCHLIST_FILE) -> list[str]:
    symbol = str(symbol or "").strip().upper()
    return save_watchlist([value for value in load_watchlist(path) if value != symbol], path)
