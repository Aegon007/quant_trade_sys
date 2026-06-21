from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths
from quant_core.events.news_summary import build_news_summary_payload, summarize_news_events
from quant_core.llm import explainer


DEFAULT_NEWS_INTELLIGENCE_FILE = qpaths.NEWS_INTELLIGENCE_FILE
_NEGATIVE_SENTIMENTS = {"negative", "bearish", "risk_off"}
_POSITIVE_SENTIMENTS = {"positive", "bullish", "risk_on"}


def _symbol(value) -> str:
    return str(value or "").strip().upper()


def _confidence(event) -> float:
    try:
        return max(0.0, min(float(getattr(event, "confidence_score", 0.0) or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _severity_score(value) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(str(value or "").strip().lower(), 2)


def build_analyst_context(analyst_cache: Mapping, symbols: Iterable[str]) -> dict:
    cache = dict(analyst_cache or {})
    recommendations = dict(cache.get("recommendations", {}) or {})
    records = []
    for raw_symbol in symbols or []:
        symbol = _symbol(raw_symbol)
        row = dict(recommendations.get(symbol, {}) or {})
        if not row:
            continue
        records.append(
            {
                "symbol": symbol,
                "signal": str(row.get("signal") or "NEUTRAL").upper(),
                "total_analysts": int(row.get("total_analysts") or row.get("total") or 0),
                "bullish_ratio": row.get("bullish_ratio"),
                "bearish_ratio": row.get("bearish_ratio"),
                "reason": str(row.get("reason") or "").strip(),
                "source": str(row.get("source") or "unknown").strip(),
                "retrieved_at": row.get("retrieved_at"),
                "is_etf_proxy": bool(row.get("is_etf_proxy")),
            }
        )
    return {
        "input_type": "structured_consensus",
        "includes_report_text": False,
        "last_updated": cache.get("last_updated"),
        "covered_count": len(records),
        "records": records,
        "note": "Analyst input contains structured recommendation counts only; it does not contain research-report text.",
    }


def _event_applies_to_symbol(event, symbol: str) -> bool:
    event_symbols = {_symbol(value) for value in list(getattr(event, "symbols", []) or []) if _symbol(value)}
    return not event_symbols or symbol in event_symbols


def _impact_direction(events) -> str:
    positive = sum(1 for event in events if str(getattr(event, "sentiment", "")).lower() in _POSITIVE_SENTIMENTS)
    negative = sum(1 for event in events if str(getattr(event, "sentiment", "")).lower() in _NEGATIVE_SENTIMENTS)
    if positive and negative:
        return "MIXED"
    if positive:
        return "POSITIVE"
    if negative:
        return "NEGATIVE"
    return "NEUTRAL"


def _risk_action(events, direction: str) -> str:
    high_confidence_negative = any(
        str(getattr(event, "severity", "")).lower() == "high"
        and str(getattr(event, "sentiment", "")).lower() in _NEGATIVE_SENTIMENTS
        and _confidence(event) >= 0.65
        for event in events
    )
    if high_confidence_negative:
        return "REVIEW"
    if direction in {"NEGATIVE", "MIXED"}:
        return "WATCH"
    return "NONE"


def _impact_summary(symbol: str, events, direction: str) -> str:
    titles = [str(getattr(event, "title", "") or "").strip() for event in events]
    titles = [title for title in titles if title]
    direction_text = {
        "POSITIVE": "偏正面",
        "NEGATIVE": "偏负面",
        "MIXED": "多空混合",
        "NEUTRAL": "中性",
    }[direction]
    evidence = "；".join(titles[:2]) or "暂无可读标题"
    return f"{symbol} 新闻影响{direction_text}：{evidence}"


def build_structured_portfolio_impacts(events, symbols: Iterable[str]) -> list[dict]:
    rows = []
    for raw_symbol in symbols or []:
        symbol = _symbol(raw_symbol)
        if not symbol:
            continue
        relevant = [event for event in events if _event_applies_to_symbol(event, symbol)]
        if not relevant:
            continue
        relevant.sort(
            key=lambda event: (_severity_score(getattr(event, "severity", "")), _confidence(event)),
            reverse=True,
        )
        direction = _impact_direction(relevant)
        confidence = max((_confidence(event) for event in relevant), default=0.0)
        relevance_score = min(
            100,
            round(
                sum(
                    _severity_score(getattr(event, "severity", "")) * 18
                    + _confidence(event) * 20
                    + (8 if bool(getattr(event, "verified", False)) else 0)
                    for event in relevant[:3]
                )
            ),
        )
        rows.append(
            {
                "symbol": symbol,
                "relevance_score": relevance_score,
                "direction": direction,
                "horizon": "SHORT_TO_MEDIUM",
                "confidence": round(confidence, 3),
                "risk_action": _risk_action(relevant, direction),
                "summary": _impact_summary(symbol, relevant, direction),
                "event_ids": [str(getattr(event, "event_id", "") or "") for event in relevant[:3]],
                "evidence": [
                    {
                        "title": str(getattr(event, "title", "") or "").strip(),
                        "source": str(getattr(event, "source", "") or "").strip(),
                        "verified": bool(getattr(event, "verified", False)),
                        "severity": str(getattr(event, "severity", "medium") or "medium"),
                        "confidence": round(_confidence(event), 3),
                    }
                    for event in relevant[:3]
                ],
            }
        )
    return sorted(rows, key=lambda row: (row["relevance_score"], row["confidence"]), reverse=True)


def _market_risk_level(events) -> str:
    risk_score = sum(
        _severity_score(getattr(event, "severity", "medium"))
        for event in events
        if str(getattr(event, "sentiment", "")).lower() in _NEGATIVE_SENTIMENTS
    )
    if risk_score >= 6:
        return "HIGH"
    if risk_score >= 3:
        return "MEDIUM"
    return "LOW"


def build_news_intelligence(
    *,
    events,
    portfolio_symbols: Iterable[str],
    candidate_symbols: Iterable[str],
    analyst_cache: Mapping,
    notification_config: Mapping,
    llm_runner=None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    event_list = list(events or [])
    tracked_symbols = list(
        dict.fromkeys(
            [_symbol(value) for value in list(portfolio_symbols or []) + list(candidate_symbols or []) if _symbol(value)]
        )
    )
    summary_payload = build_news_summary_payload(summarize_news_events(event_list, lang="zh", max_headlines=5))
    analyst_context = build_analyst_context(analyst_cache, tracked_symbols)
    impacts = build_structured_portfolio_impacts(event_list, tracked_symbols)
    structured_payload = {
        **summary_payload,
        "portfolio_impacts": impacts[:12],
        "analyst_context": analyst_context,
        "market_risk_level": _market_risk_level(event_list),
    }
    if not event_list:
        return {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "status": "NO_EVENTS",
            "market_risk_level": "LOW",
            "executive_summary": summary_payload["overview"],
            "portfolio_impacts": [],
            "analyst_context": analyst_context,
            "structured_summary": summary_payload,
            "llm": {"route_name": "", "model": "", "cached": False, "fallback_attempts": []},
        }

    llm_runner = llm_runner or explainer.analyze_portfolio_news
    ok, text, meta = llm_runner(
        news_payload=structured_payload,
        notification_config=notification_config,
    )
    fallback_summary = "；".join(row["summary"] for row in impacts[:3]) or summary_payload["overview"]
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": "READY" if ok else "STRUCTURED_ONLY",
        "market_risk_level": structured_payload["market_risk_level"],
        "executive_summary": str(text or "").strip() if ok else fallback_summary,
        "portfolio_impacts": impacts,
        "analyst_context": analyst_context,
        "structured_summary": summary_payload,
        "llm": {
            "route_name": str(dict(meta or {}).get("route_name") or ""),
            "model": str(dict(meta or {}).get("model") or ""),
            "cached": bool(dict(meta or {}).get("cached")),
            "fallback_attempts": list(dict(meta or {}).get("fallback_attempts", []) or []),
            "error": "" if ok else str(text or "").strip(),
        },
    }


def save_news_intelligence(payload: Mapping, *, path: str = DEFAULT_NEWS_INTELLIGENCE_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return str(target)


def load_news_intelligence(*, path: str = DEFAULT_NEWS_INTELLIGENCE_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
