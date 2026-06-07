from dataclasses import dataclass, field
import hashlib
import json
from typing import Iterable, List


_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_SENTIMENT_WEIGHT = {"negative": 2, "neutral": 1, "positive": 0}
_SENTIMENT_LABEL_ZH = {"negative": "偏负面", "neutral": "中性", "positive": "偏正面"}
_THEME_LABELS = {
    "fomc": ("FOMC / 利率", "FOMC / Rates"),
    "macro": ("宏观数据", "Macro"),
    "policy": ("政策监管", "Policy"),
    "geopolitical": ("地缘风险", "Geopolitics"),
    "earnings": ("财报", "Earnings"),
    "company": ("公司要闻", "Company"),
    "sector": ("行业主题", "Sector Theme"),
}


@dataclass(frozen=True)
class NewsSummary:
    overview: str
    event_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    dominant_sentiment: str
    high_severity_count: int
    verified_count: int
    top_headlines: List[str] = field(default_factory=list)
    top_headline_details: List["HeadlineRankDetail"] = field(default_factory=list)
    focus_points: List[str] = field(default_factory=list)
    theme_focuses: List["ThemeFocus"] = field(default_factory=list)


@dataclass(frozen=True)
class HeadlineRankDetail:
    event_id: str
    headline: str
    total_score: float
    severity_component: float
    sentiment_component: float
    confidence_component: float
    verified_component: float
    event_type_component: float
    explanation_zh: str
    explanation_en: str


@dataclass(frozen=True)
class ThemeFocus:
    theme_key: str
    label_zh: str
    label_en: str
    event_count: int
    dominant_sentiment: str
    high_severity_count: int
    verified_count: int
    top_symbols: List[str] = field(default_factory=list)
    top_headlines: List[str] = field(default_factory=list)
    summary_zh: str = ""
    summary_en: str = ""
    priority_score: float = 0.0


def _dominant_sentiment(positive_count: int, neutral_count: int, negative_count: int) -> str:
    if negative_count > 0 and negative_count >= positive_count:
        return "negative"
    if positive_count > max(negative_count, neutral_count):
        return "positive"
    return "neutral"


def _headline_score_breakdown(event) -> HeadlineRankDetail:
    severity = _SEVERITY_WEIGHT.get(str(getattr(event, "severity", "medium")).lower(), 2)
    sentiment = _SENTIMENT_WEIGHT.get(str(getattr(event, "sentiment", "neutral")).lower(), 1)
    confidence = float(getattr(event, "confidence_score", 0.5) or 0.5)
    verified = 1 if bool(getattr(event, "verified", False)) else 0
    event_type = str(getattr(event, "event_type", "")).lower()
    event_bonus = 1 if event_type in ("fomc", "macro", "policy", "geopolitical") else 0
    severity_component = float(severity * 2)
    sentiment_component = float(sentiment)
    confidence_component = float(confidence)
    verified_component = float(verified)
    event_type_component = float(event_bonus)
    total_score = (
        severity_component
        + sentiment_component
        + confidence_component
        + verified_component
        + event_type_component
    )
    headline = _format_headline(event)
    event_id = str(getattr(event, "event_id", "") or headline)
    explanation_zh = (
        f"总分 {total_score:.2f} = 强度分 {severity_component:.2f} + 情绪分 {sentiment_component:.2f} + "
        f"置信度分 {confidence_component:.2f} + 核验加分 {verified_component:.2f} + 事件类型加分 {event_type_component:.2f}"
    )
    explanation_en = (
        f"Total {total_score:.2f} = Severity {severity_component:.2f} + Sentiment {sentiment_component:.2f} + "
        f"Confidence {confidence_component:.2f} + Verified bonus {verified_component:.2f} + Event-type bonus {event_type_component:.2f}"
    )
    return HeadlineRankDetail(
        event_id=event_id,
        headline=headline,
        total_score=total_score,
        severity_component=severity_component,
        sentiment_component=sentiment_component,
        confidence_component=confidence_component,
        verified_component=verified_component,
        event_type_component=event_type_component,
        explanation_zh=explanation_zh,
        explanation_en=explanation_en,
    )


def _format_headline(event) -> str:
    title = str(getattr(event, "title", "")).strip() or "Untitled"
    source = str(getattr(event, "source", "")).strip()
    if source:
        return f"{title} ({source})"
    return title


