import pandas as pd
from datetime import datetime
from strategies import ui as su
from quant_core.events import analyst_consensus as ac
from quant_core.portfolio import allocation as ca
import deep_learning_strategy as dl_utils
from share_utils import format_share_quantity
from quant_core.portfolio.position import recommend_position_action
from signal_approval import approve_signal


def _consensus_display_fields(consensus, now=None):
    summary = ac.summarize_consensus_status(consensus, now=now)
    return {
        "分析师意见": summary["status"],
        "分析师看多": summary["bullish_display"],
        "分析师看空": summary["bearish_display"],
        "分析师样本": summary["sample_display"],
        "分析师说明": summary["reason"],
    }


def _resolve_signal_and_profile(strategy, symbol):
    if strategy is None:
        return "HOLD", "未选择策略，默认观望", None
    if str(strategy.get("id") or "") == "deep_tcn":
        profile = dl_utils.get_deep_tcn_signal_profile(symbol, **strategy.get("params", {}))
        return profile.signal, profile.reason, profile
    signal, reason = su.get_signal(strategy, symbol)
    return signal, reason, None


def _analysis_snapshot_map(analysis_snapshot):
    mapped = {}
    for row in list((analysis_snapshot or {}).get("symbols", []) or []):
        symbol = str((row or {}).get("symbol", "")).strip().upper()
        if symbol:
            mapped[symbol] = dict(row or {})
    return mapped


def _format_analysis_time(analysis_snapshot, analysis_row):
    if not analysis_row:
        return "—"
    raw_value = (analysis_row or {}).get("generated_at") or (analysis_snapshot or {}).get("generated_at")
    text = str(raw_value or "").strip()
    if not text:
        return "—"
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def _analysis_freshness_fields(analysis_snapshot, analysis_row, *, now=None):
    if not analysis_row:
        return {
            "display": "—",
            "label": "无数据",
            "color": "#6b7280",
        }
    raw_value = (analysis_row or {}).get("generated_at") or (analysis_snapshot or {}).get("generated_at")
    text = str(raw_value or "").strip()
    if not text:
        return {
            "display": "—",
            "label": "无数据",
            "color": "#6b7280",
        }
    now = now or datetime.now()
    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    display_text = _format_analysis_time(analysis_snapshot, analysis_row)
    if parsed is None:
        return {
            "display": display_text,
            "label": "未知",
            "color": "#6b7280",
        }
    age_hours = max((now - parsed).total_seconds(), 0.0) / 3600.0
    if age_hours > 48:
        return {
            "display": display_text,
            "label": "过期",
            "color": "#b91c1c",
        }
    if age_hours > 24:
        return {
            "display": display_text,
            "label": "偏旧",
            "color": "#b45309",
        }
    return {
        "display": display_text,
        "label": "新鲜",
        "color": "#0b7b44",
    }


def build_holdings_analysis_freshness_alert(holdings, analysis_snapshot, *, now=None):
    holdings = list(holdings or [])
    if not holdings:
        return None

    analysis_map = _analysis_snapshot_map(analysis_snapshot)
    expired_symbols = []
    missing_symbols = []
    stale_symbols = []
    fresh_symbols = []

    for holding in holdings:
        symbol = str((holding or {}).get("symbol", "")).strip().upper()
        if not symbol:
            continue
        analysis_row = analysis_map.get(symbol, {})
        freshness = _analysis_freshness_fields(analysis_snapshot, analysis_row, now=now)
        label = freshness["label"]
        if label == "过期":
            expired_symbols.append(symbol)
        elif label == "无数据":
            missing_symbols.append(symbol)
        elif label == "偏旧":
            stale_symbols.append(symbol)
        else:
            fresh_symbols.append(symbol)

    needs_warning = bool(expired_symbols or missing_symbols)
    if not needs_warning:
        return None

    return {
        "expired_symbols": expired_symbols,
        "missing_symbols": missing_symbols,
        "stale_symbols": stale_symbols,
        "fresh_symbols": fresh_symbols,
        "needs_warning": needs_warning,
    }


