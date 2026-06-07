from __future__ import annotations

from copy import deepcopy
from typing import Mapping, Optional

from quant_core.analytics import core_etf_rotation as cer


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


def _price_component(row: Mapping) -> float:
    score = 0.0
    ret_3m = _safe_float(row.get("return_3m"))
    ret_6m = _safe_float(row.get("return_6m"))
    ret_12m = _safe_float(row.get("return_12m"))
    high_proximity = _safe_float(row.get("high_proximity"))
    if ret_3m is not None:
        score += _clamp(ret_3m * 60.0, -10.0, 12.0)
    if ret_6m is not None:
        score += _clamp(ret_6m * 45.0, -8.0, 10.0)
    if ret_12m is not None:
        score += _clamp(ret_12m * 30.0, -5.0, 6.0)
    if high_proximity is not None and high_proximity >= 0.95:
        score += _clamp((high_proximity - 0.95) * 200.0, 0.0, 4.0)
    return _clamp(score, -12.0, 30.0)


def _model_component(row: Mapping) -> float:
    score = 0.0
    signal = str(row.get("signal") or "HOLD").strip().upper()
    if "BUY" in signal:
        score += 5.0
    elif "SELL" in signal:
        score -= 6.0

    monte_carlo = dict(row.get("monte_carlo") or {})
    mc_expected = _safe_float(monte_carlo.get("expected_return"))
    mc_positive = _safe_float(monte_carlo.get("positive_probability"))
    if mc_expected is not None:
        score += _clamp(mc_expected * 120.0, -6.0, 8.0)
    if mc_positive is not None:
        score += _clamp((mc_positive - 0.5) * 25.0, -4.0, 5.0)

    tcn = dict(row.get("tcn_profile") or {})
    tcn_prob = _safe_float(tcn.get("probability"))
    tcn_expected = _safe_float(tcn.get("expected_return_pct"))
    if tcn_prob is not None:
        score += _clamp((tcn_prob - 0.5) * 30.0, -5.0, 6.0)
    if tcn_expected is not None:
        score += _clamp(tcn_expected * 80.0, -4.0, 6.0)
    return _clamp(score, -15.0, 25.0)


def _backtest_component(row: Mapping) -> float:
    backtest = dict(row.get("backtest") or {})
    score = 0.0
    total_return = _safe_float(backtest.get("total_return"))
    sharpe = _safe_float(backtest.get("sharpe_ratio"))
    win_rate = _safe_float(backtest.get("win_rate"))
    if total_return is not None:
        score += _clamp(total_return * 70.0, -6.0, 8.0)
    if sharpe is not None:
        score += _clamp(sharpe * 3.0, -4.0, 4.0)
    if win_rate is not None:
        score += _clamp((win_rate - 0.5) * 16.0, -3.0, 3.0)
    return _clamp(score, -12.0, 15.0)


def _risk_penalty(row: Mapping) -> float:
    penalty = 0.0
    volatility = _safe_float(row.get("volatility"))
    drawdown = _safe_float(row.get("max_drawdown"))
    ret_3m = _safe_float(row.get("return_3m"))
    high_proximity = _safe_float(row.get("high_proximity"))
    if volatility is not None:
        penalty += _clamp(volatility * 15.0, 0.0, 8.0)
    if drawdown is not None and drawdown < 0:
        penalty += _clamp(abs(drawdown) * 25.0, 0.0, 8.0)
    if ret_3m is not None and ret_3m > 0.35 and high_proximity is not None and high_proximity > 0.995:
        penalty += 6.0
    if row.get("error"):
        penalty += 10.0
    return _clamp(penalty, 0.0, 20.0)


