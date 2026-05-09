from dataclasses import dataclass, field
from typing import Iterable, List


_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_SENTIMENT_WEIGHT = {"negative": 2, "neutral": 1, "positive": 0}


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
        sentiment_label = {"negative": "偏负面", "neutral": "中性", "positive": "偏正面"}[dominant]
        overview = (
            f"共 {len(event_list)} 条生效新闻/事件，情绪整体{sentiment_label}；"
            f"高强度事件 {high_severity_count} 条，已核验来源 {verified_count} 条。"
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
    )
