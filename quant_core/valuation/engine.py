from __future__ import annotations

import math
from typing import Mapping

import numpy as np

from quant_core.valuation.router import normalize_valuation_route


def _finite(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _scenario(assumptions: Mapping, name: str, scenario: str, default: float) -> float:
    return _finite(dict(assumptions.get(name, {}) or {}).get(scenario), default)


def _dcf_value(*, cash_flow: float, growth: float, discount: float, terminal_growth: float, years: int = 10) -> float:
    if cash_flow <= 0 or discount <= terminal_growth + 0.005:
        return 0.0
    value = 0.0
    current = cash_flow
    for year in range(1, years + 1):
        fading_growth = growth + (terminal_growth - growth) * (year / years) * 0.55
        current *= 1.0 + fading_growth
        value += current / ((1.0 + discount) ** year)
    terminal = current * (1.0 + terminal_growth) / (discount - terminal_growth)
    return value + terminal / ((1.0 + discount) ** years)


def _corporate_scenario(financials: Mapping, assumptions: Mapping, scenario: str, model: str) -> float:
    shares = max(_finite(financials.get("shares_outstanding")), 1.0)
    cash = _finite(financials.get("cash"))
    debt = _finite(financials.get("total_debt"))
    growth = _scenario(assumptions, "growth_rate", scenario, 0.05)
    discount = _scenario(assumptions, "discount_rate", scenario, 0.095)
    terminal = _scenario(assumptions, "terminal_growth", scenario, 0.025)
    if model == "revenue_growth_dcf":
        revenue = _finite(financials.get("revenue"))
        margin = _scenario(assumptions, "target_margin", scenario, 0.15)
        cash_flow = max(revenue * margin * 0.72, 0.0)
    else:
        cash_flow = _finite(financials.get("free_cash_flow"))
    enterprise = _dcf_value(cash_flow=cash_flow, growth=growth, discount=discount, terminal_growth=terminal)
    return max((enterprise + cash - debt) / shares, 0.0)


def _residual_income(financials: Mapping, assumptions: Mapping, scenario: str) -> float:
    shares = max(_finite(financials.get("shares_outstanding")), 1.0)
    equity = max(_finite(financials.get("equity")), 0.0)
    income = _finite(financials.get("net_income"))
    roe = income / equity if equity > 0 else 0.0
    cost = _scenario(assumptions, "discount_rate", scenario, 0.1)
    growth = min(_scenario(assumptions, "terminal_growth", scenario, 0.025), cost - 0.01)
    excess = max((roe - cost) * equity, -equity * 0.5)
    value = equity + excess / max(cost - growth, 0.01)
    return max(value / shares, 0.0)


def _multiple_value(financials: Mapping, assumptions: Mapping, scenario: str, *, revenue_based=False) -> float:
    shares = max(_finite(financials.get("shares_outstanding")), 1.0)
    multiple = _scenario(assumptions, "normalized_multiple", scenario, 15.0)
    base = _finite(financials.get("revenue" if revenue_based else "normalized_earnings"))
    if not revenue_based and base == 0:
        base = _finite(financials.get("net_income"))
    value = base * multiple + _finite(financials.get("cash")) - _finite(financials.get("total_debt"))
    return max(value / shares, 0.0)


def _etf_value(financials: Mapping, current_price: float, scenario: str, model: str) -> float:
    if model == "etf_yield_duration":
        current_yield = _finite(financials.get("distribution_yield"))
        if current_yield <= 0:
            return current_price
        required = {"bear": 0.055, "base": 0.045, "bull": 0.035}[scenario]
        return max(current_price * current_yield / required, current_price * 0.45)
    if model == "etf_spot_carry":
        drawdown = min(_finite(financials.get("drawdown_52w")), 0.0)
        factor = {"bear": 0.88, "base": 1.0 - drawdown * 0.35, "bull": 1.08 - drawdown * 0.6}[scenario]
        return max(current_price * factor, 0.01)
    earnings_yield = _finite(financials.get("earnings_yield"))
    historical = _finite(financials.get("historical_earnings_yield"))
    if earnings_yield <= 0 or historical <= 0:
        return current_price
    earnings_yield = max(earnings_yield, 0.005)
    historical = max(historical, 0.005)
    required = historical * {"bear": 1.18, "base": 1.0, "bull": 0.88}[scenario]
    return max(current_price * earnings_yield / required, current_price * 0.35)


def _scenario_value(financials: Mapping, route: Mapping, current_price: float, scenario: str) -> float:
    model = str(route["primary_model"])
    assumptions = dict(route.get("assumptions", {}) or {})
    if model.startswith("etf_"):
        return _etf_value(financials, current_price, scenario, model)
    if model == "residual_income":
        return _residual_income(financials, assumptions, scenario)
    if model == "normalized_earnings":
        return _multiple_value(financials, assumptions, scenario)
    if model == "revenue_multiple":
        return _multiple_value(financials, assumptions, scenario, revenue_based=True)
    if model == "reit_ffo_nav":
        ffo = _finite(financials.get("funds_from_operations"), _finite(financials.get("free_cash_flow")))
        patched = dict(financials)
        patched["normalized_earnings"] = ffo
        return _multiple_value(patched, assumptions, scenario)
    if model == "sum_of_parts":
        segment_value = sum(_finite(row.get("estimated_value")) for row in list(financials.get("segments", []) or []))
        shares = max(_finite(financials.get("shares_outstanding")), 1.0)
        if segment_value > 0:
            return max((segment_value + _finite(financials.get("cash")) - _finite(financials.get("total_debt"))) / shares, 0.0)
    if model == "distress_weighted":
        going = _corporate_scenario(financials, assumptions, scenario, "fcff_multistage")
        liquidation = max((_finite(financials.get("cash")) + _finite(financials.get("equity")) * 0.35 - _finite(financials.get("total_debt"))) / max(_finite(financials.get("shares_outstanding")), 1.0), 0.0)
        survival = 1.0 - max(0.0, min(_finite(financials.get("distress_probability"), 0.5), 1.0))
        return going * survival + liquidation * (1.0 - survival)
    return _corporate_scenario(financials, assumptions, scenario, model)


def _input_coverage(financials: Mapping, model: str) -> tuple[float, bool]:
    groups_by_model = {
        "fcff_multistage": (("free_cash_flow",), ("shares_outstanding",), ("cash",), ("total_debt",)),
        "revenue_growth_dcf": (("revenue",), ("shares_outstanding",), ("cash",), ("total_debt",)),
        "residual_income": (("equity",), ("net_income",), ("shares_outstanding",)),
        "normalized_earnings": (("normalized_earnings", "net_income"), ("shares_outstanding",), ("cash",), ("total_debt",)),
        "revenue_multiple": (("revenue",), ("shares_outstanding",), ("cash",), ("total_debt",)),
        "reit_ffo_nav": (("funds_from_operations", "free_cash_flow"), ("shares_outstanding",)),
        "sum_of_parts": (("segments",), ("shares_outstanding",)),
        "distress_weighted": (("free_cash_flow",), ("equity",), ("shares_outstanding",), ("total_debt",)),
        "etf_risk_premium": (("earnings_yield",), ("historical_earnings_yield",)),
        "etf_yield_duration": (("distribution_yield",),),
        "etf_spot_carry": (("drawdown_52w",),),
    }
    groups = groups_by_model.get(model, (("shares_outstanding",),))

    def available(group) -> bool:
        for key in group:
            value = financials.get(key)
            if key == "segments" and isinstance(value, list) and value:
                return True
            if value is not None:
                try:
                    if math.isfinite(float(value)):
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    states = [available(group) for group in groups]
    return sum(states) / max(len(states), 1), bool(states and states[0])


def value_security(
    financials: Mapping,
    route: Mapping,
    *,
    current_price: float,
    simulations: int = 1200,
    seed: int = 17,
) -> dict:
    normalized_route = normalize_valuation_route(route)
    current_price = max(_finite(current_price), 0.01)
    primary_model = normalized_route["primary_model"]
    model_values = {}
    for model in [primary_model, *normalized_route["secondary_models"]]:
        _coverage, essential_available = _input_coverage(financials, model)
        if model != primary_model and not essential_available:
            continue
        model_route = {**normalized_route, "primary_model": model}
        model_values[model] = {
            scenario: _scenario_value(financials, model_route, current_price, scenario)
            for scenario in ("bear", "base", "bull")
        }
    scenario_values = {
        scenario: float(np.median([values[scenario] for values in model_values.values()]))
        for scenario in ("bear", "base", "bull")
    }
    ordered = sorted(max(value, 0.01) for value in scenario_values.values())
    low, middle, high = ordered
    rng = np.random.default_rng(seed)
    count = max(int(simulations), 100)
    sigma = max((high - low) / 3.29, middle * 0.04, 0.01)
    samples = np.clip(rng.normal(middle, sigma, count), low * 0.72, high * 1.28)
    p10, p50, p90 = [round(float(value), 4) for value in np.quantile(samples, [0.1, 0.5, 0.9])]
    coverage, essential_available = _input_coverage(financials, primary_model)
    status_factor = 0.85 if str(financials.get("status") or "READY") == "PARTIAL" else 1.0
    essential_factor = 1.0 if essential_available else 0.45
    model_medians = [sorted(values.values())[1] for values in model_values.values()]
    model_dispersion = (max(model_medians) - min(model_medians)) / max(float(np.median(model_medians)), 0.01) if len(model_medians) > 1 else 0.0
    agreement_factor = max(0.55, 1.0 - min(model_dispersion, 1.5) * 0.3)
    confidence = round(max(0.0, min(float(normalized_route["confidence"]) * (0.45 + coverage * 0.55) * status_factor * essential_factor * agreement_factor, 1.0)), 3)
    validation_warnings = list(normalized_route["validation_warnings"])
    if coverage < 0.75 or not essential_available:
        validation_warnings.append("missing_valuation_inputs")
    margin = round(p50 / current_price - 1.0, 4)
    dispersion = round(max((p90 - p10) / max(p50, 0.01), model_dispersion), 4)
    return {
        "symbol": str(financials.get("symbol") or "").upper(),
        "asset_type": normalized_route["asset_type"],
        "archetype": normalized_route["archetype"],
        "primary_model": normalized_route["primary_model"],
        "secondary_models": normalized_route["secondary_models"],
        "current_price": round(current_price, 4),
        "scenario_values": {key: round(value, 4) for key, value in scenario_values.items()},
        "model_values": {
            model: {key: round(value, 4) for key, value in values.items()}
            for model, values in model_values.items()
        },
        "model_count": len(model_values),
        "model_dispersion": round(model_dispersion, 4),
        "fair_value": {"p10": p10, "p50": p50, "p90": p90},
        "margin_of_safety": margin,
        "dispersion": dispersion,
        "confidence": confidence,
        "assumptions": normalized_route["assumptions"],
        "route_source": normalized_route["route_source"],
        "evidence": normalized_route["evidence"],
        "risks": normalized_route["risks"],
        "validation_warnings": list(dict.fromkeys(validation_warnings)),
    }
