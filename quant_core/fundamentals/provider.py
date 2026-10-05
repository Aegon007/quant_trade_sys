from __future__ import annotations

import math
import importlib.util
from datetime import datetime
from typing import Mapping, Optional

from quant_core.fundamentals.metrics import normalize_sec_company_facts
from quant_core.fundamentals.sec_edgar import DEFAULT_CACHE_DIR, fetch_company_facts, fetch_filing_context


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _etf_market_info(symbol: str) -> dict:
    if importlib.util.find_spec("yfinance") is None:
        return {}
    try:
        import yfinance as yf

        return dict(getattr(yf.Ticker(symbol), "info", {}) or {})
    except Exception:
        return {}


def _normalized_yield(value):
    number = _finite(value)
    if number is None:
        return None
    return number / 100 if number > 1 else number


def _etf_profile(symbol: str, *, metadata: Optional[Mapping] = None, market_info: Optional[Mapping] = None) -> dict:
    metadata = dict(metadata or {})
    info = _etf_market_info(symbol) if market_info is None else dict(market_info or {})
    trailing_pe = _finite(info.get("trailingPE"))
    current_earnings_yield = 1.0 / trailing_pe if trailing_pe and trailing_pe > 0 else _finite(metadata.get("earnings_yield"))
    historical_earnings_yield = _finite(metadata.get("historical_earnings_yield"))
    if historical_earnings_yield is None:
        historical_earnings_yield = current_earnings_yield
    distribution_yield = _normalized_yield(info.get("yield") if info.get("yield") is not None else info.get("dividendYield"))
    if distribution_yield is None:
        distribution_yield = _normalized_yield(metadata.get("distribution_yield"))
    is_commodity = "commodity" in str(metadata.get("sector") or metadata.get("role") or "").lower()
    ready = is_commodity or (current_earnings_yield is not None and historical_earnings_yield is not None)
    return {
        "symbol": symbol,
        "company_name": metadata.get("name") or symbol,
        "asset_type": "etf",
        "sector": metadata.get("sector") or metadata.get("role") or "broad_market",
        "status": "READY" if ready else "PARTIAL",
        "source": "yfinance_etf_metadata" if info else "configured_etf_metadata",
        "retrieved_at": datetime.now().isoformat(),
        "earnings_yield": current_earnings_yield,
        "historical_earnings_yield": historical_earnings_yield,
        "distribution_yield": distribution_yield,
        "quality_score": _finite(metadata.get("quality_score"), 70),
        "damage_score": 5.0,
        "distress_probability": 0.01,
        "fiscal_period": None,
        "evidence": [{"source": "Yahoo ETF market metadata" if info else "configured ETF valuation metadata"}],
    }


def _statement_value(frame, labels, *, trailing=False):
    if frame is None or getattr(frame, "empty", True):
        return None
    for label in labels:
        if label not in frame.index:
            continue
        values = frame.loc[label]
        try:
            numeric = [float(value) for value in list(values) if _finite(value) is not None]
        except Exception:
            continue
        if numeric:
            return sum(numeric[:4]) if trailing else numeric[0]
    return None


