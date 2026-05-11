import json
import os
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, Optional, Tuple

from quant_core import paths as qpaths


qpaths.bootstrap_storage_paths()

ANALYST_CONSENSUS_CACHE_FILE = qpaths.ANALYST_CONSENSUS_CACHE_FILE
DEFAULT_CONSENSUS_THRESHOLD = 0.90
DEFAULT_MIN_ANALYST_COUNT = 5
DEFAULT_MAX_CACHE_AGE_DAYS = 7
DEFAULT_ETF_PROXY_MIN_COVERAGE_RATIO = 0.50
DEFAULT_ETF_PROXY_MAX_HOLDINGS = 10
DEFAULT_CONSENSUS_TILT_THRESHOLD = 0.60


def _now_iso(now=None):
    return (now or datetime.now()).isoformat()


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _coerce_count(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _coerce_ratio(value) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(ratio, 0.0), 1.0)


def _coerce_weight(value) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return 0.0
    if weight > 1.0 and weight <= 100.0:
        weight = weight / 100.0
    return min(max(weight, 0.0), 1.0)


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
        "symbol": _normalize_symbol(symbol),
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


def fetch_yfinance_top_holdings(symbol: str, max_holdings: int = DEFAULT_ETF_PROXY_MAX_HOLDINGS):
    import yfinance as yf

    ticker = yf.Ticker(_normalize_symbol(symbol))
    funds_data = getattr(ticker, "funds_data", None)
    top_holdings = getattr(funds_data, "top_holdings", None) if funds_data is not None else None
    if top_holdings is None or getattr(top_holdings, "empty", True):
        return []

    holdings = []
    rows = top_holdings.reset_index().head(int(max_holdings)).to_dict("records")
    for row in rows:
        holding_symbol = _normalize_symbol(row.get("Symbol") or row.get("symbol"))
        if not holding_symbol:
            continue
        holdings.append(
            {
                "symbol": holding_symbol,
                "name": str(row.get("Name") or row.get("name") or "").strip(),
                "holding_percent": _coerce_weight(
                    row.get("Holding Percent", row.get("holding_percent", row.get("weight")))
                ),
            }
        )
    return holdings


def _is_component_record_usable(record: Optional[Dict], min_analyst_count: int) -> bool:
    if not isinstance(record, dict):
        return False
    return _coerce_count(record.get("total")) >= int(min_analyst_count)