def _friendly_market_source_name(source_name):
    source = str(source_name or "").strip().lower()
    if source == "stooq":
        return "Stooq"
    if source == "yfinance":
        return "Yahoo"
    if not source:
        return "Unknown"
    return source


def build_manual_refresh_notice(data_source_status, tracked_symbol_count, *, lang="zh"):
    prices = dict((data_source_status or {}).get("prices", {}) or {})
    primary_source = _friendly_market_source_name(prices.get("primary_source"))
    source_order = [
        _friendly_market_source_name(source)
        for source in list(prices.get("source_order", []) or [])
        if str(source or "").strip()
    ]
    fallback_source = source_order[1] if len(source_order) > 1 else "备用源"
    primary_hits = int(prices.get("primary_symbols") or 0)
    fallback_hits = int(prices.get("fallback_symbols") or 0)
    total_symbols = max(int(tracked_symbol_count or 0), 0)
    unresolved = max(total_symbols - primary_hits - fallback_hits, 0)
    last_error = str(prices.get("last_error") or "").strip()

    if lang == "en":
        fragments = [
            f"Manual refresh checked {total_symbols} symbols.",
            f"Primary {primary_source} resolved {primary_hits}.",
            f"Fallback {fallback_source} resolved {fallback_hits}.",
        ]
        if unresolved > 0:
            fragments.append(f"{unresolved} symbols still have no fresh price.")
        if last_error:
            fragments.append(f"Latest source note: {last_error}")
    else:
        fragments = [
            f"本次强制刷新了 {total_symbols} 个标的。",
            f"主源 {primary_source} 命中 {primary_hits} 个。",
            f"回退到 {fallback_source} {fallback_hits} 个。",
        ]
        if unresolved > 0:
            fragments.append(f"仍有 {unresolved} 个标的未拿到最新价格。")
        if last_error:
            fragments.append(f"最近一次源返回提示：{last_error}")

    level = "warning" if unresolved > 0 else "success"
    return {
        "level": level,
        "message": " ".join(fragments),
        "primary_hits": primary_hits,
        "fallback_hits": fallback_hits,
        "unresolved_symbols": unresolved,
        "tracked_symbols": total_symbols,
        "primary_source": primary_source,
        "fallback_source": fallback_source,
    }


def build_trade_plan_banner(plan, *, lang="zh"):
    plan = dict(plan or {})
    has_actions = bool(plan.get("has_actions"))
    decision = str(plan.get("decision") or "").strip().upper()
    action_count = int(plan.get("action_count") or len(list(plan.get("items", []) or [])) or 0)
    blocked_count = int(plan.get("blocked_count") or len(list(plan.get("blocked_items", []) or [])) or 0)
    summary_reason = str(plan.get("summary_reason") or "").strip()
    plan_date = str(plan.get("plan_date") or "").strip()

    if lang == "en":
        if has_actions:
            message = f"Tomorrow has {action_count} planned actions."
            if blocked_count > 0:
                message += f" {blocked_count} additional entry actions were blocked by discipline rules."
            if plan_date:
                message += f" Plan date: {plan_date}."
            if summary_reason:
                message += f" {summary_reason}"
            return {
                "level": "success" if action_count <= 3 else "warning",
                "message": message.strip(),
            }
        message = "No trade actions for tomorrow. Hold current positions."
        if summary_reason:
            message += f" {summary_reason}"
        return {"level": "info", "message": message.strip()}

    if has_actions or decision == "ACTION":
        message = f"明日有 {action_count} 条交易动作。"
        if blocked_count > 0:
            message += f" 另有 {blocked_count} 条动作被纪律层压制。"
        if plan_date:
            message += f" 计划日期：{plan_date}。"
        if summary_reason:
            message += f" {summary_reason}"
        return {
            "level": "success" if action_count <= 3 else "warning",
            "message": message.strip(),
        }

    message = "明日无交易动作，建议持仓不动。"
    if summary_reason:
        message += f" {summary_reason}"
    return {"level": "info", "message": message.strip()}


