import json
import os
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, Optional, Tuple


ANALYST_CONSENSUS_CACHE_FILE = "analyst_consensus_cache.json"
DEFAULT_CONSENSUS_THRESHOLD = 0.90
DEFAULT_MIN_ANALYST_COUNT = 5
DEFAULT_MAX_CACHE_AGE_DAYS = 7


def _now_iso(now=None):
    return (now or datetime.now()).isoformat()


def _coerce_count(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _get_count(row: Dict, *names) -> int:
    for name in names:
        if name in row:
            return _coerce_count(row.get(name))
    return 0


def _row_to_dict(row) -> Optional[Dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "to_dict"):
        return row.to_dict()
    return None


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def analyst_cycle_key_for_timestamp(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    cycle_day = now.date() if now.hour == 23 else (now - timedelta(days=1)).date()
    return cycle_day.isoformat()


def is_nightly_consensus_window(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return now.hour in (23, 0)


def build_consensus_record(
    symbol: str,
    row,
    *,
    retrieved_at: Optional[str] = None,
    source: str = "yfinance",
    threshold: float = DEFAULT_CONSENSUS_THRESHOLD,
    min_analyst_count: int = DEFAULT_MIN_ANALYST_COUNT,
) -> Optional[Dict]:
    row_dict = _row_to_dict(row)
    if not row_dict:
        return None

    strong_buy = _get_count(row_dict, "strongBuy", "strong_buy", "strong buy")
    buy = _get_count(row_dict, "buy")
    hold = _get_count(row_dict, "hold")
    sell = _get_count(row_dict, "sell")
    strong_sell = _get_count(row_dict, "strongSell", "strong_sell", "strong sell")
    total = strong_buy + buy + hold + sell + strong_sell
    bullish_count = strong_buy + buy
    bearish_count = sell + strong_sell
    bullish_ratio = bullish_count / total if total else 0.0
    bearish_ratio = bearish_count / total if total else 0.0

    signal = "NEUTRAL"
    if total < int(min_analyst_count):
        reason = f"分析师样本不足：{total}/{int(min_analyst_count)}，不使用分析师意见。"
    elif bullish_ratio >= float(threshold):
        signal = "STRONG_BUY"
        reason = f"分析师共识：{bullish_ratio:.1%} 看多 ({bullish_count}/{total})，触发强烈买入。"
    elif bearish_ratio >= float(threshold):
        signal = "STRONG_SELL"
        reason = f"分析师共识：{bearish_ratio:.1%} 看空 ({bearish_count}/{total})，触发强烈卖出。"
    else:
        reason = (
            f"分析师共识未达阈值：看多 {bullish_ratio:.1%}、看空 {bearish_ratio:.1%}，"
            "不使用分析师意见。"
        )

    return {
        "symbol": str(symbol or "").strip().upper(),
        "period": str(row_dict.get("period") or ""),
        "source": source,
        "retrieved_at": retrieved_at or _now_iso(),
        "strong_buy": strong_buy,
        "buy": buy,
        "hold": hold,
        "sell": sell,
        "strong_sell": strong_sell,
        "total": total,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "bullish_ratio": bullish_ratio,
        "bearish_ratio": bearish_ratio,
        "signal": signal,
        "reason": reason,
    }


def fetch_yfinance_recommendation_row(symbol: str):
    import yfinance as yf

    ticker = yf.Ticker(str(symbol).strip().upper())
    recommendations = None
    if hasattr(ticker, "get_recommendations"):
        try:
            recommendations = ticker.get_recommendations(as_dict=False)
        except TypeError:
            recommendations = ticker.get_recommendations()
        except Exception:
            recommendations = None
    if recommendations is None:
        try:
            recommendations = getattr(ticker, "recommendations", None)
        except Exception:
            recommendations = None
    if recommendations is None or getattr(recommendations, "empty", False):
        return None

    if hasattr(recommendations, "iterrows"):
        current_rows = recommendations[recommendations.get("period") == "0m"] if "period" in recommendations else None
        if current_rows is not None and not current_rows.empty:
            return current_rows.iloc[0]
        return recommendations.iloc[0]
    if isinstance(recommendations, list) and recommendations:
        return recommendations[0]
    return None


def load_analyst_consensus_cache(cache_path: str = ANALYST_CONSENSUS_CACHE_FILE) -> Dict:
    if not cache_path or not os.path.exists(cache_path):
        return {"recommendations": {}, "errors": {}, "last_updated": None, "last_cycle_key": None}
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            cache = json.load(handle)
    except Exception:
        return {"recommendations": {}, "errors": {}, "last_updated": None, "last_cycle_key": None}
    if not isinstance(cache, dict):
        return {"recommendations": {}, "errors": {}, "last_updated": None, "last_cycle_key": None}
    cache.setdefault("recommendations", {})
    cache.setdefault("errors", {})
    cache.setdefault("last_updated", None)
    cache.setdefault("last_cycle_key", None)
    return cache


def save_analyst_consensus_cache(cache: Dict, cache_path: str = ANALYST_CONSENSUS_CACHE_FILE):
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def should_run_nightly_consensus_update(
    *,
    now: Optional[datetime] = None,
    cache_path: str = ANALYST_CONSENSUS_CACHE_FILE,
) -> bool:
    now = now or datetime.now()
    if not is_nightly_consensus_window(now):
        return False
    cache = load_analyst_consensus_cache(cache_path)
    return cache.get("last_cycle_key") != analyst_cycle_key_for_timestamp(now)


def refresh_analyst_consensus_cache(
    symbols: Iterable[str],
    *,
    cache_path: str = ANALYST_CONSENSUS_CACHE_FILE,
    now: Optional[datetime] = None,
    fetcher: Optional[Callable[[str], object]] = None,
) -> Tuple[bool, str]:
    now = now or datetime.now()
    fetcher = fetcher or fetch_yfinance_recommendation_row
    retrieved_at = now.isoformat()
    unique_symbols = sorted({str(symbol).strip().upper() for symbol in symbols or [] if str(symbol or "").strip()})
    if not unique_symbols:
        return False, "没有可抓取分析师共识的标的"

    cache = load_analyst_consensus_cache(cache_path)
    recommendations = dict(cache.get("recommendations", {}))
    errors = {}
    success_count = 0
    failure_count = 0

    for symbol in unique_symbols:
        try:
            row = fetcher(symbol)
            record = build_consensus_record(symbol, row, retrieved_at=retrieved_at)
            if record is None:
                failure_count += 1
                errors[symbol] = "无分析师推荐数据"
                continue
            recommendations[symbol] = record
            success_count += 1
        except Exception as exc:
            failure_count += 1
            errors[symbol] = str(exc)

    cache = {
        "last_updated": retrieved_at,
        "last_cycle_key": analyst_cycle_key_for_timestamp(now),
        "recommendations": recommendations,
        "errors": errors,
    }
    save_analyst_consensus_cache(cache, cache_path)
    return True, f"分析师共识夜间抓取完成: 成功 {success_count}, 失败 {failure_count}"


def get_cached_analyst_consensus(symbol: str, cache: Optional[Dict]) -> Optional[Dict]:
    if not isinstance(cache, dict):
        return None
    recommendations = cache.get("recommendations", cache)
    if not isinstance(recommendations, dict):
        return None
    return recommendations.get(str(symbol or "").strip().upper())


def is_cached_consensus_fresh(record: Dict, *, now: Optional[datetime] = None, max_age_days: int = DEFAULT_MAX_CACHE_AGE_DAYS) -> bool:
    if not isinstance(record, dict):
        return False
    retrieved_at = _parse_iso_datetime(record.get("retrieved_at"))
    if retrieved_at is None:
        return False
    now = now or datetime.now()
    return (now - retrieved_at) <= timedelta(days=int(max_age_days))


def apply_analyst_consensus_to_signal(
    base_signal: str,
    base_reason: str,
    consensus_record: Optional[Dict],
    *,
    now: Optional[datetime] = None,
) -> Tuple[str, str]:
    if not is_cached_consensus_fresh(consensus_record or {}, now=now):
        return base_signal, base_reason

    consensus_signal = str(consensus_record.get("signal") or "").upper()
    if consensus_signal not in ("STRONG_BUY", "STRONG_SELL"):
        return base_signal, base_reason
    return consensus_signal, str(consensus_record.get("reason") or base_reason)