def build_etf_proxy_consensus_record(
    symbol: str,
    holdings,
    component_records: Dict[str, Dict],
    *,
    retrieved_at: Optional[str] = None,
    source: str = "etf_proxy_holdings",
    threshold: float = DEFAULT_CONSENSUS_THRESHOLD,
    min_analyst_count: int = DEFAULT_MIN_ANALYST_COUNT,
    min_coverage_ratio: float = DEFAULT_ETF_PROXY_MIN_COVERAGE_RATIO,
) -> Optional[Dict]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_holdings = []
    for item in holdings or []:
        if not isinstance(item, dict):
            continue
        component_symbol = _normalize_symbol(item.get("symbol") or item.get("Symbol"))
        if not component_symbol or component_symbol == normalized_symbol:
            continue
        weight = _coerce_weight(
            item.get("holding_percent", item.get("Holding Percent", item.get("weight")))
        )
        if weight <= 0:
            continue
        normalized_holdings.append(
            {
                "symbol": component_symbol,
                "holding_percent": weight,
                "name": str(item.get("name") or item.get("Name") or "").strip(),
            }
        )

    if not normalized_holdings:
        return None

    total_holdings = len(normalized_holdings)
    visible_weight = sum(item["holding_percent"] for item in normalized_holdings)
    coverage_denominator = max(1.0, visible_weight)
    covered_weight = 0.0
    bullish_weight = 0.0
    bearish_weight = 0.0
    analyst_sample_total = 0
    covered_holdings = 0
    component_symbols = []

    for item in normalized_holdings:
        record = component_records.get(item["symbol"])
        if not _is_component_record_usable(record, min_analyst_count):
            continue
        weight = item["holding_percent"]
        covered_holdings += 1
        covered_weight += weight
        analyst_sample_total += _coerce_count(record.get("total"))
        bullish_weight += weight * _coerce_ratio(record.get("bullish_ratio"))
        bearish_weight += weight * _coerce_ratio(record.get("bearish_ratio"))
        component_symbols.append(item["symbol"])

    coverage_ratio = covered_weight / coverage_denominator if coverage_denominator else 0.0
    bullish_ratio = bullish_weight / covered_weight if covered_weight else 0.0
    bearish_ratio = bearish_weight / covered_weight if covered_weight else 0.0
    sample_display = f"{covered_holdings}/{total_holdings} 成分股"

    signal = "NEUTRAL"
    if coverage_ratio < float(min_coverage_ratio):
        reason = (
            f"ETF 持仓代理覆盖不足：仅覆盖 {coverage_ratio:.1%} 权重"
            f"（{sample_display}），不使用 ETF 代理意见。"
        )
    elif bullish_ratio >= float(threshold):
        signal = "STRONG_BUY"
        reason = (
            f"ETF 持仓代理共识：在已覆盖 {coverage_ratio:.1%} 权重内，"
            f"看多 {bullish_ratio:.1%}，基于 {sample_display}。"
        )
    elif bearish_ratio >= float(threshold):
        signal = "STRONG_SELL"
        reason = (
            f"ETF 持仓代理共识：在已覆盖 {coverage_ratio:.1%} 权重内，"
            f"看空 {bearish_ratio:.1%}，基于 {sample_display}。"
        )
    else:
        reason = (
            f"ETF 持仓代理未达阈值：覆盖 {coverage_ratio:.1%} 权重，"
            f"看多 {bullish_ratio:.1%}、看空 {bearish_ratio:.1%}，基于 {sample_display}。"
        )

    return {
        "symbol": normalized_symbol,
        "period": "proxy",
        "source": source,
        "retrieved_at": retrieved_at or _now_iso(),
        "strong_buy": 0,
        "buy": 0,
        "hold": 0,
        "sell": 0,
        "strong_sell": 0,
        "total": analyst_sample_total,
        "bullish_count": 0,
        "bearish_count": 0,
        "bullish_ratio": bullish_ratio,
        "bearish_ratio": bearish_ratio,
        "signal": signal,
        "reason": reason,
        "covered_holdings": covered_holdings,
        "total_holdings": total_holdings,
        "covered_weight": covered_weight,
        "visible_weight": visible_weight,
        "coverage_ratio": coverage_ratio,
        "sample_display": sample_display,
        "component_symbols": component_symbols,
    }


def summarize_consensus_status(
    record: Optional[Dict],
    *,
    now: Optional[datetime] = None,
    tilt_threshold: float = DEFAULT_CONSENSUS_TILT_THRESHOLD,
    min_analyst_count: int = DEFAULT_MIN_ANALYST_COUNT,
    min_coverage_ratio: float = DEFAULT_ETF_PROXY_MIN_COVERAGE_RATIO,
) -> Dict[str, object]:
    default_summary = {
        "status": "无数据",
        "reason": "暂无分析师共识数据。",
        "bullish_display": "—",
        "bearish_display": "—",
        "sample_display": "—",
        "is_proxy": False,
        "source": "",
    }
    if not isinstance(record, dict):
        return default_summary

    source = str(record.get("source") or "")
    is_proxy = source == "etf_proxy_holdings"
    prefix = "ETF代理" if is_proxy else ""
    bullish_ratio = record.get("bullish_ratio")
    bearish_ratio = record.get("bearish_ratio")
    bullish_display = "—" if bullish_ratio is None else f"{float(bullish_ratio):.1%}"
    bearish_display = "—" if bearish_ratio is None else f"{float(bearish_ratio):.1%}"
    sample_value = record.get("sample_display", record.get("total"))
    sample_display = "—" if sample_value in (None, "") else str(sample_value)
    raw_signal = str(record.get("signal") or "").upper()
    reason = str(record.get("reason") or "暂无分析师共识数据。")

    if not is_cached_consensus_fresh(record, now=now):
        return {
            "status": "已过期",
            "reason": "分析师共识缓存已过期（超过 7 天），不参与当前提示。",
            "bullish_display": bullish_display,
            "bearish_display": bearish_display,
            "sample_display": sample_display,
            "is_proxy": is_proxy,
            "source": source,
        }

    if raw_signal == "STRONG_BUY":
        status = f"{prefix}强烈看多"
    elif raw_signal == "STRONG_SELL":
        status = f"{prefix}强烈看空"
    else:
        coverage_ratio = float(record.get("coverage_ratio") or 0.0)
        total = _coerce_count(record.get("total"))
        bullish_value = float(bullish_ratio or 0.0)
        bearish_value = float(bearish_ratio or 0.0)
        if is_proxy and coverage_ratio < float(min_coverage_ratio):
            status = f"{prefix}覆盖不足"
        elif (not is_proxy) and total < int(min_analyst_count):
            status = "样本不足"
        elif bullish_value >= float(tilt_threshold) and bullish_value > bearish_value:
            status = f"{prefix}偏多"
        elif bearish_value >= float(tilt_threshold) and bearish_value > bullish_value:
            status = f"{prefix}偏空"
        else:
            status = f"{prefix}中性"

    return {
        "status": status,
        "reason": reason,
        "bullish_display": bullish_display,
        "bearish_display": bearish_display,
        "sample_display": sample_display,
        "is_proxy": is_proxy,
        "source": source,
    }


