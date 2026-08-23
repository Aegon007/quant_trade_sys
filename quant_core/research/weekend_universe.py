from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_WEEKEND_UNIVERSE_FILE = qpaths.WEEKEND_RESEARCH_UNIVERSE_FILE
DEFAULT_MAX_SYMBOLS = 3000


def _symbol(value) -> str:
    return str(value or "").strip().upper()


def _read_json(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_weekend_universe_config(*, path: str = DEFAULT_WEEKEND_UNIVERSE_FILE) -> dict:
    payload = _read_json(path)
    if not payload:
        return {"manual_include": [], "manual_exclude": [], "max_symbols": DEFAULT_MAX_SYMBOLS}
    return {
        "manual_include": [_symbol(item) for item in list(payload.get("manual_include", []) or []) if _symbol(item)],
        "manual_exclude": {_symbol(item) for item in list(payload.get("manual_exclude", []) or []) if _symbol(item)},
        "max_symbols": int(payload.get("max_symbols") or DEFAULT_MAX_SYMBOLS),
        "description": str(payload.get("description") or ""),
    }


def _add_symbol(
    symbols: list[str],
    sources: dict[str, set[str]],
    symbol: str,
    source: str,
    *,
    excluded: set[str],
):
    normalized = _symbol(symbol)
    if not normalized or normalized in excluded:
        return
    if normalized not in sources:
        symbols.append(normalized)
        sources[normalized] = set()
    sources[normalized].add(str(source or "unknown"))


def build_weekend_research_universe(
    *,
    data: Optional[Mapping] = None,
    core_rotation_snapshot: Optional[Mapping] = None,
    satellite_snapshot: Optional[Mapping] = None,
    config: Optional[Mapping] = None,
    satellite_universe: Optional[Mapping] = None,
) -> dict:
    data = dict(data or {})
    core_rotation_snapshot = dict(core_rotation_snapshot or {})
    satellite_snapshot = dict(satellite_snapshot or {})
    config = dict(config or load_weekend_universe_config())
    satellite_universe = dict(satellite_universe or {})
    excluded = set(config.get("manual_exclude", set()) or set())
    max_symbols = max(1, int(config.get("max_symbols") or DEFAULT_MAX_SYMBOLS))
    symbols: list[str] = []
    sources: dict[str, set[str]] = {}

    for row in list(data.get("holdings", []) or []):
        _add_symbol(symbols, sources, dict(row or {}).get("symbol"), "holding", excluded=excluded)
    for row in list(data.get("watchlist", []) or []):
        _add_symbol(symbols, sources, dict(row or {}).get("symbol"), "watchlist", excluded=excluded)
    for row in list(core_rotation_snapshot.get("symbols", []) or []):
        _add_symbol(symbols, sources, dict(row or {}).get("symbol"), "core_etf_rotation", excluded=excluded)
    for row in list(satellite_snapshot.get("candidate_pool", []) or []):
        _add_symbol(symbols, sources, dict(row or {}).get("symbol"), "satellite_candidate_pool", excluded=excluded)
    for symbol in list(satellite_universe.get("manual_include", []) or []):
        _add_symbol(symbols, sources, symbol, "satellite_universe", excluded=excluded)
    for symbol in list(config.get("manual_include", []) or []):
        _add_symbol(symbols, sources, symbol, "weekend_universe", excluded=excluded)

    selected = symbols[:max_symbols]
    source_rows = [
        {"symbol": symbol, "sources": sorted(sources.get(symbol, set()))}
        for symbol in selected
    ]
    return {
        "schema_version": 1,
        "symbol_count": len(selected),
        "available_symbol_count": len(symbols),
        "max_symbols": max_symbols,
        "excluded_symbol_count": len(excluded),
        "symbols": selected,
        "symbol_sources": source_rows,
        "source_counts": _source_counts(source_rows),
        "truncated": len(symbols) > max_symbols,
        "message": (
            "周末研究宇宙已合并持仓、关注、核心 ETF、卫星池和周末专用 universe；"
            "扩大到几千/上万标的时，只需要扩展配置文件。"
        ),
    }


def _source_counts(rows: Iterable[Mapping]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in list(rows or []):
        for source in list(dict(row or {}).get("sources", []) or []):
            counts[str(source)] = counts.get(str(source), 0) + 1
    return counts