def build_trade_plan_records(plan):
    records = []
    for item in list((plan or {}).get("items", []) or []):
        zone_low = item.get("buy_zone_low") if item.get("buy_zone_low") is not None else item.get("trim_zone_low")
        zone_high = item.get("buy_zone_high") if item.get("buy_zone_high") is not None else item.get("trim_zone_high")
        risk_break = (
            f"${float(item.get('risk_break_level')):,.2f}"
            if item.get("risk_break_level") is not None
            else "—"
        )
        invalid_condition = str(item.get("invalid_condition") or "").strip()
        guard_text = " | ".join(part for part in [risk_break if risk_break != "—" else "", invalid_condition] if part) or "—"
        records.append(
            {
                "代码": str(item.get("symbol") or "").strip().upper(),
                "动作": str(item.get("plan_action") or "").strip().upper(),
                "仓位": (
                    f"{float(item.get('plan_weight_delta_pct') or 0.0):+.1f}%"
                    if item.get("plan_weight_delta_pct") is not None
                    else "—"
                ),
                "计划区间": _format_price_range(
                    zone_low,
                    zone_high,
                ),
                "失效 / 破位": guard_text,
                "原因": str(item.get("reason") or "").strip(),
            }
        )
    return records


def build_execution_review_records(review):
    records = []
    for item in list((review or {}).get("items", []) or []):
        in_zone = item.get("executed_in_plan_zone")
        if in_zone is True:
            zone_text = "是"
        elif in_zone is False:
            zone_text = "否"
        else:
            zone_text = "—"
        opportunity_status = str(item.get("opportunity_status") or "").strip().upper()
        if opportunity_status == "EXECUTED":
            opportunity_text = "已执行"
        elif opportunity_status == "REACHABLE":
            opportunity_text = "触达未做"
        elif opportunity_status == "INVALIDATED":
            opportunity_text = "跳空失效"
        elif opportunity_status == "UNREACHABLE":
            opportunity_text = "区间未到"
        else:
            opportunity_text = "—"
        records.append(
            {
                "代码": str(item.get("symbol") or "").strip().upper(),
                "动作": str(item.get("plan_action") or "").strip().upper(),
                "状态": str(item.get("status") or "").strip().upper(),
                "成交": (
                    f"${float(item.get('avg_execution_price')):,.2f}"
                    if item.get("avg_execution_price") is not None
                    else "—"
                ),
                "股数": (
                    format_share_quantity(item.get("executed_shares"))
                    if item.get("executed_shares") is not None
                    else "—"
                ),
                "区间": zone_text,
                "机会": opportunity_text,
            }
        )
    return records


def _holding_advice_label(advice):
    if not advice:
        return "持有"
    action = str(advice.get("action", "HOLD")).upper()
    if action == "ADD":
        delta_shares = advice.get("delta_shares")
        if delta_shares:
            return f"加仓 +{format_share_quantity(delta_shares)}"
        return "ADD"
    if action == "TRIM":
        delta_shares = advice.get("delta_shares")
        if delta_shares:
            return f"减仓 -{format_share_quantity(abs(delta_shares))}"
        return "TRIM"
    if action == "EXIT":
        return "EXIT"
    return action if action != "HOLD" else "持有"


def _watch_priority_score(signal, expected_return, backtest_return):
    normalized = str(signal or "").strip().upper()
    base = {
        "STRONG_BUY": 500.0,
        "BUY": 400.0,
        "HOLD": 250.0,
        "SELL": 100.0,
        "STRONG_SELL": 0.0,
    }.get(normalized, 200.0)
    try:
        base += float(expected_return or 0.0) * 100.0
    except (TypeError, ValueError):
        pass
    try:
        base += float(backtest_return or 0.0) * 50.0
    except (TypeError, ValueError):
        pass
    return base


