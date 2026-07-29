from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from quant_core import paths as qpaths


DEFAULT_CONFIG_FILE = qpaths.FINANCIALS_CONFIG_FILE
DEFAULT_SNAPSHOT_FILE = qpaths.FINANCIALS_INTELLIGENCE_FILE


DEFAULT_CONFIG = {
    "schema_version": 1,
    "enabled": True,
    "refresh_on_nightly": True,
    "max_symbols": 100,
    "source_order": ["yfinance"],
    "llm_enabled": True,
    "sources": {
        "yfinance": {
            "enabled": True,
            "statement_preference": ["quarterly", "annual"],
        }
    },
    "stress_thresholds": {
        "free_cash_flow_margin_caution": 0.05,
        "free_cash_flow_margin_stress": 0.0,
        "capex_to_operating_cash_flow_caution": 0.45,
        "capex_to_operating_cash_flow_stress": 0.75,
        "debt_to_operating_cash_flow_caution": 3.0,
        "debt_growth_caution": 0.15,
        "revenue_growth_negative": 0.0,
    },
}


ROW_ALIASES = {
    "capital_expenditure": (
        "Capital Expenditure",
        "Capital Expenditures",
        "CapitalExpenditure",
        "Capital Expenditure Reported",
    ),
    "operating_cash_flow": (
        "Operating Cash Flow",
        "Total Cash From Operating Activities",
        "Cash Flow From Continuing Operating Activities",
    ),
    "free_cash_flow": ("Free Cash Flow", "FreeCashFlow"),
    "total_debt": (
        "Total Debt",
        "Long Term Debt And Capital Lease Obligation",
        "Long Term Debt",
        "Short Long Term Debt Total",
    ),
    "revenue": ("Total Revenue", "Operating Revenue"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
}


def _deep_merge(base: Mapping, override: Mapping | None) -> dict:
    merged = json.loads(json.dumps(dict(base or {})))
    for key, value in dict(override or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_financials_config(config: Mapping | None = None) -> dict:
    merged = _deep_merge(DEFAULT_CONFIG, config or {})
    merged["enabled"] = bool(merged.get("enabled", True))
    merged["refresh_on_nightly"] = bool(merged.get("refresh_on_nightly", True))
    merged["llm_enabled"] = bool(merged.get("llm_enabled", True))
    merged["max_symbols"] = max(int(merged.get("max_symbols") or 100), 1)
    merged["source_order"] = [
        str(item or "").strip().lower()
        for item in list(merged.get("source_order", []) or [])
        if str(item or "").strip()
    ] or ["yfinance"]
    return merged


def load_financials_config(*, path: str = DEFAULT_CONFIG_FILE) -> dict:
    target = Path(path)
    if not target.exists():
        config = normalize_financials_config()
        save_financials_config(config, path=path)
        return config
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return normalize_financials_config(payload if isinstance(payload, Mapping) else {})


def save_financials_config(config: Mapping, *, path: str = DEFAULT_CONFIG_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(normalize_financials_config(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(target)


def load_financials_intelligence(*, path: str = DEFAULT_SNAPSHOT_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_financials_intelligence(snapshot: Mapping, *, path: str = DEFAULT_SNAPSHOT_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return str(target)


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _normalize_statement(frame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    result.index = [str(index).strip() for index in result.index]
    return result


def _statement_value(frame: pd.DataFrame, aliases: Sequence[str], *, column_index: int = 0):
    frame = _normalize_statement(frame)
    if frame.empty or len(frame.columns) <= column_index:
        return None
    lower_index = {str(index).strip().lower(): index for index in frame.index}
    for alias in aliases:
        index = lower_index.get(str(alias).strip().lower())
        if index is None:
            continue
        return _finite_float(frame.iloc[frame.index.get_loc(index), column_index])
    return None


def _growth(frame: pd.DataFrame, aliases: Sequence[str]):
    latest = _statement_value(frame, aliases, column_index=0)
    previous = _statement_value(frame, aliases, column_index=1)
    if latest is None or previous in (None, 0):
        return None
    previous_abs = abs(float(previous))
    if previous_abs <= 0:
        return None
    return float(latest - previous) / previous_abs


def _period_label(frame: pd.DataFrame):
    frame = _normalize_statement(frame)
    if frame.empty or len(frame.columns) == 0:
        return None
    try:
        return str(pd.Timestamp(frame.columns[0]).date())
    except Exception:
        return str(frame.columns[0])


def _ratio(numerator, denominator):
    numerator = _finite_float(numerator)
    denominator = _finite_float(denominator)
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _fetch_yfinance_record(symbol: str, *, now: datetime) -> dict:
    if importlib.util.find_spec("yfinance") is None:
        return {
            "symbol": symbol,
            "status": "SOURCE_UNAVAILABLE",
            "source": "yfinance",
            "retrieved_at": now.isoformat(),
            "warnings": ["Python package 'yfinance' is not installed."],
            "metrics": {},
        }
    import yfinance as yf

    warnings = []
    try:
        ticker = yf.Ticker(symbol)
        quarterly_cashflow = _normalize_statement(getattr(ticker, "quarterly_cashflow", pd.DataFrame()))
        annual_cashflow = _normalize_statement(getattr(ticker, "cashflow", pd.DataFrame()))
        quarterly_balance = _normalize_statement(getattr(ticker, "quarterly_balance_sheet", pd.DataFrame()))
        annual_balance = _normalize_statement(getattr(ticker, "balance_sheet", pd.DataFrame()))
        quarterly_income = _normalize_statement(getattr(ticker, "quarterly_financials", pd.DataFrame()))
        annual_income = _normalize_statement(getattr(ticker, "financials", pd.DataFrame()))
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "FETCH_FAILED",
            "source": "yfinance",
            "retrieved_at": now.isoformat(),
            "warnings": [str(exc)],
            "metrics": {},
        }

    cashflow = quarterly_cashflow if not quarterly_cashflow.empty else annual_cashflow
    balance = quarterly_balance if not quarterly_balance.empty else annual_balance
    income = quarterly_income if not quarterly_income.empty else annual_income
    if cashflow.empty and balance.empty and income.empty:
        return {
            "symbol": symbol,
            "status": "NO_STATEMENT_DATA",
            "source": "yfinance",
            "retrieved_at": now.isoformat(),
            "warnings": ["No financial statement data returned; this is common for ETFs and some ADRs."],
            "metrics": {},
        }

    capex = _statement_value(cashflow, ROW_ALIASES["capital_expenditure"])
    operating_cash_flow = _statement_value(cashflow, ROW_ALIASES["operating_cash_flow"])
    free_cash_flow = _statement_value(cashflow, ROW_ALIASES["free_cash_flow"])
    total_debt = _statement_value(balance, ROW_ALIASES["total_debt"])
    revenue = _statement_value(income, ROW_ALIASES["revenue"])
    net_income = _statement_value(income, ROW_ALIASES["net_income"])
    interest_expense = _statement_value(income, ROW_ALIASES["interest_expense"])
    if capex is not None:
        capex = abs(float(capex))
    metrics = {
        "capital_expenditure": capex,
        "operating_cash_flow": operating_cash_flow,
        "free_cash_flow": free_cash_flow,
        "total_debt": total_debt,
        "revenue": revenue,
        "net_income": net_income,
        "interest_expense": interest_expense,
        "free_cash_flow_margin": _ratio(free_cash_flow, revenue),
        "capex_to_operating_cash_flow": _ratio(capex, operating_cash_flow),
        "debt_to_operating_cash_flow": _ratio(total_debt, operating_cash_flow),
        "revenue_growth": _growth(income, ROW_ALIASES["revenue"]),
        "free_cash_flow_growth": _growth(cashflow, ROW_ALIASES["free_cash_flow"]),
        "debt_growth": _growth(balance, ROW_ALIASES["total_debt"]),
        "capex_growth": _growth(cashflow, ROW_ALIASES["capital_expenditure"]),
    }
    if operating_cash_flow is not None and operating_cash_flow <= 0:
        warnings.append("Operating cash flow is non-positive.")
    if free_cash_flow is not None and free_cash_flow <= 0:
        warnings.append("Free cash flow is non-positive.")
    return {
        "symbol": symbol,
        "status": "READY",
        "source": "yfinance",
        "retrieved_at": now.isoformat(),
        "fiscal_period": _period_label(cashflow) or _period_label(income) or _period_label(balance),
        "statement_frequency": "quarterly" if not quarterly_cashflow.empty or not quarterly_income.empty else "annual",
        "warnings": warnings,
        "metrics": {key: value for key, value in metrics.items() if value is not None},
    }


def score_financial_stress(record: Mapping, *, thresholds: Mapping | None = None) -> dict:
    record = dict(record or {})
    thresholds = dict(thresholds or DEFAULT_CONFIG["stress_thresholds"])
    if str(record.get("status") or "").upper() != "READY":
        return {
            "symbol": record.get("symbol"),
            "status": "MISSING",
            "stress_score": 0.0,
            "stress_state": "NO_DATA",
            "drivers": list(record.get("warnings", []) or [])[:3],
            "confidence": 0.1,
        }
    metrics = dict(record.get("metrics", {}) or {})
    score = 0.0
    drivers = []
    fcf_margin = _finite_float(metrics.get("free_cash_flow_margin"))
    if fcf_margin is not None:
        if fcf_margin < float(thresholds.get("free_cash_flow_margin_stress", 0.0)):
            score += 28
            drivers.append(f"free-cash-flow margin stress {fcf_margin:.1%}")
        elif fcf_margin < float(thresholds.get("free_cash_flow_margin_caution", 0.05)):
            score += 14
            drivers.append(f"free-cash-flow margin thin {fcf_margin:.1%}")
    capex_to_ocf = _finite_float(metrics.get("capex_to_operating_cash_flow"))
    if capex_to_ocf is not None:
        if capex_to_ocf > float(thresholds.get("capex_to_operating_cash_flow_stress", 0.75)):
            score += 26
            drivers.append(f"capex consumes operating cash flow {capex_to_ocf:.1%}")
        elif capex_to_ocf > float(thresholds.get("capex_to_operating_cash_flow_caution", 0.45)):
            score += 13
            drivers.append(f"capex intensity elevated {capex_to_ocf:.1%}")
    debt_to_ocf = _finite_float(metrics.get("debt_to_operating_cash_flow"))
    if debt_to_ocf is not None and debt_to_ocf > float(thresholds.get("debt_to_operating_cash_flow_caution", 3.0)):
        score += 12
        drivers.append(f"debt/operating-cash-flow elevated {debt_to_ocf:.1f}x")
    debt_growth = _finite_float(metrics.get("debt_growth"))
    if debt_growth is not None and debt_growth > float(thresholds.get("debt_growth_caution", 0.15)):
        score += 10
        drivers.append(f"debt growth rising {debt_growth:.1%}")
    revenue_growth = _finite_float(metrics.get("revenue_growth"))
    if revenue_growth is not None and revenue_growth < float(thresholds.get("revenue_growth_negative", 0.0)):
        score += 8
        drivers.append(f"revenue growth negative {revenue_growth:.1%}")
    score = round(min(max(score, 0.0), 100.0), 1)
    state = "STRESS" if score >= 55 else "CAUTION" if score >= 25 else "LOW"
    confidence = 0.75 if metrics else 0.2
    return {
        "symbol": record.get("symbol"),
        "status": "READY",
        "stress_score": score,
        "stress_state": state,
        "drivers": drivers[:6],
        "confidence": confidence,
        "metrics": metrics,
        "fiscal_period": record.get("fiscal_period"),
        "source": record.get("source"),
    }


def _structured_summary(rows: Sequence[Mapping], stress_rows: Sequence[Mapping]) -> str:
    ready = [dict(row or {}) for row in rows if str(dict(row or {}).get("status") or "").upper() == "READY"]
    stressed = [dict(row or {}) for row in stress_rows if str(dict(row or {}).get("stress_state") or "").upper() == "STRESS"]
    cautious = [dict(row or {}) for row in stress_rows if str(dict(row or {}).get("stress_state") or "").upper() == "CAUTION"]
    if not ready:
        return "No company financial-statement data is currently available; do not treat missing data as a bearish signal."
    if stressed:
        names = ", ".join(str(row.get("symbol") or "") for row in stressed[:5])
        return f"Financial statement stress is elevated for {names}; review cash-flow, capex intensity, and debt drivers before adding exposure."
    if cautious:
        names = ", ".join(str(row.get("symbol") or "") for row in cautious[:5])
        return f"Financial statement caution is present for {names}; keep position sizing disciplined until cash-flow and capex data improve."
    return "Covered company financial statements do not show elevated capex/cash-flow/debt stress in the latest available data."


def build_financials_intelligence(
    *,
    symbols: Sequence[str],
    config: Mapping | None = None,
    notification_config: Mapping | None = None,
    now: datetime | None = None,
) -> dict:
    from quant_core.llm import explainer

    now = now or datetime.now()
    normalized = normalize_financials_config(config) if config is not None else load_financials_config()
    unique_symbols = []
    for raw_symbol in list(symbols or []):
        symbol = str(raw_symbol or "").strip().upper()
        if symbol and symbol not in unique_symbols:
            unique_symbols.append(symbol)
    unique_symbols = unique_symbols[: int(normalized.get("max_symbols") or 100)]
    if not bool(normalized.get("enabled", True)):
        return {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "status": "DISABLED",
            "summary": {"covered_count": 0, "missing_count": 0, "stress_count": 0, "caution_count": 0},
            "symbols": [],
            "stress": [],
            "executive_summary": "Financial intelligence is disabled.",
            "llm": {"status": "SKIPPED", "reason": "disabled"},
        }

    rows = []
    for symbol in unique_symbols:
        record = None
        for source in list(normalized.get("source_order", []) or []):
            source_cfg = dict(dict(normalized.get("sources", {}) or {}).get(source, {}) or {})
            if not bool(source_cfg.get("enabled", True)):
                continue
            if source == "yfinance":
                record = _fetch_yfinance_record(symbol, now=now)
            if record and str(record.get("status") or "").upper() == "READY":
                break
        rows.append(record or {
            "symbol": symbol,
            "status": "NO_SOURCE",
            "source": None,
            "retrieved_at": now.isoformat(),
            "warnings": ["No enabled financial statement source."],
            "metrics": {},
        })

    thresholds = dict(normalized.get("stress_thresholds", {}) or {})
    stress_rows = [score_financial_stress(row, thresholds=thresholds) for row in rows]
    ready_count = sum(1 for row in rows if str(row.get("status") or "").upper() == "READY")
    stress_count = sum(1 for row in stress_rows if str(row.get("stress_state") or "").upper() == "STRESS")
    caution_count = sum(1 for row in stress_rows if str(row.get("stress_state") or "").upper() == "CAUTION")
    top_stress = sorted(stress_rows, key=lambda row: float(dict(row or {}).get("stress_score") or 0), reverse=True)[:8]
    structured_summary = _structured_summary(rows, stress_rows)
    llm_payload = {"status": "SKIPPED", "reason": "disabled_or_unconfigured"}
    executive_summary = structured_summary
    if bool(normalized.get("llm_enabled", True)) and notification_config:
        try:
            llm_payload = explainer.analyze_financials_intelligence(
                financials_payload={
                    "summary": {
                        "covered_count": ready_count,
                        "missing_count": len(rows) - ready_count,
                        "stress_count": stress_count,
                        "caution_count": caution_count,
                    },
                    "top_stress": top_stress,
                    "symbols": rows,
                },
                notification_config=notification_config,
            )
            text = str(llm_payload.get("text") or "").strip()
            if text:
                executive_summary = text
        except Exception as exc:
            llm_payload = {"status": "FAILED", "error": str(exc)}

    status = "READY" if ready_count else "NO_DATA"
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": status,
        "summary": {
            "symbol_count": len(rows),
            "covered_count": ready_count,
            "missing_count": len(rows) - ready_count,
            "stress_count": stress_count,
            "caution_count": caution_count,
            "top_stress_symbols": [str(row.get("symbol") or "") for row in top_stress if float(row.get("stress_score") or 0) > 0],
            "hard_financial_data": "AVAILABLE" if ready_count == len(rows) and rows else "PARTIAL" if ready_count else "MISSING",
        },
        "executive_summary": executive_summary,
        "structured_summary": structured_summary,
        "symbols": rows,
        "stress": stress_rows,
        "llm": llm_payload,
        "config": {
            "source_order": list(normalized.get("source_order", []) or []),
            "max_symbols": normalized.get("max_symbols"),
            "llm_enabled": normalized.get("llm_enabled"),
        },
    }