def _fetch_consensus_record_with_etf_proxy(
    symbol: str,
    *,
    retrieved_at: str,
    fetcher: Callable[[str], object],
    holdings_fetcher: Callable[[str], object],
    fetched_records: Dict[str, Optional[Dict]],
    threshold: float = DEFAULT_CONSENSUS_THRESHOLD,
    min_analyst_count: int = DEFAULT_MIN_ANALYST_COUNT,
    min_coverage_ratio: float = DEFAULT_ETF_PROXY_MIN_COVERAGE_RATIO,
) -> Optional[Dict]:
    normalized_symbol = _normalize_symbol(symbol)
    if normalized_symbol in fetched_records:
        return fetched_records[normalized_symbol]

    row = fetcher(normalized_symbol)
    record = build_consensus_record(
        normalized_symbol,
        row,
        retrieved_at=retrieved_at,
        threshold=threshold,
        min_analyst_count=min_analyst_count,
    )
    if record is not None:
        fetched_records[normalized_symbol] = record
        return record

    holdings = holdings_fetcher(normalized_symbol)
    component_records = {}
    for item in holdings or []:
        component_symbol = _normalize_symbol(item.get("symbol") if isinstance(item, dict) else None)
        if not component_symbol or component_symbol == normalized_symbol:
            continue
        if component_symbol not in fetched_records:
            component_row = fetcher(component_symbol)
            fetched_records[component_symbol] = build_consensus_record(
                component_symbol,
                component_row,
                retrieved_at=retrieved_at,
                threshold=threshold,
                min_analyst_count=min_analyst_count,
            )
        component_records[component_symbol] = fetched_records.get(component_symbol)

    proxy_record = build_etf_proxy_consensus_record(
        normalized_symbol,
        holdings,
        component_records,
        retrieved_at=retrieved_at,
        threshold=threshold,
        min_analyst_count=min_analyst_count,
        min_coverage_ratio=min_coverage_ratio,
    )
    fetched_records[normalized_symbol] = proxy_record
    return proxy_record


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
    holdings_fetcher: Optional[Callable[[str], object]] = None,
) -> Tuple[bool, str]:
    now = now or datetime.now()
    fetcher = fetcher or fetch_yfinance_recommendation_row
    holdings_fetcher = holdings_fetcher or fetch_yfinance_top_holdings
    retrieved_at = now.isoformat()
    unique_symbols = sorted({_normalize_symbol(symbol) for symbol in symbols or [] if _normalize_symbol(symbol)})
    if not unique_symbols:
        return False, "没有可抓取分析师共识的标的"

    cache = load_analyst_consensus_cache(cache_path)
    recommendations = dict(cache.get("recommendations", {}))
    errors = {}
    success_count = 0
    failure_count = 0
    fetched_records: Dict[str, Optional[Dict]] = {}

    for symbol in unique_symbols:
        try:
            record = _fetch_consensus_record_with_etf_proxy(
                symbol,
                retrieved_at=retrieved_at,
                fetcher=fetcher,
                holdings_fetcher=holdings_fetcher,
                fetched_records=fetched_records,
            )
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
    return recommendations.get(_normalize_symbol(symbol))


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
