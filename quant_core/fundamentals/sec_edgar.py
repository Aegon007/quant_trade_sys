from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_CACHE_DIR = qpaths.RESEARCH_CACHE_DIR / "sec"


def _headers(user_agent: Optional[str] = None) -> dict:
    agent = str(user_agent or os.getenv("SEC_USER_AGENT") or "personal-valuation-research contact@example.com").strip()
    return {"User-Agent": agent, "Host": "www.sec.gov"}


def _read_json(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload


def _fetch_json(url: str, *, user_agent: Optional[str], urlopen, host: Optional[str] = None):
    headers = _headers(user_agent)
    if host:
        headers["Host"] = host
    request = urllib.request.Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_ticker_map(
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    user_agent: Optional[str] = None,
    urlopen=urllib.request.urlopen,
    max_age_seconds: int = 7 * 24 * 3600,
) -> dict[str, str]:
    cache_dir = Path(cache_dir)
    path = cache_dir / "company_tickers.json"
    payload = None
    if path.exists() and time.time() - path.stat().st_mtime <= max_age_seconds:
        payload = _read_json(path)
    if payload is None:
        payload = _fetch_json(TICKER_MAP_URL, user_agent=user_agent, urlopen=urlopen)
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    rows = payload.values() if isinstance(payload, Mapping) else []
    return {
        str(row.get("ticker") or "").strip().upper(): str(int(row.get("cik_str"))).zfill(10)
        for row in rows
        if isinstance(row, Mapping) and row.get("ticker") and row.get("cik_str") is not None
    }


def fetch_company_facts(
    symbol: str,
    *,
    cik: Optional[str] = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    user_agent: Optional[str] = None,
    urlopen=urllib.request.urlopen,
    force: bool = False,
    max_age_seconds: int = 24 * 3600,
) -> dict:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    cache_dir = Path(cache_dir)
    path = cache_dir / "companyfacts" / f"{symbol}.json"
    if path.exists() and not force and time.time() - path.stat().st_mtime <= max_age_seconds:
        payload = _read_json(path)
        if isinstance(payload, dict):
            return payload
    resolved_cik = str(cik or load_ticker_map(cache_dir=cache_dir, user_agent=user_agent, urlopen=urlopen).get(symbol) or "").zfill(10)
    if not resolved_cik.strip("0"):
        raise LookupError(f"SEC CIK not found for {symbol}")
    payload = _fetch_json(
        COMPANY_FACTS_URL.format(cik=resolved_cik),
        user_agent=user_agent,
        urlopen=urlopen,
        host="data.sec.gov",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)
    return payload
