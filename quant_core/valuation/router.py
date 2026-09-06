from __future__ import annotations

import json
import math
import re
from typing import Mapping, Optional

from quant_core.llm.openai_compatible import call_openai_compatible_chat


MODEL_BY_ARCHETYPE = {
    "mature_profitable": "fcff_multistage",
    "mature_growth": "fcff_multistage",
    "high_growth_profitable": "revenue_growth_dcf",
    "financial_service": "residual_income",
    "reit": "reit_ffo_nav",
    "cyclical": "normalized_earnings",
    "commodity": "normalized_earnings",
    "unprofitable_growth": "revenue_multiple",
    "conglomerate": "sum_of_parts",
    "distressed": "distress_weighted",
    "broad_market_etf": "etf_risk_premium",
    "sector_etf": "etf_risk_premium",
    "bond_etf": "etf_yield_duration",
    "commodity_etf": "etf_spot_carry",
}

ALLOWED_MODELS = set(MODEL_BY_ARCHETYPE.values())

COMPATIBLE_MODELS = {
    "mature_profitable": {"fcff_multistage", "normalized_earnings"},
    "mature_growth": {"fcff_multistage", "revenue_growth_dcf"},
    "high_growth_profitable": {"revenue_growth_dcf", "fcff_multistage"},
    "financial_service": {"residual_income"},
    "reit": {"reit_ffo_nav"},
    "cyclical": {"normalized_earnings", "fcff_multistage"},
    "commodity": {"normalized_earnings"},
    "unprofitable_growth": {"revenue_multiple"},
    "conglomerate": {"sum_of_parts"},
    "distressed": {"distress_weighted"},
    "broad_market_etf": {"etf_risk_premium"},
    "sector_etf": {"etf_risk_premium"},
    "bond_etf": {"etf_yield_duration"},
    "commodity_etf": {"etf_spot_carry"},
}

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _number(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _scenario(value, defaults) -> dict:
    supplied = dict(value or {}) if isinstance(value, Mapping) else {}
    return {
        "bear": _number(supplied.get("bear"), defaults[0]),
        "base": _number(supplied.get("base"), defaults[1]),
        "bull": _number(supplied.get("bull"), defaults[2]),
    }


def _bounded_scenario(value, defaults, *, low: float, high: float, descending: bool = False) -> tuple[dict, bool]:
    supplied = _scenario(value, defaults)
    bounded = [max(low, min(_number(supplied[name], defaults[index]), high)) for index, name in enumerate(("bear", "base", "bull"))]
    ordered = sorted(bounded, reverse=descending)
    normalized = {name: ordered[index] for index, name in enumerate(("bear", "base", "bull"))}
    return normalized, normalized != supplied


def normalize_valuation_route(route: Optional[Mapping]) -> dict:
    raw = dict(route or {})
    asset_type = str(raw.get("asset_type") or "equity").strip().lower()
    archetype = str(raw.get("archetype") or ("broad_market_etf" if asset_type == "etf" else "mature_profitable")).strip().lower()
    if archetype not in MODEL_BY_ARCHETYPE:
        archetype = "broad_market_etf" if asset_type == "etf" else "mature_profitable"
    expected_model = MODEL_BY_ARCHETYPE[archetype]
    primary = str(raw.get("primary_model") or expected_model).strip().lower()
    warnings = [str(item) for item in list(raw.get("validation_warnings", []) or [])]
    if primary not in COMPATIBLE_MODELS[archetype]:
        primary = expected_model
        warnings.append("route_corrected")
    secondary = []
    for model in list(raw.get("secondary_models", []) or []):
        normalized = str(model or "").strip().lower()
        if normalized in COMPATIBLE_MODELS[archetype] and normalized != primary and normalized not in secondary:
            secondary.append(normalized)
    supplied_assumptions = dict(raw.get("assumptions", {}) or {})
    assumptions = {}
    changed = False
    assumptions["growth_rate"], sanitized = _bounded_scenario(
        supplied_assumptions.get("growth_rate"), (0.01, 0.06, 0.11), low=-0.25, high=0.60
    )
    changed = changed or sanitized
    assumptions["discount_rate"], sanitized = _bounded_scenario(
        supplied_assumptions.get("discount_rate"), (0.12, 0.095, 0.08), low=0.04, high=0.35, descending=True
    )
    changed = changed or sanitized
    terminal, sanitized = _bounded_scenario(
        supplied_assumptions.get("terminal_growth"), (0.015, 0.025, 0.03), low=-0.02, high=0.05
    )
    terminal_ceiling = assumptions["discount_rate"]["bull"] - 0.01
    constrained_terminal = {name: min(value, terminal_ceiling) for name, value in terminal.items()}
    assumptions["terminal_growth"] = constrained_terminal
    changed = changed or sanitized or constrained_terminal != terminal
    assumptions["target_margin"], sanitized = _bounded_scenario(
        supplied_assumptions.get("target_margin"), (0.08, 0.16, 0.24), low=-0.10, high=0.65
    )
    changed = changed or sanitized
    multiple_defaults = (1.5, 3.0, 5.0) if primary == "revenue_multiple" else (9.0, 13.0, 18.0) if primary == "reit_ffo_nav" else (10.0, 15.0, 21.0)
    assumptions["normalized_multiple"], sanitized = _bounded_scenario(
        supplied_assumptions.get("normalized_multiple"), multiple_defaults, low=0.5 if primary == "revenue_multiple" else 2.0, high=60.0
    )
    changed = changed or sanitized
    if changed:
        warnings.append("assumptions_sanitized")
    return {
        "asset_type": asset_type,
        "archetype": archetype,
        "primary_model": primary,
        "secondary_models": secondary,
        "assumptions": assumptions,
        "confidence": max(0.0, min(_number(raw.get("confidence"), 0.45), 1.0)),
        "evidence": [str(item).strip() for item in list(raw.get("evidence", []) or []) if str(item).strip()],
        "reasoning": str(raw.get("reasoning") or "").strip(),
        "filing_summary": str(raw.get("filing_summary") or "").strip(),
        "fundamental_signals": [str(item).strip() for item in list(raw.get("fundamental_signals", []) or []) if str(item).strip()],
        "risks": [str(item).strip() for item in list(raw.get("risks", []) or []) if str(item).strip()],
        "validation_warnings": list(dict.fromkeys(warnings)),
        "route_source": str(raw.get("route_source") or "rules").strip().lower(),
    }


def parse_route_response(text: str) -> dict:
    raw = str(text or "").strip()
    match = _JSON_FENCE.search(raw)
    if match:
        raw = match.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("LLM valuation route must be a JSON object")
    payload["route_source"] = "llm"
    return normalize_valuation_route(payload)


def _rule_route(asset_type: str, financials: Mapping) -> dict:
    kind = str(asset_type or financials.get("asset_type") or "equity").lower()
    sector = str(financials.get("sector") or "").lower()
    revenue = _number(financials.get("revenue"), 0)
    net_income = _number(financials.get("net_income"), 0)
    growth = _number(financials.get("revenue_growth"), 0)
    distress = _number(financials.get("distress_probability"), 0)
    if kind == "etf":
        archetype = "bond_etf" if "bond" in sector else "commodity_etf" if "commodity" in sector else "broad_market_etf"
    elif distress >= 0.35:
        archetype = "distressed"
    elif any(token in sector for token in ("bank", "insurance", "financial")):
        archetype = "financial_service"
    elif any(token in sector for token in ("energy", "materials", "commodity")):
        archetype = "cyclical"
    elif net_income <= 0:
        archetype = "unprofitable_growth"
    elif growth >= 0.18 and revenue > 0:
        archetype = "high_growth_profitable"
    else:
        archetype = "mature_growth"
    return normalize_valuation_route(
        {
            "asset_type": kind,
            "archetype": archetype,
            "confidence": 0.42,
            "reasoning": "Deterministic fallback used because no validated LLM route was available.",
            "evidence": [str(financials.get("fiscal_period") or "latest available financial record")],
            "route_source": "rules",
        }
    )


def route_valuation_model(
    *,
    symbol: str,
    asset_type: str,
    financials: Mapping,
    filing_evidence=None,
    event_context=None,
    llm_config: Optional[Mapping] = None,
    llm_runner=None,
) -> dict:
    fallback = _rule_route(asset_type, financials)
    config = dict(llm_config or {})
    if not config.get("enabled"):
        return fallback
    financial_payload = {key: value for key, value in dict(financials or {}).items() if key not in {"filing_context", "evidence"}}
    filing_context = dict(dict(financials or {}).get("filing_context", {}) or {})
    filing_documents = []
    for filing in list(filing_context.get("filings", []) or [])[:2]:
        filing = dict(filing or {})
        filing_documents.append(
            {
                "form": filing.get("form"),
                "filing_date": filing.get("filing_date"),
                "report_date": filing.get("report_date"),
                "url": filing.get("url"),
                "sections": [
                    {key: section.get(key) for key in ("item", "title", "text")}
                    for section in list(filing.get("sections", []) or [])[:5]
                ],
            }
        )
    prompt_payload = {
        "symbol": str(symbol).upper(),
        "asset_type": asset_type,
        "financials": financial_payload,
        "filing_evidence": list(filing_evidence or [])[:12],
        "filing_documents": filing_documents,
        "event_context": dict(event_context or {}),
        "allowed_archetypes": sorted(MODEL_BY_ARCHETYPE),
        "allowed_models": sorted(ALLOWED_MODELS),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are a valuation model router. Select a model from the supplied whitelist and extract conservative "
                "bear/base/bull assumptions from evidence. Return one JSON object only. Never issue a trade action. "
                "Every material assumption must be traceable to supplied evidence."
            ),
        },
        {
            "role": "user",
            "content": (
                "Classify this security and return keys asset_type, archetype, primary_model, secondary_models, "
                "assumptions, confidence, evidence, reasoning, filing_summary, fundamental_signals, risks. "
                "Use filing text as qualitative evidence, explicitly distinguish disclosed facts from management claims, "
                "and never infer an absent fact. Assumptions should include growth_rate, "
                "discount_rate, terminal_growth, target_margin and normalized_multiple with bear/base/bull values.\n"
                + json.dumps(prompt_payload, ensure_ascii=False, default=str)
            ),
        },
    ]
    runner = llm_runner or call_openai_compatible_chat
    ok, response = runner(messages, config)
    if not ok:
        fallback["validation_warnings"].append("llm_route_unavailable")
        return fallback
    try:
        routed = parse_route_response(response)
    except (ValueError, TypeError, json.JSONDecodeError):
        fallback["validation_warnings"].append("llm_route_invalid")
        return fallback
    if not routed["evidence"]:
        routed["confidence"] = min(routed["confidence"], 0.4)
        routed["validation_warnings"].append("missing_evidence")
    return routed
