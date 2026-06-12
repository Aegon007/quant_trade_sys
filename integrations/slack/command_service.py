import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from quant_core import paths as qpaths
from quant_core.analytics import candidate_pool as cpool
from quant_core.data import data_health as dhealth
from quant_core.portfolio import actions as pactions
from quant_core.portfolio import core_etf_engine as cee
from quant_core.portfolio import discipline as qdisc
from quant_core.research import strategy_validation as sval
from quant_core.data import storage as du
from quant_core.execution import nightly_planner as nplanner
from quant_core.execution import plan_quality as pquality
from quant_core.snapshots import system_snapshot as ss
from quant_core.common.share_utils import format_share_quantity, validate_share_quantity
from integrations.slack.command_parser import ParsedSlackCommand, parse_slack_command

qpaths.bootstrap_storage_paths()

COMMAND_AUDIT_FILE = qpaths.COMMAND_AUDIT_FILE
TRADE_PLAN_FILE = qpaths.NEXT_DAY_TRADE_PLAN_FILE
DISCIPLINE_SNAPSHOT_FILE = qpaths.DISCIPLINE_SNAPSHOT_FILE
CORE_ETF_SNAPSHOT_FILE = qpaths.CORE_ETF_SNAPSHOT_FILE
SATELLITE_CANDIDATE_POOL_FILE = qpaths.SATELLITE_CANDIDATE_POOL_FILE
NIGHTLY_JOURNAL_FILE = ss.DEFAULT_NIGHTLY_JOURNAL_FILE
STRATEGY_VALIDATION_SNAPSHOT_FILE = qpaths.STRATEGY_VALIDATION_SNAPSHOT_FILE
DATA_HEALTH_SNAPSHOT_FILE = qpaths.DATA_HEALTH_SNAPSHOT_FILE
PLAN_QUALITY_SNAPSHOT_FILE = qpaths.PLAN_QUALITY_SNAPSHOT_FILE


@dataclass(frozen=True)
class CommandExecutionResult:
    ok: bool
    command_name: str
    message: str
    snapshot: Optional[dict] = None
    action_payload: Optional[dict] = None


def supported_commands_text() -> str:
    return "\n".join(
        [
            "驾驶舱查询:",
            "- 可用命令 / help",
            "- 系统概览",
            "- 今日计划 / 明日计划",
            "- 风险状态 / 纪律状态",
            "- 数据状态",
            "- 计划质量",
            "- 策略验证",
            "- 核心ETF",
            "- 卫星雷达 / top3",
            "- 当前持仓",
            "- 当前关注",
            "- 状态 <代码>",
            "",
            "同步与维护:",
            "- 买入 <代码> <股数>",
            "- 卖出 <代码> <股数>",
            "- 全部卖出 <代码>",
            "- 关注 <代码>",
            "- 取消关注 <代码>",
            "- 转到关注 <代码>",
            "- 转到持仓 <代码> [股数]",
            "- 刷新 全部",
        ]
    )


def _format_currency(value) -> str:
    if value is None:
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(amount):
        return "—"
    return f"${amount:,.2f}"


def _find_record(records, symbol: str):
    normalized = str(symbol or "").strip().upper()
    for record in records or []:
        if str(record.get("symbol", "")).strip().upper() == normalized:
            return record
    return None


def _format_pct(value, *, scale=1.0) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number * scale:.1f}%"


def _format_price(value) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"${number:,.2f}"


def _format_price_range(low, high) -> str:
    if low is None or high is None:
        return "—"
    low_text = _format_price(low)
    high_text = _format_price(high)
    if low_text == "—" or high_text == "—":
        return "—"
    return f"{low_text} - {high_text}"


def _load_snapshot(data=None):
    current_data = data if data is not None else du.load_data()
    return ss.build_system_snapshot(data=current_data)


def _account_summary_line(snapshot: dict) -> str:
    account = snapshot.get("account", {})
    cash_available = account.get("cash_available")
    deployable_cash = account.get("deployable_cash")
    if cash_available is None:
        return ""
    return (
        f"可用现金: {_format_currency(cash_available)} | "
        f"可部署现金: {_format_currency(deployable_cash)}"
    )