def _event_summary_for_symbol(symbol, active_events):
    symbol_text = str(symbol or "").strip().upper()
    relevant = []
    macro = []
    for event in list(active_events or []):
        event_symbols = [str(item or "").strip().upper() for item in list(getattr(event, "symbols", []) or []) if str(item or "").strip()]
        if symbol_text and symbol_text in event_symbols:
            relevant.append(event)
        elif not event_symbols:
            macro.append(event)
    selected = relevant[:2] if relevant else macro[:1]
    if not selected:
        return ""
    parts = []
    for event in selected:
        title = str(getattr(event, "title", "") or "").strip()
        severity = str(getattr(event, "severity", "") or "").strip().lower()
        sentiment = str(getattr(event, "sentiment", "") or "").strip().lower()
        fragments = [title] if title else []
        if severity:
            fragments.append(severity)
        if sentiment and sentiment != "neutral":
            fragments.append(sentiment)
        if fragments:
            parts.append("/".join(fragments))
    return "；".join(parts)


def _watch_system_summary(
    *,
    signal,
    reason,
    allocation_fields,
    consensus_fields,
    freshness,
    active_events=None,
    symbol=None,
):
    fragments = []
    signal_text = str(signal or "").strip().upper()
    if signal_text:
        fragments.append(f"量化信号 {signal_text}")
    reason_text = str(reason or "").strip()
    if reason_text:
        fragments.append(reason_text)
    allocation_reason = str((allocation_fields or {}).get("资金说明", "") or "").strip()
    if allocation_reason and allocation_reason != reason_text:
        fragments.append(allocation_reason)
    analyst_status = str((consensus_fields or {}).get("分析师意见", "") or "").strip()
    if analyst_status and analyst_status not in {"无数据", "中性"}:
        fragments.append(f"分析师 {analyst_status}")
    event_summary = _event_summary_for_symbol(symbol, active_events)
    if event_summary:
        fragments.append(f"事件 {event_summary}")
    freshness_label = str((freshness or {}).get("label", "") or "").strip()
    if freshness_label in {"偏旧", "过期", "无数据"}:
        fragments.append(f"全量分析{freshness_label}")
    if not fragments:
        return "暂无动态摘要"
    summary = " | ".join(fragments)
    if len(summary) > 220:
        return summary[:217] + "..."
    return summary


def _allocation_display_fields(
    symbol,
    last_price,
    signal,
    account,
    signal_profile=None,
    risk_gate=None,
    allocation_regime=None,
    current_invested_dollars=None,
):
    if last_price is None:
        return {
            "建议动作": "—",
            "建议投入": "—",
            "建议股数": "—",
            "资金说明": "缺少最新价格，暂无法估算建议投入金额。",
        }

    plan = ca.recommend_allocation(
        symbol=symbol,
        current_price=float(last_price),
        signal=signal,
        account=account or {},
        signal_profile=signal_profile,
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        current_invested_dollars=current_invested_dollars,
    )
    action_label = "买入" if plan.action == "BUY" else "观望"
    dollars_text = f"${plan.recommended_dollars:,.2f}" if plan.recommended_dollars > 0 else "—"
    shares_text = format_share_quantity(plan.recommended_shares) if plan.recommended_shares > 0 else "—"
    return {
        "建议动作": action_label,
        "建议投入": dollars_text,
        "建议股数": shares_text,
        "资金说明": plan.reason,
    }


def _format_price_range(low, high):
    if low is None or high is None:
        return "—"
    try:
        low_value = float(low)
        high_value = float(high)
    except (TypeError, ValueError):
        return "—"
    if low_value <= 0 or high_value <= 0:
        return "—"
    if high_value < low_value:
        low_value, high_value = high_value, low_value
    return f"${low_value:,.2f} ~ ${high_value:,.2f}"


