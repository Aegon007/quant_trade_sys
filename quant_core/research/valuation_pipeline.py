from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core.opportunities.dislocation import measure_dislocation
from quant_core.opportunities.scoring import score_opportunity
from quant_core.valuation.engine import value_security
from quant_core.valuation.router import normalize_valuation_route


def _write_json(path: str, payload: Mapping) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(target)
    return str(target)


def _last_price(history):
    if history is None or getattr(history, "empty", True) or "Close" not in history:
        return None
    try:
        return float(history["Close"].dropna().iloc[-1])
    except (IndexError, TypeError, ValueError):
        return None


def run_valuation_research(
    *,
    universe,
    history_loader,
    financial_loader,
    route_loader,
    event_loader,
    market_risk: Optional[Mapping],
    snapshot_path: str,
    valuation_path: str,
    recommendation_path: str,
    now: Optional[datetime] = None,
    progress=None,
    policy: Optional[Mapping] = None,
) -> dict:
    now = now or datetime.now()
    rows = [dict(row or {}) for row in list(universe or []) if str(dict(row or {}).get("symbol") or "").strip()]
    policy = dict(policy or {})
    history_period = str(policy.get("history_period") or "2y")
    max_deep_analysis = max(int(policy.get("max_deep_analysis") or len(rows) or 1), 1)
    minimum_dislocation = float(policy.get("minimum_dislocation_score") or 0)
    require_llm_route = bool(policy.get("require_llm_route_for_action", False))
    market_history = history_loader("SPY", period=history_period)
    opportunities = []
    valuations = []
    errors = []
    sector_cache = {"SPY": market_history}
    history_cache = {"SPY": market_history}
    scanned = []
    symbols_to_load = {str(item.get("symbol") or "").strip().upper() for item in rows}
    symbols_to_load.update(str(item.get("sector_etf") or "SPY").strip().upper() for item in rows)
    symbols_to_load.discard("SPY")
    worker_count = max(1, min(int(policy.get("scan_workers") or 8), 16))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(history_loader, symbol, period=history_period): symbol for symbol in symbols_to_load}
        for completed, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                history_cache[symbol] = future.result()
            except Exception as exc:
                history_cache[symbol] = None
                errors.append({"symbol": symbol, "stage": "history", "error": f"{type(exc).__name__}: {exc}"})
            if progress and completed % max(len(futures) // 20, 1) == 0:
                progress("load_histories", int(5 + completed / max(len(futures), 1) * 25), f"已读取 {completed}/{len(futures)} 份行情", symbol=symbol)
    for index, item in enumerate(rows):
        symbol = str(item.get("symbol") or "").strip().upper()
        if progress and (index == 0 or index == len(rows) - 1 or index % max(len(rows) // 40, 1) == 0):
            progress("scan_dislocations", int(30 + (index / max(len(rows), 1)) * 18), f"扫描 {symbol}", symbol=symbol)
        try:
            history = history_cache.get(symbol)
            price = _last_price(history)
            if price is None:
                raise ValueError("missing price history")
            sector_symbol = str(item.get("sector_etf") or "SPY").strip().upper()
            if sector_symbol not in sector_cache:
                sector_cache[sector_symbol] = history_cache.get(sector_symbol)
            dislocation = measure_dislocation(
                history,
                market_history=market_history,
                sector_history=sector_cache[sector_symbol],
            )
            price_source = str(getattr(history, "attrs", {}).get("source") or "unknown")
            scanned.append({"item": item, "symbol": symbol, "price": price, "price_source": price_source, "dislocation": dislocation})
        except Exception as exc:
            errors.append({"symbol": symbol, "stage": "scan", "error": f"{type(exc).__name__}: {exc}"})
    scanned.sort(key=lambda row: float(row["dislocation"].get("dislocation_score") or 0), reverse=True)
    mandatory = [
        row for row in scanned
        if str(row["item"].get("asset_type") or "").lower() == "etf" or bool(row["item"].get("always_analyze"))
    ]
    mandatory_symbols = {row["symbol"] for row in mandatory}
    ranked = [
        row for row in scanned
        if row["symbol"] not in mandatory_symbols
        and float(row["dislocation"].get("dislocation_score") or 0) >= minimum_dislocation
    ]
    deep_limit = max(max_deep_analysis, len(mandatory))
    deep_candidates = mandatory + ranked[: max(deep_limit - len(mandatory), 0)]
    for index, scanned_row in enumerate(deep_candidates):
        item = scanned_row["item"]
        symbol = scanned_row["symbol"]
        price = scanned_row["price"]
        dislocation = scanned_row["dislocation"]
        if progress:
            progress("deep_valuation", int(48 + (index / max(len(deep_candidates), 1)) * 42), f"估值 {symbol}", symbol=symbol)
        try:
            financials = dict(financial_loader(symbol) or {})
            financials.setdefault("symbol", symbol)
            financials.setdefault("asset_type", item.get("asset_type") or "equity")
            financials.setdefault("drawdown_52w", dislocation.get("drawdown_52w"))
            event = dict(event_loader(symbol) or {})
            route = normalize_valuation_route(
                route_loader(
                    symbol=symbol,
                    asset_type=financials["asset_type"],
                    financials=financials,
                    universe_record=item,
                    event_context=event,
                )
            )
            valuation = value_security(
                financials,
                route,
                current_price=price,
                simulations=max(int(policy.get("simulation_count") or 1200), 100),
                seed=sum(ord(char) for char in symbol),
            )
            score = score_opportunity(
                dislocation=dislocation,
                valuation=valuation,
                fundamentals=financials,
                event=event,
                market_risk=dict(market_risk or {}),
                policy=policy,
            )
            if require_llm_route and route.get("route_source") != "llm" and score.get("actionable"):
                score = {
                    **score,
                    "recommendation": "LLM_REVIEW_REQUIRED",
                    "actionable": False,
                    "reason_codes": list(score.get("reason_codes", [])) + ["LLM_ROUTE_REQUIRED"],
                }
            valuation_row = {
                **valuation,
                "fiscal_period": financials.get("fiscal_period"),
                "financial_source": financials.get("source"),
                "route_reasoning": route.get("reasoning"),
                "route_risks": route.get("risks"),
                "filing_summary": route.get("filing_summary"),
                "fundamental_signals": route.get("fundamental_signals"),
                "filing_context": {
                    "status": dict(financials.get("filing_context", {}) or {}).get("status"),
                    "source": dict(financials.get("filing_context", {}) or {}).get("source"),
                    "filings": [
                        {
                            "form": filing.get("form"),
                            "filing_date": filing.get("filing_date"),
                            "report_date": filing.get("report_date"),
                            "url": filing.get("url"),
                            "sections": [
                                {"item": section.get("item"), "title": section.get("title"), "original_char_count": section.get("original_char_count")}
                                for section in list(dict(filing or {}).get("sections", []) or [])
                            ],
                        }
                        for filing in list(dict(financials.get("filing_context", {}) or {}).get("filings", []) or [])
                    ],
                    "errors": list(dict(financials.get("filing_context", {}) or {}).get("errors", []) or []),
                },
            }
            valuations.append(valuation_row)
            opportunities.append(
                {
                    "symbol": symbol,
                    "asset_type": financials["asset_type"],
                    "sector": item.get("sector") or financials.get("sector"),
                    "current_price": price,
                    "price_source": scanned_row.get("price_source"),
                    "fair_value": valuation["fair_value"],
                    "margin_of_safety": valuation["margin_of_safety"],
                    "valuation_confidence": valuation["confidence"],
                    "valuation_model": valuation["primary_model"],
                    "archetype": valuation["archetype"],
                    "dislocation": dislocation,
                    "quality_score": financials.get("quality_score"),
                    "damage_score": financials.get("damage_score"),
                    "distress_probability": financials.get("distress_probability"),
                    "event": event,
                    **score,
                    "fiscal_period": financials.get("fiscal_period"),
                    "financial_source": financials.get("source"),
                    "latest_filing_form": financials.get("latest_filing_form"),
                    "latest_filing_date": financials.get("latest_filing_date"),
                    "filing_summary": route.get("filing_summary"),
                    "fundamental_signals": route.get("fundamental_signals"),
                    "filing_risks": route.get("risks"),
                }
            )
        except Exception as exc:
            errors.append({"symbol": symbol, "stage": "valuation", "error": f"{type(exc).__name__}: {exc}"})
    opportunities.sort(key=lambda row: float(row.get("opportunity_score") or 0), reverse=True)
    generated_at = now.isoformat()
    actionable = [row for row in opportunities if row.get("actionable")]
    filing_covered = [row for row in opportunities if row.get("latest_filing_form")]
    price_source_counts = {}
    for row in scanned:
        source = str(row.get("price_source") or "unknown")
        price_source_counts[source] = price_source_counts.get(source, 0) + 1
    snapshot = {
        "schema_version": 1,
        "generated_at": generated_at,
        "status": "READY" if opportunities else "NO_RESULTS",
        "summary": {
            "universe_count": len(rows),
            "scanned_count": len(scanned),
            "deep_analysis_count": len(deep_candidates),
            "analyzed_count": len(opportunities),
            "actionable_count": len(actionable),
            "filing_coverage_count": len(filing_covered),
            "error_count": len(errors),
            "price_source_counts": price_source_counts,
            "market_regime": dict(market_risk or {}).get("regime", "UNKNOWN"),
        },
        "opportunities": opportunities,
        "errors": errors,
    }
    valuation_snapshot = {
        "schema_version": 1,
        "generated_at": generated_at,
        "status": snapshot["status"],
        "valuations": valuations,
        "errors": errors,
    }
    recommendation_snapshot = {
        "schema_version": 1,
        "generated_at": generated_at,
        "status": snapshot["status"],
        "decision": "OPPORTUNITIES_FOUND" if actionable else "NO_STRONG_SIGNAL",
        "summary": snapshot["summary"],
        "recommendations": opportunities,
    }
    _write_json(snapshot_path, snapshot)
    _write_json(valuation_path, valuation_snapshot)
    _write_json(recommendation_path, recommendation_snapshot)
    if progress:
        progress("completed", 100, f"完成 {len(opportunities)} 个标的分析")
    return snapshot
