from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from typing import Iterable, Mapping, Optional

from quant_core.llm.openai_compatible import call_openai_compatible_chat


TEMPORARY_HINTS = ("temporary", "delay", "investigation", "guidance", "tariff", "policy", "rumor", "短期", "暂时")
STRUCTURAL_HINTS = ("fraud", "bankruptcy", "default", "delist", "accounting", "lost market share", "破产", "造假", "退市")
CATALYST_HINTS = ("earnings", "product", "approval", "buyback", "recovery", "财报", "新品", "回购", "批准")


def build_event_context(symbol: str, events: Iterable) -> dict:
    symbol = str(symbol or "").strip().upper()
    relevant = []
    for event in list(events or []):
        event_symbols = {str(value).strip().upper() for value in list(getattr(event, "symbols", []) or [])}
        if event_symbols and symbol not in event_symbols:
            continue
        relevant.append(event)
    if not relevant:
        return {"transience_probability": 0.5, "catalyst_score": 25.0, "summary": "暂无经过验证的相关事件", "evidence": []}
    text = " ".join(f"{getattr(event, 'title', '')} {getattr(event, 'notes', '')}" for event in relevant).lower()
    transient = 0.55 + sum(0.07 for hint in TEMPORARY_HINTS if hint in text) - sum(0.18 for hint in STRUCTURAL_HINTS if hint in text)
    catalyst = 25 + sum(12 for hint in CATALYST_HINTS if hint in text)
    negative_structural = any(hint in text for hint in STRUCTURAL_HINTS)
    return {
        "transience_probability": round(max(0.05, min(transient, 0.95)), 3),
        "catalyst_score": round(max(0.0, min(catalyst, 100.0)), 1),
        "structural_risk": negative_structural,
        "summary": "；".join(str(getattr(event, "title", "")).strip() for event in relevant[:3] if str(getattr(event, "title", "")).strip()),
        "evidence": [
            {
                "title": str(getattr(event, "title", "")),
                "source": str(getattr(event, "source", "")),
                "verified": bool(getattr(event, "verified", False)),
                "confidence": getattr(event, "confidence_score", None),
            }
            for event in relevant[:5]
        ],
    }


def fetch_recent_news_context(symbol: str, *, max_items: int = 8) -> dict:
    if importlib.util.find_spec("yfinance") is None:
        return build_event_context(symbol, [])
    try:
        import yfinance as yf

        rows = list(getattr(yf.Ticker(symbol), "news", []) or [])[:max_items]
    except Exception:
        return build_event_context(symbol, [])
    evidence = []
    for row in rows:
        payload = dict(row.get("content", {}) or row)
        title = str(payload.get("title") or row.get("title") or "").strip()
        if not title:
            continue
        provider = dict(payload.get("provider", {}) or {})
        evidence.append(
            {
                "title": title,
                "summary": str(payload.get("summary") or payload.get("description") or "").strip(),
                "source": str(provider.get("displayName") or payload.get("publisher") or "Yahoo Finance"),
                "published_at": payload.get("pubDate") or payload.get("providerPublishTime"),
                "url": str(dict(payload.get("canonicalUrl", {}) or {}).get("url") or payload.get("link") or ""),
            }
        )
    proxy_events = [
        type("NewsEvent", (), {"title": row["title"], "notes": row["summary"], "symbols": [symbol], "source": row["source"], "verified": False, "confidence_score": 0.5})()
        for row in evidence
    ]
    context = build_event_context(symbol, proxy_events)
    context["evidence"] = evidence
    return context


def analyze_event_context(
    symbol: str,
    context: Mapping,
    *,
    llm_config: Optional[Mapping] = None,
    llm_runner=None,
) -> dict:
    fallback = dict(context or {})
    config = dict(llm_config or {})
    if not config.get("enabled") or not list(fallback.get("evidence", []) or []):
        fallback["analysis_source"] = "rules"
        return fallback
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze why a security sold off. Use only supplied headlines and summaries. Return JSON only with "
                "transience_probability (0-1), catalyst_score (0-100), structural_risk (boolean), summary (Chinese), "
                "risks (array), evidence_titles (array). Do not issue a trade recommendation."
            ),
        },
        {"role": "user", "content": json.dumps({"symbol": symbol, "news": fallback.get("evidence", [])}, ensure_ascii=False)},
    ]
    route_config = {**config, "max_tokens": max(int(config.get("max_tokens") or 300), 900)}
    ok, response = (llm_runner or call_openai_compatible_chat)(messages, route_config)
    if not ok:
        fallback["analysis_source"] = "rules"
        fallback["llm_error"] = str(response)
        return fallback
    try:
        raw = str(response).strip()
        raw = raw[raw.find("{") : raw.rfind("}") + 1]
        parsed = json.loads(raw)
        transient = max(0.0, min(float(parsed.get("transience_probability")), 1.0))
        catalyst = max(0.0, min(float(parsed.get("catalyst_score")), 100.0))
    except Exception:
        fallback["analysis_source"] = "rules"
        fallback["llm_error"] = "invalid structured event response"
        return fallback
    return {
        **fallback,
        "transience_probability": round(transient, 3),
        "catalyst_score": round(catalyst, 1),
        "structural_risk": bool(parsed.get("structural_risk")),
        "summary": str(parsed.get("summary") or fallback.get("summary") or "").strip(),
        "risks": [str(value).strip() for value in list(parsed.get("risks", []) or []) if str(value).strip()],
        "analysis_source": "llm",
        "analyzed_at": datetime.now().isoformat(),
    }