def _upside_price_range_display(current_price, signal_profile=None):
    if current_price is None:
        return "—"
    try:
        current_price = float(current_price)
    except (TypeError, ValueError):
        return "—"

    if signal_profile is None:
        return "—"

    expected_return_pct = getattr(signal_profile, "expected_return_pct", None)
    if expected_return_pct is None:
        return "—"
    try:
        expected_return_pct = float(expected_return_pct)
    except (TypeError, ValueError):
        return "—"
    if expected_return_pct <= 0:
        return "—"

    center_price = getattr(signal_profile, "take_profit_price", None)
    if center_price is None:
        center_price = current_price * (1.0 + expected_return_pct)
    else:
        try:
            center_price = float(center_price)
        except (TypeError, ValueError):
            center_price = current_price * (1.0 + expected_return_pct)

    confidence = getattr(signal_profile, "confidence", None)
    try:
        confidence = 0.5 if confidence is None else max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5

    band_pct = max(
        0.02,
        min(0.08, abs(expected_return_pct) * 0.6 + (1.0 - confidence) * 0.02),
    )
    low_price = max(current_price * 1.01, center_price * (1.0 - band_pct))
    high_price = max(low_price, center_price * (1.0 + band_pct))
    return _format_price_range(low_price, high_price)


def build_holding_records(
    holdings,
    strategy,
    portfolio_value,
    risk_gate=None,
    analyst_consensus_cache=None,
    allocation_regime=None,
    analysis_snapshot=None,
    analysis_now=None,
):
    analysis_map = _analysis_snapshot_map(analysis_snapshot)
    records = []
    for i, h in enumerate(holdings):
        cost = h["cost"]
        shares = h["shares"]
        price = h.get("current_price")
        market_value = shares * price if price is not None else None
        pl = market_value - shares * cost if market_value is not None else None
        pl_pct = (pl / (shares * cost) * 100) if pl is not None and shares * cost != 0 else None

        analysis_row = analysis_map.get(str(h["symbol"]).strip().upper(), {})
        freshness = _analysis_freshness_fields(analysis_snapshot, analysis_row, now=analysis_now)
        if analysis_row:
            display_signal = str(analysis_row.get("signal", "HOLD") or "HOLD").upper()
            display_reason = str(analysis_row.get("signal_reason", "") or "")
            advice = dict(analysis_row.get("position_advice") or {})
            if not advice:
                advice = {
                    "action": "HOLD",
                    "target_weight_pct": 0.0,
                    "current_weight_pct": 0.0,
                    "reason": display_reason,
                }
            backtest_payload = dict(analysis_row.get("backtest", {}) or {})
            monte_carlo_payload = dict(analysis_row.get("monte_carlo", {}) or {})
            guidance_payload = dict(analysis_row.get("guidance", {}) or {})
        else:
            try:
                signal, reason, _ = _resolve_signal_and_profile(strategy, h["symbol"])
            except Exception as e:
                signal, reason = "HOLD", f"信号计算失败: {e}"
            signal_approval = approve_signal(signal, risk_gate=risk_gate)
            display_signal = signal_approval.approved_signal
            display_reason = reason
            if signal_approval.blocked and signal_approval.reason:
                display_reason = f"{reason} | {signal_approval.reason}"

            advice_obj = recommend_position_action(
                holding=h,
                portfolio_value=portfolio_value,
                signal=display_signal,
                signal_reason=display_reason,
                risk_gate=risk_gate,
                allocation_regime=allocation_regime,
            )
            advice = {
                "action": advice_obj.action,
                "delta_shares": advice_obj.delta_shares,
                "target_weight_pct": advice_obj.target_weight_pct,
                "current_weight_pct": advice_obj.current_weight_pct,
                "reason": advice_obj.reason,
            }
            backtest_payload = {}
            monte_carlo_payload = {}
            guidance_payload = {}
        consensus_fields = _consensus_display_fields(
            ac.get_cached_analyst_consensus(h["symbol"], analyst_consensus_cache)
        )
        advice_text = _holding_advice_label(advice)

        records.append({
            "序号": i,
            "代码": h["symbol"],
            "股数": shares,
            "成本价": cost,
            "现价": price,
            "市值": market_value,
            "盈亏 ($)": pl,
            "盈亏 (%)": pl_pct,
            "数据来源": "自动" if price is not None else "待刷新",
            "信号": display_signal,
            "信号说明": display_reason,
            "当前仓位": float(advice.get("current_weight_pct") or 0.0),
            "目标仓位": float(advice.get("target_weight_pct") or 0.0),
            "仓位建议": advice_text,
            "仓位说明": str(advice.get("reason", "") or display_reason),
            "回测收益": backtest_payload.get("total_return"),
            "回测胜率": backtest_payload.get("win_rate"),
            "MC预期": monte_carlo_payload.get("expected_return"),
            "最近全量分析时间": freshness["display"],
            "分析新鲜度": freshness["label"],
            "分析新鲜度颜色": freshness["color"],
            "退出参考": guidance_payload.get("suggested_exit_price"),
            **consensus_fields,
        })
    return records