def _format_holdings_message(data, snapshot) -> str:
    holdings = data.get("holdings", [])
    if not holdings:
        return "当前没有持仓。"
    lines = [f"当前持仓 ({len(holdings)})"]
    for holding in holdings:
        market_value = None
        if holding.get("current_price") is not None:
            market_value = float(holding["shares"]) * float(holding["current_price"])
        lines.append(
            "- "
            f"{holding['symbol']} | {format_share_quantity(holding['shares'])} 股 | "
            f"成本 {_format_currency(holding.get('cost'))} | "
            f"现价 {_format_currency(holding.get('current_price'))} | "
            f"市值 {_format_currency(market_value)}"
        )
    account_line = _account_summary_line(snapshot)
    if account_line:
        lines.append(account_line)
    return "\n".join(lines)


def _format_watchlist_message(data, snapshot) -> str:
    watchlist = data.get("watchlist", [])
    if not watchlist:
        return "当前没有关注标的。"
    lines = [f"当前关注 ({len(watchlist)})"]
    for watch in watchlist:
        notes = str(watch.get("notes") or "").strip() or "—"
        lines.append(
            "- "
            f"{watch['symbol']} | 最新 {_format_currency(watch.get('last_price'))} | "
            f"备注 {notes}"
        )
    account_line = _account_summary_line(snapshot)
    if account_line:
        lines.append(account_line)
    return "\n".join(lines)


