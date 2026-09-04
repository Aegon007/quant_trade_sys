from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from integrations.slack.command_parser import parse_slack_command
from quant_core import paths as qpaths
from quant_core.api import actions, snapshot_loader


@dataclass(frozen=True)
class CommandExecutionResult:
    ok: bool
    command_name: str
    message: str
    snapshot: Optional[dict] = None


ACTION_LABELS = {
    "STRONG_OPPORTUNITY": "强估值机会",
    "ACCUMULATE": "可分批研究",
    "WATCH": "继续观察",
    "WAIT_FOR_STABILIZATION": "等待企稳",
    "FUNDAMENTALS_DAMAGED": "基本面受损",
    "VALUE_TRAP_RISK": "价值陷阱风险",
    "LLM_REVIEW_REQUIRED": "等待估值路线复核",
    "NO_STRONG_SIGNAL": "暂无强信号",
    "NORMAL": "正常",
    "CAUTION": "谨慎",
    "HIGH_RISK": "高风险",
    "OK": "正常",
    "DEGRADED": "需关注",
    "MISSING": "缺失",
    "PARTIAL": "部分可用",
    "fcff_multistage": "多阶段自由现金流折现",
    "revenue_growth_dcf": "成长型收入折现",
    "residual_income": "剩余收益模型",
    "normalized_earnings": "标准化盈利估值",
    "revenue_multiple": "收入倍数估值",
    "reit_ffo_nav": "REIT现金流与净资产估值",
    "sum_of_parts": "分部估值",
    "distress_weighted": "困境概率加权估值",
    "etf_risk_premium": "ETF风险溢价估值",
    "etf_yield_duration": "ETF收益率久期估值",
    "etf_spot_carry": "现货持有成本估值",
    "mature_profitable": "成熟盈利公司",
    "mature_growth": "成熟成长公司",
    "high_growth_profitable": "高增长盈利公司",
    "financial_service": "金融服务公司",
    "reit": "房地产信托",
    "cyclical": "周期型公司",
    "commodity": "商品型公司",
    "unprofitable_growth": "未盈利成长公司",
    "conglomerate": "多元化集团",
    "distressed": "困境公司",
    "broad_market_etf": "宽基ETF",
    "sector_etf": "行业ETF",
    "bond_etf": "债券ETF",
    "commodity_etf": "商品ETF",
}


def _label(value) -> str:
    raw = str(value or "")
    return ACTION_LABELS.get(raw, raw or "暂无")


def supported_commands_text() -> str:
    return "\n".join(
        [
            "可用命令",
            "• 概览：查看今日研究结论",
            "• 机会：查看当前超跌估值候选",
            "• 分析 股票代码：查看单一标的估值",
            "• 风险：查看市场风险环境",
            "• 关注列表",
            "• 关注 股票代码 / 取消关注 股票代码",
            "• 数据状态 / 策略校准",
            "• 刷新行情 / 运行完整研究",
        ]
    )


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value) -> str:
    value = _number(value)
    return "暂无" if value is None else f"${value:,.2f}"


def _percent(value) -> str:
    value = _number(value)
    return "暂无" if value is None else f"{value * 100:.1f}%"


def _opportunity_lines(rows, *, limit=5) -> list[str]:
    if not rows:
        return ["当前没有完成深度估值的候选。"]
    lines = []
    for index, row in enumerate(list(rows)[:limit], start=1):
        fair = dict(row.get("fair_value", {}) or {})
        label = _label(row.get("recommendation") or "WATCH")
        lines.extend(
            [
                f"{index}. {row.get('symbol')}：{label}，机会分 {float(row.get('opportunity_score') or 0):.0f}",
                f"   当前价 {_money(row.get('current_price'))}；合理价值中位数 {_money(fair.get('p50'))}；安全边际 {_percent(row.get('margin_of_safety'))}",
            ]
        )
    return lines


def _overview() -> CommandExecutionResult:
    envelope = snapshot_loader.load_dashboard_response()
    payload = dict(envelope.get("payload", {}) or {})
    recommendations = dict(payload.get("recommendations", {}) or {})
    brief = dict(payload.get("brief", {}) or {})
    risk = dict(payload.get("market_risk", {}) or {})
    summary = str(brief.get("summary_text") or "尚未生成研究摘要。")
    message = "\n".join(
        [
            "估值研究概览",
            f"市场状态：{_label(risk.get('regime'))}，风险分 {risk.get('risk_score', '暂无')}",
            summary,
            *_opportunity_lines(recommendations.get("recommendations", []), limit=3),
        ]
    )
    return CommandExecutionResult(True, "SHOW_OVERVIEW", message, envelope)


def _opportunities() -> CommandExecutionResult:
    envelope = snapshot_loader.load_opportunities_response()
    rows = list(dict(envelope.get("payload", {}) or {}).get("opportunities", []) or [])
    return CommandExecutionResult(True, "SHOW_OPPORTUNITIES", "\n".join(["超跌估值机会", *_opportunity_lines(rows)]), envelope)