def build_watchlist_records(
    watchlist,
    strategy=None,
    analyst_consensus_cache=None,
    account=None,
    risk_gate=None,
    allocation_regime=None,
    current_invested_dollars=None,
    analysis_snapshot=None,
    analysis_now=None,
    active_events=None,
):
    analysis_map = _analysis_snapshot_map(analysis_snapshot)
    records = []
    for i, w in enumerate(watchlist):
        last_price = w.get("last_price")
        analysis_row = analysis_map.get(str(w["symbol"]).strip().upper(), {})
        freshness = _analysis_freshness_fields(analysis_snapshot, analysis_row, now=analysis_now)
        if analysis_row:
            signal = str(analysis_row.get("signal", "HOLD") or "HOLD").upper()
            reason = str(analysis_row.get("signal_reason", "") or "")
            signal_profile = None
            backtest_payload = dict(analysis_row.get("backtest", {}) or {})
            monte_carlo_payload = dict(analysis_row.get("monte_carlo", {}) or {})
        else:
            signal, reason, signal_profile = _resolve_signal_and_profile(strategy, w["symbol"])
            backtest_payload = {}
            monte_carlo_payload = {}
        consensus = ac.get_cached_analyst_consensus(w["symbol"], analyst_consensus_cache)
        consensus_fields = _consensus_display_fields(consensus)
        signal, reason = ac.apply_analyst_consensus_to_signal(signal, reason, consensus)
        signal_approval = approve_signal(signal, risk_gate=risk_gate)
        signal = signal_approval.approved_signal
        if signal_approval.blocked and signal_approval.reason:
            reason = f"{reason} | {signal_approval.reason}"
        watch_hint, _ = _watch_hint_by_signal(signal)
        allocation_fields = _allocation_display_fields(
            w["symbol"],
            last_price,
            signal,
            account or {},
            signal_profile=signal_profile,
            risk_gate=risk_gate,
            allocation_regime=allocation_regime,
            current_invested_dollars=current_invested_dollars,
        )
        records.append({
            "选择": False,
            "序号": i,
            "代码": w["symbol"],
            "人工备注": w.get("notes", ""),
            "最新价": f"${last_price:,.2f}" if last_price else "—",
            "上涨预期价": _upside_price_range_display(last_price, signal_profile=signal_profile),
            "信号": signal,
            "提示": watch_hint,
            "信号说明": reason,
            "系统摘要": _watch_system_summary(
                signal=signal,
                reason=reason,
                allocation_fields=allocation_fields,
                consensus_fields=consensus_fields,
                freshness=freshness,
                active_events=active_events,
                symbol=w["symbol"],
            ),
            "回测收益": backtest_payload.get("total_return"),
            "MC预期": monte_carlo_payload.get("expected_return"),
            "最近全量分析时间": freshness["display"],
            "分析新鲜度": freshness["label"],
            "分析新鲜度颜色": freshness["color"],
            "排序分数": _watch_priority_score(signal, monte_carlo_payload.get("expected_return"), backtest_payload.get("total_return")),
            **allocation_fields,
            **consensus_fields,
        })
    records.sort(key=lambda row: float(row.get("排序分数") or 0.0), reverse=True)
    return records
def _watch_hint_by_signal(signal):
    normalized = str(signal or "").strip().upper()
    if normalized == "STRONG_BUY":
        return "强烈买入", "#047857"
    if normalized == "STRONG_SELL":
        return "强烈卖出", "#b91c1c"
    if normalized == "BUY":
        return "可以买入", "#0b7b44"
    if normalized == "SELL":
        return "不可买入", "#c2410c"
    return "观望", "#6b7280"
