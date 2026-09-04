from __future__ import annotations

import io
import json
import time
import urllib.request
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd

from quant_core import paths as qpaths
from quant_core.data.watchlist import load_watchlist


INDEX_URLS = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    "nasdaq100": ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
}
SECTOR_ETFS = {
    "communication services": "XLC",
    "consumer discretionary": "XLY",
    "consumer staples": "XLP",
    "energy": "XLE",
    "financials": "XLF",
    "health care": "XLV",
    "industrials": "XLI",
    "information technology": "XLK",
    "materials": "XLB",
    "real estate": "XLRE",
    "utilities": "XLU",
}
DEFAULT_CONFIG = {
    "source_indexes": ["sp500", "nasdaq100"],
    "manual_include": [],
    "manual_exclude": [],
    "etfs": [],
    "max_universe_size": 700,
    "max_deep_analysis": 30,
    "minimum_dislocation_score": 35,
}


def _read_json(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_universe_config(path: str = qpaths.RESEARCH_UNIVERSE_FILE) -> dict:
    example = _read_json(qpaths.RESEARCH_UNIVERSE_EXAMPLE_FILE) if Path(path) == Path(qpaths.RESEARCH_UNIVERSE_FILE) else {}
    return {**DEFAULT_CONFIG, **example, **_read_json(path)}


def save_universe_config(config: Mapping, path: str = qpaths.RESEARCH_UNIVERSE_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({**DEFAULT_CONFIG, **dict(config or {})}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)


def _index_constituents(name: str, *, cache_dir: Optional[Path] = None) -> list[dict | str]:
    if name not in INDEX_URLS:
        return []
    cache_dir = Path(cache_dir or qpaths.RESEARCH_CACHE_DIR / "universe")
    path = cache_dir / f"{name}.json"
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        payload = _read_json(str(path))
        if list(payload.get("records", []) or []):
            return [dict(value) for value in list(payload["records"]) if isinstance(value, Mapping)]
        return [str(value).upper() for value in list(payload.get("symbols", []) or [])]
    url, column = INDEX_URLS[name]
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 valuation-research"})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    tables = pd.read_html(io.StringIO(html))
    table = next((frame for frame in tables if column in frame.columns), None)
    if table is None:
        return []
    sector_column = next((name for name in ("GICS Sector", "Sector") if name in table.columns), None)
    industry_column = next((name for name in ("GICS Sub-Industry", "Industry", "ICB Industry") if name in table.columns), None)
    records = []
    for _, source_row in table.iterrows():
        symbol = str(source_row.get(column) or "").replace(".", "-").strip().upper()
        if not symbol or symbol == "NAN":
            continue
        sector = str(source_row.get(sector_column) or "").strip() if sector_column else ""
        industry = str(source_row.get(industry_column) or "").strip() if industry_column else ""
        sector_etf = "SMH" if "semiconductor" in industry.lower() else SECTOR_ETFS.get(sector.lower(), "SPY")
        records.append({"symbol": symbol, "sector": sector, "industry": industry, "sector_etf": sector_etf})
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return records


def _record(value, *, asset_type="equity", source="manual") -> dict:
    if isinstance(value, Mapping):
        row = dict(value)
        symbol = str(row.get("symbol") or "").strip().upper()
        return {**row, "symbol": symbol, "asset_type": str(row.get("asset_type") or asset_type).lower(), "source": row.get("source") or source}
    return {"symbol": str(value or "").strip().upper(), "asset_type": asset_type, "source": source}


def build_research_universe(config: Optional[Mapping] = None, *, index_loader=None, watchlist_loader=None) -> list[dict]:
    config = {**DEFAULT_CONFIG, **dict(config or load_universe_config())}
    excluded = {str(value).strip().upper() for value in list(config.get("manual_exclude", []) or [])}
    records = {}
    for value in list(config.get("manual_include", []) or []):
        row = _record(value)
        if row["symbol"]:
            records[row["symbol"]] = row
    for symbol in (watchlist_loader or load_watchlist)():
        records.setdefault(symbol, {"symbol": symbol, "asset_type": "equity", "source": "watchlist", "always_analyze": True})
    loader = index_loader or _index_constituents
    for source in list(config.get("source_indexes", []) or []):
        try:
            symbols = loader(str(source))
        except Exception:
            symbols = []
        for value in symbols:
            row = _record(value, source=str(source))
            records.setdefault(row["symbol"], row)
    for value in list(config.get("etfs", []) or []):
        row = _record(value, asset_type="etf", source="etf_config")
        if row["symbol"]:
            records[row["symbol"]] = row
    selected = [row for symbol, row in records.items() if symbol not in excluded]
    return selected[: max(int(config.get("max_universe_size") or 700), 1)]