def _theme_key(event) -> str:
    event_type = str(getattr(event, "event_type", "") or "").strip().lower()
    tags = {str(tag or "").strip().lower() for tag in list(getattr(event, "tags", []) or []) if str(tag or "").strip()}
    symbols = [str(symbol or "").strip().upper() for symbol in list(getattr(event, "symbols", []) or []) if str(symbol or "").strip()]
    if event_type in _THEME_LABELS:
        return event_type
    for tag in tags:
        if tag in _THEME_LABELS:
            return tag
    if len(symbols) == 1:
        return f"symbol:{symbols[0]}"
    if len(symbols) > 1:
        return "sector"
    return "company"


def _theme_labels(theme_key: str) -> tuple[str, str]:
    theme_key = str(theme_key or "").strip().lower()
    if theme_key.startswith("symbol:"):
        symbol = theme_key.split(":", 1)[1].strip().upper()
        return f"{symbol} 跟踪", f"{symbol} Focus"
    return _THEME_LABELS.get(theme_key, ("公司要闻", "Company"))


def _theme_summary_lines(*, label_zh: str, label_en: str, event_count: int, dominant_sentiment: str, high_severity_count: int, symbols: list[str]) -> tuple[str, str]:
    sentiment_zh = _SENTIMENT_LABEL_ZH.get(dominant_sentiment, "中性")
    symbols_text = "、".join(symbols[:3]) if symbols else "广泛市场"
    summary_zh = (
        f"{label_zh} {event_count} 条，整体{sentiment_zh}"
        f"{'，高强度 ' + str(high_severity_count) + ' 条' if high_severity_count else ''}，"
        f"重点涉及 {symbols_text}。"
    )
    summary_en = (
        f"{label_en}: {event_count} items, overall {dominant_sentiment}"
        f"{', high-severity ' + str(high_severity_count) if high_severity_count else ''}, "
        f"focused on {', '.join(symbols[:3]) if symbols else 'broader market'}."
    )
    return summary_zh, summary_en


def _build_theme_focuses(event_list, scored_details):
    buckets = {}
    for event, detail in zip(event_list, scored_details):
        theme_key = _theme_key(event)
        bucket = buckets.setdefault(
            theme_key,
            {
                "events": [],
                "details": [],
                "symbols": [],
            },
        )
        bucket["events"].append(event)
        bucket["details"].append(detail)
        for symbol in list(getattr(event, "symbols", []) or []):
            symbol = str(symbol or "").strip().upper()
            if symbol and symbol not in bucket["symbols"]:
                bucket["symbols"].append(symbol)

    theme_focuses = []
    for theme_key, bucket in buckets.items():
        events = list(bucket["events"])
        details = list(bucket["details"])
        symbols = list(bucket["symbols"])
        positive_count = sum(1 for event in events if str(getattr(event, "sentiment", "neutral")).lower() == "positive")
        negative_count = sum(1 for event in events if str(getattr(event, "sentiment", "neutral")).lower() == "negative")
        neutral_count = len(events) - positive_count - negative_count
        dominant_sentiment = _dominant_sentiment(positive_count, neutral_count, negative_count)
        high_severity_count = sum(
            1 for event in events if str(getattr(event, "severity", "medium")).lower() == "high"
        )
        verified_count = sum(1 for event in events if bool(getattr(event, "verified", False)))
        label_zh, label_en = _theme_labels(theme_key)
        summary_zh, summary_en = _theme_summary_lines(
            label_zh=label_zh,
            label_en=label_en,
            event_count=len(events),
            dominant_sentiment=dominant_sentiment,
            high_severity_count=high_severity_count,
            symbols=symbols,
        )
        top_headlines = [detail.headline for detail in sorted(details, key=lambda row: row.total_score, reverse=True)[:2]]
        priority_score = sum(float(detail.total_score) for detail in sorted(details, key=lambda row: row.total_score, reverse=True)[:2])
        priority_score += float(high_severity_count) * 2.0
        priority_score += float(len(events)) * 0.35
        theme_focuses.append(
            ThemeFocus(
                theme_key=theme_key,
                label_zh=label_zh,
                label_en=label_en,
                event_count=len(events),
                dominant_sentiment=dominant_sentiment,
                high_severity_count=high_severity_count,
                verified_count=verified_count,
                top_symbols=symbols[:4],
                top_headlines=top_headlines,
                summary_zh=summary_zh,
                summary_en=summary_en,
                priority_score=priority_score,
            )
        )
    return sorted(theme_focuses, key=lambda row: row.priority_score, reverse=True)