def _status_from_score(row: Mapping, *, score: float, policy: Mapping, discipline_snapshot: Optional[Mapping]):
    signal = str(row.get("signal") or "HOLD").strip().upper()
    entry_threshold = float(policy.get("candidate_entry_threshold", 65.0) or 65.0)
    exit_threshold = float(policy.get("candidate_exit_threshold", 45.0) or 45.0)
    high_proximity = _safe_float(row.get("high_proximity"))
    ret_3m = _safe_float(row.get("return_3m"))
    can_open = bool((discipline_snapshot or {}).get("can_open_new_satellite_positions", True))

    if row.get("error"):
        return "BROKEN", "WATCH", "深度分析失败，保留观察。"
    if "SELL" in signal or score < exit_threshold:
        return "BROKEN", "WATCH", "趋势或模型确认偏弱，暂不建议建仓。"
    if high_proximity is not None and ret_3m is not None and high_proximity > 0.995 and ret_3m > 0.35:
        if score >= entry_threshold + 10.0 and "BUY" in signal:
            return "OVERHEATED_CONFIRMED", "WATCH", "趋势非常强，但位置已经过热，暂不追价。"
        return "OVERHEATED", "WATCH", "短期过热，等待回调更稳妥。"
    if score >= entry_threshold + 10.0 and "BUY" in signal:
        if can_open:
            return "CONFIRMED", "ACCUMULATE", "趋势、模型与回测共同确认，可作为重点卫星仓。"
        return "CONFIRMED", "WATCH", "趋势确认，但纪律层当前不允许新开卫星仓。"
    if score >= entry_threshold and "BUY" in signal:
        if can_open:
            return "PROBE", "PROBE", "趋势开始确认，适合小仓试探。"
        return "PROBE", "WATCH", "趋势在改善，但纪律层当前不允许新开卫星仓。"
    return "WATCH", "WATCH", "维持观察，等待更强的确认信号。"


