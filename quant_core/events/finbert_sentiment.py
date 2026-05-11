from typing import Dict, Optional


DEFAULT_FINBERT_MODEL = "ProsusAI/finbert"

_FINBERT_PIPELINE = None
_FINBERT_MODEL_NAME = None
_FINBERT_LOAD_ERROR = None


_POSITIVE_HINTS = [
    "beat",
    "beats",
    "raised guidance",
    "raise guidance",
    "upgraded",
    "strong demand",
    "record revenue",
    "profit growth",
    "surge",
    "bullish",
]

_NEGATIVE_HINTS = [
    "miss",
    "misses",
    "cut guidance",
    "downgraded",
    "weak demand",
    "lawsuit",
    "investigation",
    "profit warning",
    "plunge",
    "bearish",
]


def _normalize_label(raw_label: str) -> str:
    label = str(raw_label or "").strip().lower()
    if label in ("positive", "negative", "neutral"):
        return label
    if "pos" in label:
        return "positive"
    if "neg" in label:
        return "negative"
    return "neutral"


def _keyword_sentiment(text: str) -> Dict[str, float]:
    normalized = str(text or "").lower()
    positive_hits = sum(1 for token in _POSITIVE_HINTS if token in normalized)
    negative_hits = sum(1 for token in _NEGATIVE_HINTS if token in normalized)
    if positive_hits == 0 and negative_hits == 0:
        return {
            "label": "neutral",
            "score": 0.55,
            "positive": 0.20,
            "neutral": 0.55,
            "negative": 0.25,
            "method": "keyword",
            "model": "keyword-fallback",
        }
    if positive_hits >= negative_hits:
        confidence = min(0.95, 0.55 + 0.1 * (positive_hits - negative_hits + 1))
        negative = max(0.02, (1.0 - confidence) * 0.35)
        neutral = 1.0 - confidence - negative
        return {
            "label": "positive",
            "score": confidence,
            "positive": confidence,
            "neutral": max(neutral, 0.02),
            "negative": max(negative, 0.02),
            "method": "keyword",
            "model": "keyword-fallback",
        }
    confidence = min(0.95, 0.55 + 0.1 * (negative_hits - positive_hits + 1))
    positive = max(0.02, (1.0 - confidence) * 0.35)
    neutral = 1.0 - confidence - positive
    return {
        "label": "negative",
        "score": confidence,
        "positive": max(positive, 0.02),
        "neutral": max(neutral, 0.02),
        "negative": confidence,
        "method": "keyword",
        "model": "keyword-fallback",
    }


def _get_finbert_pipeline(model_name: str):
    global _FINBERT_PIPELINE, _FINBERT_MODEL_NAME, _FINBERT_LOAD_ERROR
    if _FINBERT_PIPELINE is not None and _FINBERT_MODEL_NAME == model_name:
        return _FINBERT_PIPELINE
    try:
        from transformers import pipeline
        hf_logging = None
        try:
            from transformers.utils import logging as hf_logging
        except Exception:
            try:
                from transformers import logging as hf_logging
            except Exception:
                hf_logging = None

        if hf_logging is not None:
            try:
                hf_logging.set_verbosity_error()
            except Exception:
                pass
            try:
                hf_logging.disable_progress_bar()
            except Exception:
                pass

        _FINBERT_PIPELINE = pipeline("text-classification", model=model_name, tokenizer=model_name)
        _FINBERT_MODEL_NAME = model_name
        _FINBERT_LOAD_ERROR = None
        return _FINBERT_PIPELINE
    except Exception as exc:
        _FINBERT_PIPELINE = None
        _FINBERT_MODEL_NAME = model_name
        _FINBERT_LOAD_ERROR = str(exc)
        return None


def analyze_financial_sentiment(
    text: str,
    *,
    use_finbert: bool = True,
    model_name: str = DEFAULT_FINBERT_MODEL,
) -> Dict[str, Optional[float]]:
    if not text or not str(text).strip():
        return {
            "label": "neutral",
            "score": 0.5,
            "positive": 0.25,
            "neutral": 0.5,
            "negative": 0.25,
            "method": "empty",
            "model": "none",
        }

    if use_finbert:
        pipe = _get_finbert_pipeline(model_name)
        if pipe is not None:
            try:
                output = pipe(str(text))
                if isinstance(output, list):
                    output = output[0] if output else {}
                label = _normalize_label(output.get("label"))
                score = float(output.get("score", 0.5))
                remaining = max(0.0, 1.0 - score)
                if label == "positive":
                    probs = {"positive": score, "neutral": remaining * 0.7, "negative": remaining * 0.3}
                elif label == "negative":
                    probs = {"positive": remaining * 0.3, "neutral": remaining * 0.7, "negative": score}
                else:
                    probs = {"positive": remaining * 0.5, "neutral": score, "negative": remaining * 0.5}
                return {
                    "label": label,
                    "score": score,
                    "positive": probs["positive"],
                    "neutral": probs["neutral"],
                    "negative": probs["negative"],
                    "method": "finbert",
                    "model": model_name,
                }
            except Exception:
                pass

    result = _keyword_sentiment(str(text))
    if _FINBERT_LOAD_ERROR:
        result["fallback_reason"] = _FINBERT_LOAD_ERROR
    return result