def build_news_summary_payload(summary: NewsSummary) -> dict:
    focus_points = list(getattr(summary, "focus_points", []) or [])
    theme_focuses = list(getattr(summary, "theme_focuses", []) or [])
    return {
        "overview": str(getattr(summary, "overview", "") or "").strip(),
        "event_count": int(getattr(summary, "event_count", 0) or 0),
        "dominant_sentiment": str(getattr(summary, "dominant_sentiment", "neutral") or "neutral"),
        "high_severity_count": int(getattr(summary, "high_severity_count", 0) or 0),
        "verified_count": int(getattr(summary, "verified_count", 0) or 0),
        "focus_points": focus_points,
        "theme_focuses": [
            {
                "theme_key": getattr(item, "theme_key", ""),
                "label_zh": getattr(item, "label_zh", ""),
                "label_en": getattr(item, "label_en", ""),
                "event_count": getattr(item, "event_count", 0),
                "dominant_sentiment": getattr(item, "dominant_sentiment", "neutral"),
                "high_severity_count": getattr(item, "high_severity_count", 0),
                "verified_count": getattr(item, "verified_count", 0),
                "top_symbols": list(getattr(item, "top_symbols", []) or []),
                "top_headlines": list(getattr(item, "top_headlines", []) or []),
                "summary_zh": getattr(item, "summary_zh", ""),
                "summary_en": getattr(item, "summary_en", ""),
                "priority_score": float(getattr(item, "priority_score", 0.0) or 0.0),
            }
            for item in theme_focuses
        ],
        "top_headlines": list(getattr(summary, "top_headlines", []) or []),
    }


def build_news_summary_signature(summary: NewsSummary) -> str:
    payload = build_news_summary_payload(summary)
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest


def summarize_news_events(events: Iterable, lang: str = "zh", max_headlines: int = 3) -> NewsSummary:
    event_list = list(events or [])
    if not event_list:
        overview = "当前暂无生效中的新闻/事件输入。" if lang == "zh" else "No active news/events at the moment."
        return NewsSummary(
            overview=overview,
            event_count=0,
            positive_count=0,
            neutral_count=0,
            negative_count=0,
            dominant_sentiment="neutral",
            high_severity_count=0,
            verified_count=0,
            top_headlines=[],
            top_headline_details=[],
            focus_points=[],
            theme_focuses=[],
        )

    positive_count = 0
    neutral_count = 0
    negative_count = 0
    high_severity_count = 0
    verified_count = 0
    for event in event_list:
        sentiment = str(getattr(event, "sentiment", "neutral")).lower()
        if sentiment == "positive":
            positive_count += 1
        elif sentiment == "negative":
            negative_count += 1
        else:
            neutral_count += 1
        if str(getattr(event, "severity", "medium")).lower() == "high":
            high_severity_count += 1
        if bool(getattr(event, "verified", False)):
            verified_count += 1

    dominant = _dominant_sentiment(positive_count, neutral_count, negative_count)

    if lang == "zh":
        sentiment_label = _SENTIMENT_LABEL_ZH[dominant]
        overview = (
            f"共 {len(event_list)} 条生效新闻/事件，整体{sentiment_label}；"
            f"高强度 {high_severity_count} 条，已核验 {verified_count} 条。"
        )
    else:
        overview = (
            f"{len(event_list)} active news/events; overall sentiment is {dominant}. "
            f"High-severity: {high_severity_count}, verified sources: {verified_count}."
        )

    scored = [_headline_score_breakdown(event) for event in event_list]
    ranked = sorted(scored, key=lambda detail: detail.total_score, reverse=True)
    top_details = ranked[:max(1, int(max_headlines))]
    top = [detail.headline for detail in top_details]
    theme_focuses = _build_theme_focuses(event_list, scored)
    focus_points = [
        item.summary_zh if lang == "zh" else item.summary_en
        for item in theme_focuses[:3]
    ]

    return NewsSummary(
        overview=overview,
        event_count=len(event_list),
        positive_count=positive_count,
        neutral_count=neutral_count,
        negative_count=negative_count,
        dominant_sentiment=dominant,
        high_severity_count=high_severity_count,
        verified_count=verified_count,
        top_headlines=top,
        top_headline_details=top_details,
        focus_points=focus_points,
        theme_focuses=theme_focuses,
    )