def _format_status_message(data, symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    holding = _find_record(data.get("holdings", []), symbol)
    if holding is not None:
        market_value = None
        if holding.get("current_price") is not None:
            market_value = float(holding["shares"]) * float(holding["current_price"])
        return "\n".join(
            [
                f"{symbol} 当前在持仓中",
                f"- 股数: {format_share_quantity(holding['shares'])}",
                f"- 成本价: {_format_currency(holding.get('cost'))}",
                f"- 现价: {_format_currency(holding.get('current_price'))}",
                f"- 市值: {_format_currency(market_value)}",
                f"- 行业: {holding.get('sector') or '—'}",
            ]
        )

    watch = _find_record(data.get("watchlist", []), symbol)
    if watch is not None:
        return "\n".join(
            [
                f"{symbol} 当前在关注列表中",
                f"- 最新价: {_format_currency(watch.get('last_price'))}",
                f"- 备注: {watch.get('notes') or '—'}",
            ]
        )

    return f"未找到 {symbol}，对应标的不在持仓或关注列表中。"


def _load_trade_plan():
    return nplanner.load_next_day_trade_plan(path=TRADE_PLAN_FILE)


def _load_discipline_snapshot():
    return qdisc.load_discipline_snapshot(path=DISCIPLINE_SNAPSHOT_FILE)


def _load_core_etf_snapshot():
    return cee.load_core_etf_snapshot(path=CORE_ETF_SNAPSHOT_FILE)


def _load_satellite_snapshot():
    return cpool.load_satellite_candidate_pool_snapshot(path=SATELLITE_CANDIDATE_POOL_FILE)


def _load_strategy_validation_snapshot():
    return sval.load_strategy_validation_snapshot(path=STRATEGY_VALIDATION_SNAPSHOT_FILE)


def _load_data_health_snapshot():
    return dhealth.load_data_health_snapshot(path=DATA_HEALTH_SNAPSHOT_FILE)


def _load_plan_quality_snapshot():
    return pquality.load_plan_quality_snapshot(path=PLAN_QUALITY_SNAPSHOT_FILE)


def _load_latest_monthly_review():
    rows = ss.load_snapshot_journal(journal_path=NIGHTLY_JOURNAL_FILE, limit=1)
    if not rows:
        return None
    return dict((rows[-1] or {}).get("monthly_discipline_review", {}) or {})


def _format_trade_plan_message(plan) -> str:
    plan = dict(plan or {})
    if not plan:
        return "尚未生成次日计划。请先运行 nightly 或执行一次强制补齐。"
    lines = [
        "次日交易计划",
        f"- 计划日: {plan.get('plan_date') or '—'}",
        f"- 模式: {plan.get('decision') or '—'}",
        f"- 结论: {plan.get('summary_reason') or '—'}",
    ]
    decision_signature = str(plan.get("decision_signature") or "").strip()
    if decision_signature:
        lines.append(f"- 计划签名: {decision_signature}")
    items = list(plan.get("items", []) or [])
    if not items:
        lines.append("- 当前无强信号，建议按计划不动。")
        return "\n".join(lines)
    lines.append("- 计划单:")
    for item in items[:5]:
        symbol = str(item.get("symbol") or "").strip().upper() or "—"
        action = str(item.get("plan_action") or "").strip().upper() or "HOLD"
        lines.append(
            "  "
            f"{symbol} | {action} | 仓位变化 {_format_pct(item.get('plan_weight_delta_pct'))}"
        )
        buy_zone = _format_price_range(item.get("buy_zone_low"), item.get("buy_zone_high"))
        trim_zone = _format_price_range(item.get("trim_zone_low"), item.get("trim_zone_high"))
        if buy_zone != "—":
            lines.append(f"    买入区间: {buy_zone}")
        if trim_zone != "—":
            lines.append(f"    减仓区间: {trim_zone}")
        if item.get("invalid_condition"):
            lines.append(f"    作废条件: {item.get('invalid_condition')}")
    if len(items) > 5:
        lines.append(f"- 其余 {len(items) - 5} 条动作请在 WebUI 查看。")
    return "\n".join(lines)


def _format_risk_message(snapshot, monthly_review=None) -> str:
    snapshot = dict(snapshot or {})
    if not snapshot:
        return "尚未生成纪律与风险快照。请先运行 nightly 或执行一次强制补齐。"
    monthly_review = dict(monthly_review or {})
    lines = [
        "纪律与风险状态",
        f"- 纪律状态: {snapshot.get('regime') or '—'}",
        f"- 风险状态: {snapshot.get('risk_regime') or '—'}",
        f"- 配置状态: {snapshot.get('allocation_regime') or '—'}",
        f"- 可开核心仓: {'是' if snapshot.get('can_open_new_core_positions') else '否'}",
        f"- 可开卫星仓: {'是' if snapshot.get('can_open_new_satellite_positions') else '否'}",
        f"- 可部署现金: {_format_currency(snapshot.get('deployable_cash'))}",
        f"- 暴露率: {_format_pct(snapshot.get('exposure_pct'))}",
    ]
    summary = str(snapshot.get("summary") or "").strip()
    if summary:
        lines.append(f"- 总结: {summary}")
    warnings = list(snapshot.get("warnings", []) or [])
    if warnings:
        lines.append(f"- 预警: {'；'.join(str(item).strip() for item in warnings[:2] if str(item).strip())}")
    if monthly_review:
        lines.append(
            f"- 月度纪律: {monthly_review.get('status') or '—'} | "
            f"FOLLOW {int(monthly_review.get('follow_days') or 0)} | "
            f"IGNORE {int(monthly_review.get('ignore_days') or 0)}"
        )
    return "\n".join(lines)


def _format_core_etf_message(snapshot) -> str:
    snapshot = dict(snapshot or {})
    if not snapshot:
        return "尚未生成核心 ETF 快照。请先运行 nightly 或执行一次强制补齐。"
    summary = dict(snapshot.get("summary", {}) or {})
    symbols = list(snapshot.get("symbols", []) or [])
    ranked = sorted(
        symbols,
        key=lambda row: (
            {"ACCUMULATE": 0, "TRIM": 1, "PAUSE_BUY": 2, "RISK_EXIT": 3, "HOLD": 4}.get(
                str((row or {}).get("action") or "HOLD").strip().upper(),
                9,
            ),
            -float((row or {}).get("target_weight_pct") or 0.0),
            str((row or {}).get("symbol") or ""),
        ),
    )
    lines = [
        "核心 ETF 引擎",
        f"- 风险状态: {snapshot.get('risk_regime') or '—'} | 配置状态: {snapshot.get('allocation_regime') or '—'}",
        f"- 动作汇总: 加仓 {int(summary.get('accumulate_count') or 0)} / 减仓 {int(summary.get('trim_count') or 0)} / 总数 {int(summary.get('total_symbols') or 0)}",
    ]
    if not ranked:
        lines.append("- 当前没有核心 ETF 快照明细。")
        return "\n".join(lines)
    lines.append("- 重点 ETF:")
    for row in ranked[:5]:
        symbol = str(row.get("symbol") or "").strip().upper() or "—"
        action = str(row.get("action") or "HOLD").strip().upper()
        stability = row.get("signal_stability_score")
        stability_text = "—" if stability is None else f"{float(stability):.0f}/100"
        same_action_days = int(float(row.get("days_in_same_action") or 0.0) or 0)
        lines.append(
            "  "
            f"{symbol} | {action} | 当前 {_format_pct(row.get('current_weight_pct'))} | "
            f"目标 {_format_pct(row.get('target_weight_pct'))} | 分数 {float(row.get('rotation_score') or 0.0):.1f} | 稳定 {stability_text}"
        )
        lines.append(
            "    "
            f"同动作 {same_action_days} 天 | "
            f"买 {_format_price_range(row.get('recommended_buy_zone_low'), row.get('recommended_buy_zone_high'))} | "
            f"减 {_format_price_range(row.get('trim_zone_low'), row.get('trim_zone_high'))} | "
            f"破位 {_format_price(row.get('risk_break_level'))}"
        )
    return "\n".join(lines)


def _format_satellite_message(snapshot) -> str:
    snapshot = dict(snapshot or {})
    if not snapshot:
        return "尚未生成卫星雷达快照。请先运行 nightly 或执行一次强制补齐。"
    summary = dict(snapshot.get("summary", {}) or {})
    top_rows = list(snapshot.get("top_recommendations", []) or [])
    lines = [
        "卫星仓雷达",
        f"- 候选池: {int(summary.get('candidate_count') or 0)} | 深分析: {int(summary.get('deep_analysis_count') or 0)} | Top3: {int(summary.get('top_recommendation_count') or 0)}",
        f"- 状态汇总: CONFIRMED {int(summary.get('confirmed_count') or 0)} / PROBE {int(summary.get('probe_count') or 0)} / WATCH {int(summary.get('watch_count') or 0)}",
    ]
    if not top_rows:
        lines.append("- 当前没有进入 Top 推荐的卫星仓候选。")
        return "\n".join(lines)
    lines.append("- Top 推荐:")
    for row in top_rows[:3]:
        symbol = str(row.get("symbol") or "").strip().upper() or "—"
        status = str(row.get("recommendation_status") or "WATCH").strip().upper()
        action = str(row.get("plan_action") or "HOLD").strip().upper()
        membership_state = str(row.get("top3_membership_state") or "").strip().upper() or "—"
        residency_days = int(float(row.get("top3_residency_days") or 0.0) or 0)
        lines.append(
            "  "
            f"{symbol} | {status} / {action} | 仓位 {_format_pct(row.get('suggested_weight_pct'))} | 总分 {float(row.get('satellite_score') or 0.0):.1f}"
        )
        lines.append(f"    Top3: {membership_state} | 驻留 {residency_days} 天")
        reason = str(row.get("recommendation_reason") or row.get("signal_reason") or "").strip()
        if reason:
            lines.append(f"    原因: {reason}")
    return "\n".join(lines)


def _format_strategy_validation_message(snapshot) -> str:
    snapshot = dict(snapshot or {})
    summary = dict(snapshot.get("summary", {}) or {})
    if not summary:
        return "尚未生成策略验证快照。请先运行周末研究或执行一次强制补齐。"
    lines = [
        "策略验证",
        f"- 状态: {summary.get('status') or '—'} | 覆盖: {int(summary.get('symbol_count') or 0)} | 已验证: {int(summary.get('validated_count') or 0)}",
        f"- 预警: {int(summary.get('review_count') or 0)} REVIEW / {int(summary.get('caution_count') or 0)} CAUTION / {int(summary.get('low_sample_count') or 0)} LOW_SAMPLE",
    ]
    message = str(summary.get("message") or "").strip()
    if message:
        lines.append(f"- 结论: {message}")
    warning_symbols = list(summary.get("warning_symbols", []) or [])
    if warning_symbols:
        lines.append(f"- 重点复核: {', '.join(warning_symbols[:6])}")
    rows = list(snapshot.get("symbols", []) or [])
    if rows:
        ranked = sorted(
            rows,
            key=lambda row: (
                {"REVIEW": 0, "CAUTION": 1, "LOW_SAMPLE": 2, "VALIDATED": 3, "UNVALIDATED": 4}.get(
                    str((row or {}).get("status") or "UNVALIDATED").strip().upper(),
                    9,
                ),
                str((row or {}).get("focus_role") or ""),
                str((row or {}).get("symbol") or ""),
            ),
        )
        lines.append("- 重点标的:")
        for row in ranked[:5]:
            lines.append(
                "  "
                f"{str(row.get('symbol') or '').strip().upper() or '—'} | "
                f"{str(row.get('focus_role') or 'satellite').strip().lower()} | "
                f"{str(row.get('status') or '—').strip().upper()} | "
                f"默认第 {row.get('default_rank') if row.get('default_rank') is not None else '—'} | "
                f"领先 {str(row.get('best_strategy_name') or '—').strip()}"
            )
    return "\n".join(lines)


def _format_data_health_message(snapshot) -> str:
    snapshot = dict(snapshot or {})
    summary = dict(snapshot.get("summary", {}) or {})
    if not summary:
        return "尚未生成数据健康快照。请先刷新行情或运行 nightly。"
    lines = [
        "数据状态",
        f"- 状态: {summary.get('status') or snapshot.get('status') or '—'}",
        f"- 跟踪标的: {int(summary.get('tracked_symbol_count') or 0)} | 缺失 {int(summary.get('missing_price_count') or 0)} | 无效 {int(summary.get('invalid_price_count') or 0)} | 过期 {int(summary.get('stale_price_count') or 0)}",
        f"- 主源命中: {int(summary.get('primary_symbol_count') or 0)} | fallback: {int(summary.get('fallback_symbol_count') or 0)}",
    ]
    missing = list(snapshot.get("missing_symbols", []) or [])
    invalid = list(snapshot.get("invalid_symbols", []) or [])
    stale = list(snapshot.get("stale_symbols", []) or [])
    if missing:
        lines.append(f"- 缺失价格: {', '.join(missing[:8])}")
    if invalid:
        lines.append(f"- 无效价格: {', '.join(invalid[:8])}")
    if stale:
        lines.append(f"- 过期缓存: {', '.join(stale[:8])}")
    if summary.get("last_error"):
        lines.append(f"- 最近错误: {summary.get('last_error')}")
    return "\n".join(lines)


def _format_plan_quality_message(snapshot) -> str:
    snapshot = dict(snapshot or {})
    summary = dict(snapshot.get("summary", {}) or {})
    if not summary:
        return "尚未生成计划质量快照。请先运行 nightly 或导入 Robinhood CSV 后复盘。"
    execution_rate = summary.get("execution_rate")
    rate_text = "—" if execution_rate is None else f"{float(execution_rate) * 100:.1f}%"
    lines = [
        "计划质量",
        f"- 状态: {summary.get('status') or snapshot.get('status') or '—'} | 复盘数: {int(summary.get('review_count') or 0)}",
        f"- 执行率: {rate_text} | 已执行 {int(summary.get('executed_count') or 0)} | 错过 {int(summary.get('missed_count') or 0)} | 计划外 {int(summary.get('unplanned_trade_count') or 0)}",
        f"- 可触达未执行: {int(summary.get('missed_reachable_count') or 0)} | 跳空/失效 {int(summary.get('invalidated_count') or 0)} | 区间未到 {int(summary.get('unreachable_count') or 0)}",
    ]
    groups = dict(snapshot.get("groups", {}) or {})
    for name in ("core", "satellite", "tactical"):
        row = dict(groups.get(name, {}) or {})
        lines.append(
            f"- {name}: planned {int(row.get('planned_count') or 0)} | executed {int(row.get('executed_count') or 0)} | missed reachable {int(row.get('missed_reachable_count') or 0)}"
        )
    return "\n".join(lines)


def _format_overview_message(
    data,
    snapshot,
    plan,
    discipline_snapshot,
    core_snapshot,
    satellite_snapshot,
    strategy_validation_snapshot=None,
    data_health_snapshot=None,
    plan_quality_snapshot=None,
    monthly_review=None,
) -> str:
    account = dict((snapshot or {}).get("account", {}) or {})
    lines = [
        "系统概览",
        f"- 计划: {(plan or {}).get('decision') or '—'} | {(plan or {}).get('summary_reason') or '尚未生成计划'}",
        f"- 纪律/风险: {(discipline_snapshot or {}).get('regime') or '—'} / {(discipline_snapshot or {}).get('risk_regime') or '—'}",
        f"- 账户: 现金 {_format_currency(account.get('cash_available'))} | 可部署 {_format_currency(account.get('deployable_cash'))} | 暴露 {_format_pct(account.get('exposure_pct'))}",
        f"- 持仓/关注: {len((data or {}).get('holdings', []) or [])} / {len((data or {}).get('watchlist', []) or [])}",
    ]
    plan_signature = str((plan or {}).get("decision_signature") or "").strip()
    if plan_signature:
        lines.append(f"- 计划签名: {plan_signature}")
    core_summary = dict((core_snapshot or {}).get("summary", {}) or {})
    lines.append(
        f"- 核心 ETF: 加仓 {int(core_summary.get('accumulate_count') or 0)} / 减仓 {int(core_summary.get('trim_count') or 0)}"
    )
    top_symbols = list(dict((satellite_snapshot or {}).get("summary", {}) or {}).get("top_symbols", []) or [])
    lines.append(f"- 卫星雷达 Top: {', '.join(top_symbols[:3]) if top_symbols else '当前无 Top 推荐'}")
    validation_summary = dict((strategy_validation_snapshot or {}).get("summary", {}) or {})
    if validation_summary:
        lines.append(
            f"- 策略验证: {validation_summary.get('status') or '—'} | "
            f"覆盖 {int(validation_summary.get('symbol_count') or 0)} | "
            f"预警 {len(list(validation_summary.get('warning_symbols', []) or []))}"
        )
    data_health_summary = dict((data_health_snapshot or {}).get("summary", {}) or {})
    if data_health_summary:
        lines.append(
            f"- 数据健康: {data_health_summary.get('status') or '—'} | "
            f"缺失 {int(data_health_summary.get('missing_price_count') or 0)} | "
            f"无效 {int(data_health_summary.get('invalid_price_count') or 0)}"
        )
    plan_quality_summary = dict((plan_quality_snapshot or {}).get("summary", {}) or {})
    if plan_quality_summary:
        lines.append(
            f"- 计划质量: {plan_quality_summary.get('status') or '—'} | "
            f"已执行 {int(plan_quality_summary.get('executed_count') or 0)} | "
            f"可触达未执行 {int(plan_quality_summary.get('missed_reachable_count') or 0)}"
        )
    if monthly_review:
        lines.append(
            f"- 月度纪律: {monthly_review.get('status') or '—'} | FOLLOW {int(monthly_review.get('follow_days') or 0)} / IGNORE {int(monthly_review.get('ignore_days') or 0)}"
        )
    return "\n".join(lines)


def _append_command_audit_log(command: ParsedSlackCommand, ok: bool, message: str, action_payload=None, path=None):
    path = path or COMMAND_AUDIT_FILE
    row = {
        "timestamp": datetime.now().isoformat(),
        "command_name": command.name,
        "raw_text": command.raw_text,
        "normalized_text": command.normalized_text,
        "symbol": command.symbol,
        "shares": command.shares,
        "ok": bool(ok),
        "message": str(message),
        "action_payload": action_payload or {},
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _friendly_error_message(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("watchlist ") and message.endswith(" not found"):
        symbol = message[len("watchlist ") : -len(" not found")].strip().upper()
        return f"{symbol} 不在关注列表中。请先执行“关注 {symbol}”，或直接使用“买入 {symbol} <股数>”。"
    if message.startswith("holding ") and message.endswith(" not found"):
        symbol = message[len("holding ") : -len(" not found")].strip().upper()
        return f"{symbol} 不在持仓中。"
    if message.endswith("already exists in holdings"):
        symbol = message[: -len("already exists in holdings")].strip().upper()
        return f"{symbol} 已在持仓中。"
    if message.endswith("already exists in watchlist"):
        symbol = message[: -len("already exists in watchlist")].strip().upper()
        return f"{symbol} 已在关注列表中。"
    if message == "sell shares cannot exceed current holding shares":
        return "卖出股数不能超过当前持仓。"
    if message == "cash_available would become negative":
        return "可用现金不足，无法完成本次操作。"
    if "must be at least" in message:
        parts = message.split("must be at least", 1)
        field_name = parts[0].strip() or "shares"
        threshold = parts[1].strip()
        return f"{field_name} 至少为 {threshold} 股"
    return message


def _result(ok: bool, command: ParsedSlackCommand, message: str, action_payload=None, data=None) -> CommandExecutionResult:
    snapshot = None
    try:
        snapshot = _load_snapshot(data=data)
    except Exception:
        snapshot = None
    _append_command_audit_log(command, ok, message, action_payload=action_payload)
    return CommandExecutionResult(
        ok=bool(ok),
        command_name=command.name,
        message=message,
        snapshot=snapshot,
        action_payload=action_payload,
    )


def execute_slack_command(text) -> CommandExecutionResult:
    command = parse_slack_command(text)

    try:
        if command.name == "HELP":
            return _result(True, command, supported_commands_text())

        if command.name == "SHOW_PLAN":
            return _result(True, command, _format_trade_plan_message(_load_trade_plan()))

        if command.name == "SHOW_RISK":
            return _result(
                True,
                command,
                _format_risk_message(_load_discipline_snapshot(), monthly_review=_load_latest_monthly_review()),
            )

        if command.name == "SHOW_DATA_HEALTH":
            return _result(True, command, _format_data_health_message(_load_data_health_snapshot()))

        if command.name == "SHOW_PLAN_QUALITY":
            return _result(True, command, _format_plan_quality_message(_load_plan_quality_snapshot()))

        if command.name == "SHOW_VALIDATION":
            return _result(True, command, _format_strategy_validation_message(_load_strategy_validation_snapshot()))

        if command.name == "SHOW_CORE":
            return _result(True, command, _format_core_etf_message(_load_core_etf_snapshot()))

        if command.name == "SHOW_SATELLITE":
            return _result(True, command, _format_satellite_message(_load_satellite_snapshot()))

        if command.name == "SHOW_OVERVIEW":
            data = du.load_data()
            snapshot = _load_snapshot(data=data)
            return _result(
                True,
                command,
                _format_overview_message(
                    data,
                    snapshot,
                    _load_trade_plan(),
                    _load_discipline_snapshot(),
                    _load_core_etf_snapshot(),
                    _load_satellite_snapshot(),
                    _load_strategy_validation_snapshot(),
                    _load_data_health_snapshot(),
                    _load_plan_quality_snapshot(),
                    monthly_review=_load_latest_monthly_review(),
                ),
                data=data,
            )

        if command.name == "SHOW_HOLDINGS":
            data = du.load_data()
            snapshot = _load_snapshot(data=data)
            return _result(True, command, _format_holdings_message(data, snapshot), data=data)

        if command.name == "SHOW_WATCHLIST":
            data = du.load_data()
            snapshot = _load_snapshot(data=data)
            return _result(True, command, _format_watchlist_message(data, snapshot), data=data)

        if command.name == "STATUS":
            data = du.load_data()
            return _result(True, command, _format_status_message(data, command.symbol), data=data)

        if command.name == "REFRESH_ALL":
            data = pactions.refresh_all_market_data(force_source_refresh=True)
            updated_at = data.get("prices_last_updated") or "—"
            return _result(True, command, f"已强制刷新行情数据。更新时间: {updated_at}", data=data)

        if command.name == "ADD_WATCH":
            action = pactions.add_watch_symbol(command.symbol)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = f"已关注 {action['symbol']}。"
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "REMOVE_WATCH":
            action = pactions.remove_watch_symbol(command.symbol)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = f"已取消关注 {action['symbol']}。"
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name in {"BUY", "SELL"}:
            validate_share_quantity(command.shares, field_name="shares")

        if command.name == "BUY":
            action = pactions.buy_symbol(command.symbol, command.shares)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已买入 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "SELL":
            action = pactions.sell_symbol(command.symbol, command.shares)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已卖出 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "SELL_ALL":
            action = pactions.sell_all_symbol(command.symbol)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已清仓 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}，并转入关注列表。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "MOVE_TO_WATCH":
            action = pactions.move_holding_to_watch(command.symbol)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已转到关注 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "MOVE_TO_HOLDING":
            shares = 1.0 if command.shares is None else validate_share_quantity(command.shares, field_name="shares")
            action = pactions.move_watch_to_holding(command.symbol, shares)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已转到持仓 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "UNKNOWN":
            return _result(False, command, "未识别命令。发送“可用命令”查看支持的操作。")

        return _result(False, command, f"暂未实现命令: {command.name}")
    except ValueError as exc:
        return _result(False, command, _friendly_error_message(exc))
    except Exception as exc:
        return _result(False, command, f"命令执行失败: {exc}")