def _load_yfinance_profile(symbol: str, *, metadata: Optional[Mapping] = None, now: Optional[datetime] = None) -> dict:
    if importlib.util.find_spec("yfinance") is None:
        raise RuntimeError("yfinance is not installed")
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = dict(getattr(ticker, "info", {}) or {})
    income = getattr(ticker, "quarterly_income_stmt", None)
    cashflow = getattr(ticker, "quarterly_cashflow", None)
    balance = getattr(ticker, "quarterly_balance_sheet", None)
    revenue = _statement_value(income, ("Total Revenue", "Operating Revenue"), trailing=True)
    operating_income = _statement_value(income, ("Operating Income",), trailing=True)
    net_income = _statement_value(income, ("Net Income", "Net Income Common Stockholders"), trailing=True)
    operating_cash = _statement_value(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"), trailing=True)
    capex = _statement_value(cashflow, ("Capital Expenditure", "Capital Expenditures"), trailing=True)
    if capex is not None:
        capex = abs(capex)
    free_cash_flow = operating_cash - capex if operating_cash is not None and capex is not None else _finite(info.get("freeCashflow"))
    cash = _statement_value(balance, ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"))
    debt = _statement_value(balance, ("Total Debt",))
    equity = _statement_value(balance, ("Stockholders Equity", "Total Equity Gross Minority Interest"))
    shares = _finite(info.get("sharesOutstanding"))
    revenue_growth = _finite(info.get("revenueGrowth"))
    operating_margin = _finite(info.get("operatingMargins"))
    quality = 45.0 + (16 if (free_cash_flow or 0) > 0 else 0) + (10 if (revenue_growth or 0) > 0.05 else 0) + (10 if (operating_margin or 0) > 0.15 else 0)
    damage = (25 if free_cash_flow is not None and free_cash_flow < 0 else 5) + (20 if revenue_growth is not None and revenue_growth < -0.05 else 0)
    return {
        "symbol": symbol,
        "company_name": info.get("longName") or symbol,
        "asset_type": "equity",
        "sector": dict(metadata or {}).get("sector") or info.get("sector") or "",
        "status": "PARTIAL",
        "source": "yfinance_fallback",
        "retrieved_at": (now or datetime.now()).isoformat(),
        "fiscal_period": "latest_trailing_quarters",
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "operating_cash_flow": operating_cash,
        "capital_expenditure": capex,
        "free_cash_flow": free_cash_flow,
        "cash": cash,
        "total_debt": debt,
        "equity": equity,
        "shares_outstanding": shares,
        "normalized_earnings": net_income,
        "revenue_growth": revenue_growth,
        "operating_margin": operating_margin,
        "quality_score": min(quality, 85.0),
        "damage_score": min(damage, 100.0),
        "distress_probability": min(0.04 + max(damage - 20, 0) / 125, 0.8),
        "evidence": [{"source": "yfinance quarterly statements", "warning": "fallback data is not point-in-time SEC XBRL"}],
    }


def load_financial_profile(
    symbol: str,
    *,
    asset_type: str = "equity",
    metadata: Optional[Mapping] = None,
    force: bool = False,
    now: Optional[datetime] = None,
    user_agent: Optional[str] = None,
    include_filings: bool = True,
    filing_cache_dir=DEFAULT_CACHE_DIR,
) -> dict:
    symbol = str(symbol or "").strip().upper()
    metadata = dict(metadata or {})
    if str(asset_type or "equity").lower() == "etf":
        return _etf_profile(symbol, metadata=metadata)
    try:
        payload = fetch_company_facts(symbol, cik=metadata.get("cik"), force=force, user_agent=user_agent)
        profile = normalize_sec_company_facts(payload, symbol=symbol, as_of=now)
        profile["sector"] = metadata.get("sector") or profile.get("sector") or ""
        if include_filings:
            try:
                filing_context = fetch_filing_context(
                    symbol,
                    cik=metadata.get("cik") or payload.get("cik"),
                    cache_dir=filing_cache_dir,
                    user_agent=user_agent,
                    force=force,
                    as_of=now,
                )
            except Exception as exc:
                filing_context = {
                    "status": "UNAVAILABLE",
                    "source": "sec_edgar_filing",
                    "filings": [],
                    "errors": [{"error": f"{type(exc).__name__}: {exc}"}],
                }
            profile["filing_context"] = filing_context
            latest = next(iter(filing_context.get("filings", []) or []), {})
            profile["latest_filing_form"] = latest.get("form")
            profile["latest_filing_date"] = latest.get("filing_date")
            if latest:
                profile.setdefault("evidence", []).append(
                    {
                        "source": "SEC EDGAR full filing",
                        "form": latest.get("form"),
                        "filed": latest.get("filing_date"),
                        "url": latest.get("url"),
                    }
                )
        return profile
    except Exception as exc:
        profile = _load_yfinance_profile(symbol, metadata=metadata, now=now)
        profile["sec_error"] = f"{type(exc).__name__}: {exc}"
        return profile
