from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core.opportunities.dislocation import measure_dislocation
from quant_core.opportunities.scoring import score_opportunity
from quant_core.etf.allocation import analyze_etf_allocation
from quant_core.trend.engine import analyze_trend, score_trend_candidate
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
    trend_snapshot_path: Optional[str] = None,
    etf_snapshot_path: Optional[str] = None,
    routing_diagnostics=None,
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
    minimum_trend = float(policy.get("minimum_trend_score") or 58)
    require_llm_route = bool(policy.get("require_llm_route_for_action", False))
    market_history = history_loader("SPY", period=history_period)
    opportunities = []
    valuations = []
    trend_results = []
    etf_allocations = []
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
            trend = analyze_trend(
                history,
                market_history=market_history,
                sector_history=sector_cache[sector_symbol],
            )
            price_source = str(getattr(history, "attrs", {}).get("source") or "unknown")
            scanned.append({"item": item, "symbol": symbol, "price": price, "price_source": price_source, "dislocation": dislocation, "trend": trend})
        except Exception as exc:
            errors.append({"symbol": symbol, "stage": "scan", "error": f"{type(exc).__name__}: {exc}"})
    etf_candidates = [row for row in scanned if str(row["item"].get("asset_type") or "").lower() == "etf"]
    equities = [row for row in scanned if str(row["item"].get("asset_type") or "equity").lower() != "etf"]
    mandatory_equities = [row for row in equities if bool(row["item"].get("always_analyze"))]
    mandatory_symbols = {row["symbol"] for row in mandatory_equities}
    value_ranked = sorted(
        [row for row in equities if row["symbol"] not in mandatory_symbols and float(row["dislocation"].get("dislocation_score") or 0) >= minimum_dislocation],
        key=lambda row: float(row["dislocation"].get("dislocation_score") or 0),
        reverse=True,
    )
    trend_ranked = sorted(
        [row for row in equities if row["symbol"] not in mandatory_symbols and float(row["trend"].get("trend_score") or 0) >= minimum_trend],
        key=lambda row: float(row["trend"].get("trend_score") or 0),
        reverse=True,
    )
    value_screen_symbols = {row["symbol"] for row in value_ranked}
    trend_screen_symbols = {row["symbol"] for row in trend_ranked}
    deep_limit = max(max_deep_analysis, len(etf_candidates))
    equity_capacity = max(deep_limit - len(etf_candidates), 0)
    selected_equities = mandatory_equities[:equity_capacity]
    selected_symbols = {row["symbol"] for row in selected_equities}
    open_slots = max(equity_capacity - len(selected_equities), 0)
    trend_slots = min(len(trend_ranked), (open_slots + 1) // 2)
    for row in trend_ranked[:trend_slots]:
        if row["symbol"] not in selected_symbols:
            selected_equities.append(row)
            selected_symbols.add(row["symbol"])
    for row in value_ranked:
        if len(selected_equities) >= equity_capacity:
            break
        if row["symbol"] not in selected_symbols:
            selected_equities.append(row)
            selected_symbols.add(row["symbol"])
    for row in trend_ranked[trend_slots:]:
        if len(selected_equities) >= equity_capacity:
            break
        if row["symbol"] not in selected_symbols:
            selected_equities.append(row)
            selected_symbols.add(row["symbol"])
    deep_candidates = etf_candidates + selected_equities

    for scanned_row in etf_candidates:
        symbol = scanned_row["symbol"]
        try:
            financials = dict(financial_loader(symbol) or {})
            financials.setdefault("symbol", symbol)
            financials.setdefault("asset_type", "etf")
            etf_allocations.append(
                analyze_etf_allocation(
                    scanned_row["item"],
                    history_cache.get(symbol),
                    financials=financials,
                    market_risk=market_risk,
                    benchmark_history=market_history,
                )
            )
        except Exception as exc:
            errors.append({"symbol": symbol, "stage": "etf_allocation", "error": f"{type(exc).__name__}: {exc}"})

    preliminary_trends = sorted(equities, key=lambda row: float(row["trend"].get("trend_score") or 0), reverse=True)[:100]
    trend_by_symbol = {}
    for row in preliminary_trends:
        trend_score = score_trend_candidate(row["trend"], market_risk=market_risk)
        trend_by_symbol[row["symbol"]] = {
            "symbol": row["symbol"],
            "sector": row["item"].get("sector"),
            "current_price": row["price"],
            "price_source": row.get("price_source"),
            "trend": row["trend"],
            **trend_score,
        }
    for index, scanned_row in enumerate(selected_equities):
        item = scanned_row["item"]
        symbol = scanned_row["symbol"]
        price = scanned_row["price"]
        dislocation = scanned_row["dislocation"]
        selection_lanes = []
        if symbol in value_screen_symbols or bool(item.get("always_analyze")):
            selection_lanes.append("VALUE_REVERSAL")
        if symbol in trend_screen_symbols:
            selection_lanes.append("TREND_ACCELERATION")
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
            if require_llm_route and route.get("route_source") not in {"llm", "llm_cache"} and score.get("actionable"):
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
                "selection_lanes": selection_lanes,
            }
            valuations.append(valuation_row)
            trend_score = score_trend_candidate(scanned_row["trend"], fundamentals=financials, market_risk=market_risk)
            trend_by_symbol[symbol] = {
                "symbol": symbol,
                "sector": item.get("sector") or financials.get("sector"),
                "current_price": price,
                "price_source": scanned_row.get("price_source"),
                "trend": scanned_row["trend"],
                "quality_score": financials.get("quality_score"),
                "damage_score": financials.get("damage_score"),
                "distress_probability": financials.get("distress_probability"),
                "fiscal_period": financials.get("fiscal_period"),
                "latest_filing_date": financials.get("latest_filing_date"),
                **trend_score,
            }
            if "VALUE_REVERSAL" in selection_lanes:
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
                    "valuation_dispersion": valuation["dispersion"],
                    "valuation_usable": valuation["valuation_usable"],
                    "valuation_warnings": valuation["validation_warnings"],
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
                        "selection_lanes": selection_lanes,
                    }
                )
        except Exception as exc:
            errors.append({"symbol": symbol, "stage": "valuation", "error": f"{type(exc).__name__}: {exc}"})
    trend_results = sorted(trend_by_symbol.values(), key=lambda row: float(row.get("signal_score") or 0), reverse=True)
    etf_allocations.sort(key=lambda row: float(row.get("allocation_score") or 0), reverse=True)
    opportunities.sort(key=lambda row: float(row.get("opportunity_score") or 0), reverse=True)
    generated_at = now.isoformat()
    actionable = [row for row in opportunities if row.get("actionable")]
    filing_covered = [row for row in valuations if row.get("filing_context", {}).get("filings")]
    trend_actionable = [row for row in trend_results if row.get("actionable")]
    trend_candidates = [row for row in trend_results if float(dict(row.get("trend", {}) or {}).get("trend_score") or 0) >= minimum_trend]
    route_source_counts = {}
    for row in valuations:
        source = str(row.get("route_source") or "unknown")
        route_source_counts[source] = route_source_counts.get(source, 0) + 1
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
            "analyzed_count": len(valuations),
            "value_candidate_count": len(opportunities),
            "actionable_count": len(actionable),
            "trend_candidate_count": len(trend_candidates),
            "trend_actionable_count": len(trend_actionable),
            "trend_scanned_count": len(equities),
            "etf_analysis_count": len(etf_allocations),
            "filing_coverage_count": len(filing_covered),
            "error_count": len(errors),
            "price_source_counts": price_source_counts,
            "market_regime": dict(market_risk or {}).get("regime", "UNKNOWN"),
            "route_source_counts": route_source_counts,
            "llm_routing": dict(routing_diagnostics() or {}) if callable(routing_diagnostics) else {},
        },
        "opportunities": opportunities,
        "trend_signals": trend_results,
        "etf_allocations": etf_allocations,
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
        "trend_signals": trend_results,
        "etf_allocations": etf_allocations,
    }
    _write_json(snapshot_path, snapshot)
    _write_json(valuation_path, valuation_snapshot)
    _write_json(recommendation_path, recommendation_snapshot)
    if trend_snapshot_path:
        _write_json(
            trend_snapshot_path,
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "status": "READY" if trend_results else "NO_RESULTS",
                "summary": {"scanned_count": len(equities), "candidate_count": len(trend_candidates), "published_count": len(trend_results), "actionable_count": len(trend_actionable)},
                "trends": trend_results,
                "errors": [row for row in errors if row.get("stage") in {"history", "scan", "valuation"}],
            },
        )
    if etf_snapshot_path:
        _write_json(
            etf_snapshot_path,
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "status": "READY" if etf_allocations else "NO_RESULTS",
                "summary": {"analyzed_count": len(etf_allocations)},
                "allocations": etf_allocations,
                "errors": [row for row in errors if row.get("stage") == "etf_allocation"],
            },
        )
    if progress:
        progress("completed", 100, f"完成 {len(opportunities)} 个标的分析")
    return snapshot