def _analyze(symbol: str) -> CommandExecutionResult:
    envelope = snapshot_loader.load_valuations_response(symbol)
    rows = list(dict(envelope.get("payload", {}) or {}).get("valuations", []) or [])
    if not rows:
        return CommandExecutionResult(False, "ANALYZE", f"尚无 {symbol} 的估值结果。请先加入关注列表并运行完整研究。")
    row = dict(rows[0])
    fair = dict(row.get("fair_value", {}) or {})
    lines = [
        f"{symbol} 估值摘要",
        f"适用模型：{_label(row.get('primary_model'))}；公司类型：{_label(row.get('archetype'))}",
        f"当前价 {_money(row.get('current_price'))}；合理价值区间 {_money(fair.get('p10'))} 至 {_money(fair.get('p90'))}",
        f"中位合理价值 {_money(fair.get('p50'))}；安全边际 {_percent(row.get('margin_of_safety'))}；可信度 {_percent(row.get('confidence'))}",
    ]
    risks = [str(item) for item in list(row.get("risks", []) or []) if str(item)]
    if risks:
        lines.append("主要风险：" + "；".join(risks[:3]))
    return CommandExecutionResult(True, "ANALYZE", "\n".join(lines), envelope)


def _risk() -> CommandExecutionResult:
    envelope = snapshot_loader.load_market_risk_response()
    row = dict(envelope.get("payload", {}) or {})
    drivers = [str(item) for item in list(row.get("drivers", []) or []) if str(item)]
    lines = [
        "市场风险环境",
        f"当前状态：{_label(row.get('regime'))}；风险分 {row.get('risk_score', '暂无')}",
        f"建议研究门槛：{row.get('action_threshold_adjustment', '暂无')}",
    ]
    if drivers:
        lines.append("主要因素：" + "；".join(drivers[:4]))
    return CommandExecutionResult(True, "SHOW_RISK", "\n".join(lines), envelope)


def _watchlist() -> CommandExecutionResult:
    envelope = snapshot_loader.load_watchlist_response()
    rows = list(dict(envelope.get("payload", {}) or {}).get("symbols", []) or [])
    lines = ["关注列表"] + (["、".join(str(row.get("symbol")) for row in rows)] if rows else ["当前为空。"])
    return CommandExecutionResult(True, "SHOW_WATCHLIST", "\n".join(lines), envelope)


def _data_health() -> CommandExecutionResult:
    envelope = snapshot_loader.load_snapshot_response("data-health", qpaths.DATA_HEALTH_SNAPSHOT_FILE)
    payload = dict(envelope.get("payload", {}) or {})
    summary = dict(payload.get("summary", {}) or {})
    price_cache = dict(summary.get("price_cache", {}) or {})
    lines = [
        "数据健康状态",
        f"状态：{_label(payload.get('status') or envelope.get('freshness_status'))}",
        str(summary.get("reason") or "尚未完成健康检查"),
        f"最新价格缓存{_label(price_cache.get('status'))}，覆盖 {price_cache.get('symbol_count', 0)} 个标的",
        f"完成深度估值 {summary.get('analyzed_count', 0)} 个；记录标的级异常 {summary.get('error_count', 0)} 条",
    ]
    if summary.get("warnings"):
        lines.append("提示：" + str(summary["warnings"]))
    message = "\n".join(lines)
    return CommandExecutionResult(True, "SHOW_DATA_HEALTH", message, envelope)


def _calibration() -> CommandExecutionResult:
    envelope = snapshot_loader.load_snapshot_response("calibration", qpaths.VALUATION_CALIBRATION_FILE, max_age_seconds=8 * 86400)
    payload = dict(envelope.get("payload", {}) or {})
    lines = ["历史推荐校准"]
    for horizon, row in dict(payload.get("horizons", {}) or {}).items():
        lines.append(
            f"{horizon}个交易日：样本 {row.get('count', 0)}，跑赢短期国债比例 {_percent(row.get('risk_free_win_rate'))}，"
            f"跑赢SPY比例 {_percent(row.get('market_win_rate'))}；对短债中位超额 {_percent(row.get('median_excess_over_risk_free'))}，"
            f"对SPY中位超额 {_percent(row.get('median_excess_over_market'))}"
        )
    if len(lines) == 1:
        lines.append("尚无足够成熟样本；周末任务会持续更新。")
    return CommandExecutionResult(True, "SHOW_CALIBRATION", "\n".join(lines), envelope)


def execute_command(text: str) -> CommandExecutionResult:
    command = parse_slack_command(text)
    if command.name == "HELP":
        return CommandExecutionResult(True, command.name, supported_commands_text())
    if command.name == "SHOW_OVERVIEW":
        return _overview()
    if command.name == "SHOW_OPPORTUNITIES":
        return _opportunities()
    if command.name == "ANALYZE":
        return _analyze(command.symbol or "")
    if command.name == "SHOW_RISK":
        return _risk()
    if command.name == "SHOW_WATCHLIST":
        return _watchlist()
    if command.name == "SHOW_DATA_HEALTH":
        return _data_health()
    if command.name == "SHOW_CALIBRATION":
        return _calibration()
    if command.name in {"ADD_WATCH", "REMOVE_WATCH"}:
        result = actions.update_watchlist(command.symbol or "", remove=command.name == "REMOVE_WATCH")
        return CommandExecutionResult(True, command.name, str(result.get("message")), result)
    if command.name == "REFRESH_MARKET":
        result = actions.run_with_job_status("slack-market-refresh", actions.refresh_market_data_now, run_async=True)
        return CommandExecutionResult(bool(result.get("accepted")), command.name, "行情刷新任务已启动，可稍后发送“数据状态”查看结果。", result)
    if command.name == "RUN_RESEARCH":
        result = actions.run_with_job_status(
            "slack-full-research",
            lambda: actions.run_nightly_once(progress=actions.build_job_progress_callback("slack-full-research")),
            run_async=True,
        )
        return CommandExecutionResult(bool(result.get("accepted")), command.name, "完整估值研究已启动，可稍后发送“概览”查看结果。", result)
    return CommandExecutionResult(False, command.name, "无法识别该命令。\n\n" + supported_commands_text())


execute_slack_command = execute_command