def rank_satellite_candidates(
    snapshot: Mapping,
    *,
    policy: Optional[Mapping] = None,
    discipline_snapshot: Optional[Mapping] = None,
    previous_snapshot: Optional[Mapping] = None,
    max_recommendations: Optional[int] = None,
) -> dict:
    policy = cer.normalize_engine_policy(policy or cer.load_engine_policy())
    snapshot = deepcopy(dict(snapshot or {}))
    previous_rows = {
        str((row or {}).get("symbol") or "").strip().upper(): dict(row or {})
        for row in list((previous_snapshot or {}).get("symbols", []) or [])
        if (row or {}).get("symbol")
    }
    previous_top_symbols = {
        str((row or {}).get("symbol") or "").strip().upper()
        for row in list((previous_snapshot or {}).get("top_recommendations", []) or [])
        if (row or {}).get("symbol")
    }
    promotion_days_required = int(policy.get("top3_promotion_confirmation_days", 2) or 2)
    demotion_days_required = int(policy.get("top3_demotion_confirmation_days", 2) or 2)
    minimum_top3_residency_days = int(policy.get("minimum_top3_residency_days", 2) or 2)
    symbols = []
    for row in list(snapshot.get("symbols", []) or []):
        row = dict(row or {})
        previous_row = previous_rows.get(str(row.get("symbol") or "").strip().upper(), {})
        price_score = _price_component(row)
        model_score = _model_component(row)
        backtest_score = _backtest_component(row)
        penalty = _risk_penalty(row)
        total_score = _clamp(price_score + model_score + backtest_score - penalty + 35.0, 0.0, 100.0)
        status, plan_action, reason = _status_from_score(
            row,
            score=total_score,
            policy=policy,
            discipline_snapshot=discipline_snapshot,
        )
        suggested_weight_pct = 0.0
        if plan_action == "ACCUMULATE":
            suggested_weight_pct = min(
                float(policy.get("satellite_max_single_weight_pct", 5.0) or 5.0),
                2.0 + ((total_score - 75.0) / 10.0),
            )
        elif plan_action == "PROBE":
            suggested_weight_pct = min(
                float(policy.get("satellite_max_single_weight_pct", 5.0) or 5.0),
                1.0 + ((total_score - 65.0) / 20.0),
            )
        current_status = str(status or "WATCH").strip().upper()
        previous_status = str(previous_row.get("recommendation_status") or "").strip().upper()
        status_unchanged_days = int(_safe_float(previous_row.get("status_unchanged_days"), 0) or 0) + 1 if previous_status == current_status else 1
        was_top3 = str(row.get("symbol") or "").strip().upper() in previous_top_symbols
        previous_top_days = int(_safe_float(previous_row.get("top3_residency_days"), 0) or 0) if was_top3 else 0
        candidate_strong = current_status in {"CONFIRMED", "PROBE", "OVERHEATED_CONFIRMED"}
        promotion_support_days = (
            int(_safe_float(previous_row.get("promotion_support_days"), 0) or 0) + 1
            if candidate_strong
            else 0
        )
        candidate_weak = current_status in {"WATCH", "OVERHEATED"}
        demotion_support_days = (
            int(_safe_float(previous_row.get("demotion_support_days"), 0) or 0) + 1
            if candidate_weak or current_status == "BROKEN"
            else 0
        )
        row.update(
            {
                "satellite_score": round(total_score, 4),
                "score_components": {
                    "price": round(price_score, 4),
                    "model": round(model_score, 4),
                    "backtest": round(backtest_score, 4),
                    "risk_penalty": round(penalty, 4),
                },
                "recommendation_status": status,
                "plan_action": plan_action,
                "recommendation_reason": reason,
                "suggested_weight_pct": round(max(suggested_weight_pct, 0.0), 4),
                "status_unchanged_days": status_unchanged_days,
                "promotion_support_days": promotion_support_days,
                "demotion_support_days": demotion_support_days,
                "top3_residency_days": previous_top_days,
            }
        )
        symbols.append(row)

    symbols.sort(
        key=lambda row: (
            {"CONFIRMED": 0, "OVERHEATED_CONFIRMED": 1, "PROBE": 2, "WATCH": 3, "OVERHEATED": 4, "BROKEN": 5}.get(
                str(row.get("recommendation_status") or "WATCH"), 9
            ),
            -float(row.get("satellite_score") or 0.0),
            row.get("symbol", ""),
        )
    )
    snapshot["symbols"] = symbols

    recommendation_limit = int(
        max_recommendations
        if max_recommendations is not None
        else snapshot.get("max_recommendations", policy.get("max_recommendations", 3) or 3)
    )
    top_rows = []
    retained_symbols = set()
    for row in symbols:
        symbol = str(row.get("symbol") or "").strip().upper()
        status = str(row.get("recommendation_status") or "").strip().upper()
        if symbol not in previous_top_symbols:
            continue
        demotion_ready = bool(
            status == "BROKEN"
            or (
                row.get("demotion_support_days", 0) >= demotion_days_required
                and row.get("top3_residency_days", 0) >= minimum_top3_residency_days
            )
        )
        if demotion_ready:
            row["top3_membership_state"] = "DEMOTED"
            row["top3_residency_days"] = 0
            continue
        row["top3_membership_state"] = "RETAINED"
        row["top3_residency_days"] = int(_safe_float(row.get("top3_residency_days"), 0) or 0) + 1
        top_rows.append(row)
        retained_symbols.add(symbol)
        if len(top_rows) >= max(0, recommendation_limit):
            break

    for row in symbols:
        if len(top_rows) >= max(0, recommendation_limit):
            break
        symbol = str(row.get("symbol") or "").strip().upper()
        status = str(row.get("recommendation_status") or "").strip().upper()
        if symbol in retained_symbols or status == "BROKEN":
            continue
        if symbol in previous_top_symbols:
            continue
        promotion_ready = status in {"CONFIRMED", "PROBE", "OVERHEATED_CONFIRMED"} and (
            row.get("promotion_support_days", 0) >= promotion_days_required
        )
        if not previous_top_symbols and status in {"CONFIRMED", "PROBE", "OVERHEATED_CONFIRMED"}:
            promotion_ready = True
        if not promotion_ready:
            row["top3_membership_state"] = "PENDING_PROMOTION"
            row["top3_residency_days"] = 0
            continue
        row["top3_membership_state"] = "INITIAL" if not previous_top_symbols else "PROMOTED"
        row["top3_residency_days"] = 1
        top_rows.append(row)

    snapshot["top_recommendations"] = top_rows
    snapshot.setdefault("summary", {})
    snapshot["summary"].update(
        {
            "top_symbols": [row.get("symbol") for row in top_rows],
            "top_recommendation_count": len(top_rows),
            "confirmed_count": sum(
                1 for row in symbols if str(row.get("recommendation_status") or "").upper() == "CONFIRMED"
            ),
            "probe_count": sum(
                1 for row in symbols if str(row.get("recommendation_status") or "").upper() == "PROBE"
            ),
            "watch_count": sum(
                1 for row in symbols if str(row.get("recommendation_status") or "").upper() == "WATCH"
            ),
            "overheated_count": sum(
                1 for row in symbols if str(row.get("recommendation_status") or "").upper() == "OVERHEATED"
            ),
            "overheated_confirmed_count": sum(
                1 for row in symbols if str(row.get("recommendation_status") or "").upper() == "OVERHEATED_CONFIRMED"
            ),
            "broken_count": sum(
                1 for row in symbols if str(row.get("recommendation_status") or "").upper() == "BROKEN"
            ),
        }
    )
    return snapshot
