from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.llm import openai_compatible as oai
from quant_core.notifications import notification_config as ncfg


DEFAULT_EXPLANATION_CACHE_FILE = qpaths.LLM_SUMMARY_CACHE_FILE


def load_explanation_cache(*, path: str = DEFAULT_EXPLANATION_CACHE_FILE):
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_explanation_cache(cache: Mapping, *, path: str = DEFAULT_EXPLANATION_CACHE_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(cache or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def summarize_explanation_cache(*, path: str = DEFAULT_EXPLANATION_CACHE_FILE):
    cache = load_explanation_cache(path=path)
    rows = list(dict(cache or {}).values())
    if not rows:
        return {"entry_count": 0, "by_kind": {}, "by_route": {}, "latest_created_at": None}
    by_kind = {}
    by_route = {}
    latest_created_at = None
    for row in rows:
        row = dict(row or {})
        kind = str(row.get("kind") or "unknown").strip() or "unknown"
        route = str(row.get("route_name") or "unknown").strip() or "unknown"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_route[route] = by_route.get(route, 0) + 1
        created_at = str(row.get("created_at") or "").strip()
        if created_at and (latest_created_at is None or created_at > latest_created_at):
            latest_created_at = created_at
    return {
        "entry_count": len(rows),
        "by_kind": by_kind,
        "by_route": by_route,
        "latest_created_at": latest_created_at,
    }


def select_llm_route(config: Mapping, *, complexity: str = "narration"):
    routes = list_llm_routes(config, complexity=complexity)
    if routes:
        return routes[0]
    return "", {}


def list_llm_routes(config: Mapping, *, complexity: str = "narration"):
    normalized = ncfg.normalize_notification_config(dict(config or {}))
    local_slm = dict(normalized.get("local_slm", {}) or {})
    remote_llm = dict(normalized.get("llm", {}) or {})
    complexity = str(complexity or "narration").strip().lower()
    routes = []

    def add_route(route_name: str, route_config: Mapping):
        route_config = dict(route_config or {})
        if not route_config.get("enabled") or not str(route_config.get("base_url") or "").strip():
            return
        if any(existing_name == route_name for existing_name, _ in routes):
            return
        routes.append((route_name, route_config))

    if complexity in {"narration", "rewrite", "verbalize"}:
        add_route("local_slm", local_slm)
        add_route("llm", remote_llm)
    elif complexity in {"explanation", "research", "analysis", "complex"}:
        add_route("llm", remote_llm)
        add_route("local_slm", local_slm)
    else:
        add_route("llm", remote_llm)
        add_route("local_slm", local_slm)
    return routes


def build_core_etf_explanation_messages(
    *,
    symbol_row: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    change_feed: Optional[Mapping] = None,
):
    row = dict(symbol_row or {})
    discipline_snapshot = dict(discipline_snapshot or {})
    change_feed = dict(change_feed or {})
    symbol = str(row.get("symbol") or "").strip().upper() or "UNKNOWN"
    title_bits = []
    for item in list(change_feed.get("high_items", []) or []):
        if str(item.get("symbol") or "").strip().upper() == symbol:
            title_bits.append(f"{item.get('title', '')}: {item.get('message', '')}".strip(": "))
    change_context = " | ".join(title_bits[:2]) or "无新的高优先级变化。"
    user_prompt = (
        f"请用简洁中文解释为什么系统当前对核心 ETF {symbol} 给出这个结论。\n"
        f"- 动作: {row.get('action', 'HOLD')}\n"
        f"- 当前仓位: {row.get('current_weight_pct', 0)}%\n"
        f"- 目标仓位: {row.get('target_weight_pct', 0)}%\n"
        f"- 目标区间: {row.get('target_weight_range_low_pct', 0)}% ~ {row.get('target_weight_range_high_pct', 0)}%\n"
        f"- 轮动评分: {row.get('rotation_score', 0)}\n"
        f"- 买入区间: {row.get('recommended_buy_zone_low')} ~ {row.get('recommended_buy_zone_high')}\n"
        f"- 减仓区间: {row.get('trim_zone_low')} ~ {row.get('trim_zone_high')}\n"
        f"- 风险破坏位: {row.get('risk_break_level')}\n"
        f"- 系统原因: {row.get('signal_reason') or '无'}\n"
        f"- 仓位纪律: {discipline_snapshot.get('regime', 'UNKNOWN')}\n"
        f"- 纪律摘要: {discipline_snapshot.get('summary') or '无'}\n"
        f"- 最近变化: {change_context}\n\n"
        "输出要求：\n"
        "1. 用 3-5 个简短要点。\n"
        "2. 明确说明为什么是现在这个动作，而不是买更多或更少。\n"
        "3. 最后给一句“何时这个判断会失效”。\n"
        "4. 不要编造外部信息。"
    )
    return [
        {
            "role": "system",
            "content": "You are a concise portfolio co-pilot. Explain only from the provided portfolio and signal context. Do not invent external facts.",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_satellite_explanation_messages(
    *,
    candidate_row: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    change_feed: Optional[Mapping] = None,
):
    row = dict(candidate_row or {})
    discipline_snapshot = dict(discipline_snapshot or {})
    change_feed = dict(change_feed or {})
    symbol = str(row.get("symbol") or "").strip().upper() or "UNKNOWN"
    title_bits = []
    for item in list(change_feed.get("high_items", []) or []):
        if str(item.get("symbol") or "").strip().upper() == symbol:
            title_bits.append(f"{item.get('title', '')}: {item.get('message', '')}".strip(": "))
    change_context = " | ".join(title_bits[:2]) or "无新的高优先级变化。"
    mc = dict(row.get("monte_carlo", {}) or {})
    user_prompt = (
        f"请用简洁中文解释为什么系统当前把 {symbol} 放入卫星仓候选 / Top 3。\n"
        f"- 当前状态: {row.get('recommendation_status') or row.get('candidate_state') or 'WATCH'}\n"
        f"- 计划动作: {row.get('plan_action') or 'HOLD'}\n"
        f"- 建议仓位: {row.get('suggested_weight_pct')}\n"
        f"- 综合分: {row.get('satellite_score')}\n"
        f"- Top3 状态: {row.get('top3_membership_state')}\n"
        f"- 已驻留天数: {row.get('top3_residency_days')}\n"
        f"- 推荐原因: {row.get('recommendation_reason') or row.get('signal_reason') or '无'}\n"
        f"- 风险提示: {row.get('risk_note') or row.get('exit_reason') or '无'}\n"
        f"- 预期回报: {mc.get('expected_return')}\n"
        f"- 纪律状态: {discipline_snapshot.get('regime', 'UNKNOWN')}\n"
        f"- 最近变化: {change_context}\n\n"
        "输出要求：\n"
        "1. 用 3-5 个简短要点。\n"
        "2. 明确说明它为什么值得关注，以及为什么不是更激进或更保守。\n"
        "3. 最后给一句“什么情况下这个候选会失效或降级”。\n"
        "4. 不要编造外部信息。"
    )
    return [
        {
            "role": "system",
            "content": "You are a concise satellite-selection co-pilot. Explain only from the provided structured candidate context. Do not invent external facts.",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_change_feed_messages(
    *,
    change_feed: Mapping,
    monthly_discipline_review: Optional[Mapping] = None,
    mode: str = "explanation",
):
    feed = dict(change_feed or {})
    monthly_discipline_review = dict(monthly_discipline_review or {})
    mode = str(mode or "explanation").strip().lower()
    high_items = list(feed.get("high_items", []) or [])
    medium_items = list(feed.get("medium_items", []) or [])

    bullet_lines = []
    for item in high_items[:4] + medium_items[:3]:
        bullet_lines.append(
            f"- [{item.get('priority', 'LOW')}] {item.get('category', 'general')} | "
            f"{item.get('title', '')} | {item.get('explanation_summary') or item.get('message', '')}"
        )
        for bullet in list(item.get("explanation_bullets", []) or [])[:3]:
            bullet_lines.append(f"  * {bullet}")

    monthly_summary = str(monthly_discipline_review.get("summary") or "").strip() or "无"
    if mode == "narration":
        user_prompt = (
            "请把下面这些结构化变化原因，转述成一段更自然、简洁、适合人快速阅读的中文摘要。\n"
            "注意：只能改写和压缩，不要补充新的推断，不要引入外部信息。\n\n"
            f"变化总数：high={int(dict(feed.get('summary', {}) or {}).get('high_count', 0) or 0)}, "
            f"medium={int(dict(feed.get('summary', {}) or {}).get('medium_count', 0) or 0)}\n"
            f"月度纪律摘要：{monthly_summary}\n"
            "变化明细：\n"
            + "\n".join(bullet_lines[:18])
        )
        system_prompt = "You are a concise financial narration assistant. Rewrite only from the supplied structured reasons. Do not infer new causes."
    else:
        user_prompt = (
            "请基于下面这些结构化变化原因，解释今天最重要的变化意味着什么。\n"
            "要求：\n"
            "1. 先总结最重要的 2-3 个变化；\n"
            "2. 明确说明这些变化更偏向风险、节奏还是机会；\n"
            "3. 最后说明今天最该注意什么；\n"
            "4. 不要编造外部事实。\n\n"
            f"月度纪律摘要：{monthly_summary}\n"
            "变化明细：\n"
            + "\n".join(bullet_lines[:18])
        )
        system_prompt = "You are a portfolio analyst. Explain only from the provided structured change-feed reasons. Do not invent external facts."
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_discipline_review_messages(
    *,
    review: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    latest_post_close_review: Optional[Mapping] = None,
    mode: str = "explanation",
):
    review = dict(review or {})
    discipline_snapshot = dict(discipline_snapshot or {})
    latest_post_close_review = dict(latest_post_close_review or {})
    mode = str(mode or "explanation").strip().lower()

    rows = list(review.get("rows", []) or [])
    row_lines = [
        f"- {row.get('检查项', row.get('Check', ''))}: {row.get('观察', row.get('Value', ''))}"
        for row in rows[:14]
    ]
    notes = [str(item).strip() for item in list(review.get("notes", []) or []) if str(item).strip()]
    notes_block = "\n".join(f"- {item}" for item in notes[:6]) or "- 无"

    if mode == "narration":
        user_prompt = (
            "请把下面这份纪律层月度复盘，用更自然、易读的中文转述出来。\n"
            "注意：只能转述已有结构化信息，不要增加新的判断。\n\n"
            f"纪律状态：{discipline_snapshot.get('regime', 'UNKNOWN')}\n"
            f"月度状态：{review.get('status', 'MONITOR')}\n"
            f"月度摘要：{review.get('summary', '无')}\n"
            "关键指标：\n"
            + "\n".join(row_lines)
            + "\n补充说明：\n"
            + notes_block
        )
        system_prompt = "You are a concise financial narration assistant. Rewrite the structured discipline review into natural wording without adding new conclusions."
    else:
        user_prompt = (
            "请基于下面这份结构化纪律层月度复盘，解释当前纪律状态意味着什么。\n"
            "要求：\n"
            "1. 先解释 FOLLOW / IGNORE 结构是否健康；\n"
            "2. 说明最近的执行复盘是否支持当前纪律结论；\n"
            "3. 给出一句接下来应如何调整执行习惯；\n"
            "4. 不要编造外部事实。\n\n"
            f"纪律状态：{discipline_snapshot.get('regime', 'UNKNOWN')}\n"
            f"月度状态：{review.get('status', 'MONITOR')}\n"
            f"月度摘要：{review.get('summary', '无')}\n"
            f"最近执行复盘：executed={int(latest_post_close_review.get('executed_count', 0) or 0)}, "
            f"missed={int(latest_post_close_review.get('missed_count', 0) or 0)}, "
            f"unplanned={int(latest_post_close_review.get('unplanned_trade_count', 0) or 0)}\n"
            "关键指标：\n"
            + "\n".join(row_lines)
            + "\n补充说明：\n"
            + notes_block
        )
        system_prompt = "You are a portfolio discipline analyst. Explain only from the structured discipline-review data. Do not invent external facts."
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_news_summary_messages(*, summary_payload: Mapping, mode: str = "narration"):
    payload = dict(summary_payload or {})
    mode = str(mode or "narration").strip().lower()
    overview = str(payload.get("overview") or "").strip() or "无"
    focus_points = [str(item).strip() for item in list(payload.get("focus_points", []) or []) if str(item).strip()]
    theme_focuses = list(payload.get("theme_focuses", []) or [])
    theme_lines = []
    for row in theme_focuses[:5]:
        row = dict(row or {})
        label = str(row.get("label_zh") or row.get("label_en") or row.get("theme_key") or "").strip()
        summary = str(row.get("summary_zh") or row.get("summary_en") or "").strip()
        headlines = " | ".join(str(item).strip() for item in list(row.get("top_headlines", []) or [])[:2] if str(item).strip())
        line = f"- {label}: {summary}"
        if headlines:
            line += f" | 代表新闻: {headlines}"
        theme_lines.append(line)

    if mode == "narration":
        system_prompt = (
            "You are a concise financial narration assistant. Rewrite only from the provided structured news summary. "
            "Do not add new facts, predictions, or external causes."
        )
        user_prompt = (
            "请把下面这份结构化新闻/事件摘要，转述成一段更自然、更容易快速阅读的中文。\n"
            "要求：\n"
            "1. 只做整理和改写，不要新增判断依据；\n"
            "2. 突出今天最重要的 2-3 个焦点；\n"
            "3. 结尾点出“当前最值得盯的风险或机会”；\n"
            "4. 控制在 4 句以内。\n\n"
            f"总览：{overview}\n"
            "焦点：\n"
            + "\n".join(f"- {item}" for item in focus_points[:4])
            + "\n主题聚合：\n"
            + "\n".join(theme_lines[:5])
        )
    else:
        system_prompt = (
            "You are a market news analyst. Explain only from the structured news summary provided. "
            "Do not invent external facts."
        )
        user_prompt = (
            "请基于下面这份结构化新闻/事件摘要，解释今天新闻面最重要的变化意味着什么。\n"
            "要求：\n"
            "1. 先总结主导情绪与主导主题；\n"
            "2. 说明更偏向系统性风险、行业事件还是个股驱动；\n"
            "3. 最后给一句盘中最该注意什么；\n"
            "4. 不要编造外部事实。\n\n"
            f"总览：{overview}\n"
            "焦点：\n"
            + "\n".join(f"- {item}" for item in focus_points[:4])
            + "\n主题聚合：\n"
            + "\n".join(theme_lines[:5])
        )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_portfolio_news_messages(*, news_payload: Mapping):
    payload = dict(news_payload or {})
    analyst_context = dict(payload.get("analyst_context", {}) or {})
    impacts = []
    for row in list(payload.get("portfolio_impacts", []) or [])[:10]:
        row = dict(row or {})
        evidence_titles = []
        for item in list(row.get("evidence", []) or [])[:2]:
            if isinstance(item, Mapping):
                title = str(item.get("title") or "").strip()
            else:
                title = str(item or "").strip()
            if title:
                evidence_titles.append(title)
        evidence = " | ".join(evidence_titles)
        impacts.append(
            f"- {row.get('symbol')}: direction={row.get('direction')}, relevance={row.get('relevance_score')}, "
            f"confidence={row.get('confidence')}, risk_action={row.get('risk_action')}, evidence={evidence or 'none'}"
        )
    analyst_lines = [
        f"- {row.get('symbol')}: signal={row.get('signal')}, analysts={row.get('total_analysts')}, "
        f"bullish={row.get('bullish_ratio')}, bearish={row.get('bearish_ratio')}, source={row.get('source')}"
        for row in list(analyst_context.get("records", []) or [])[:10]
    ]
    user_prompt = (
        "请基于下面的结构化新闻证据和分析师共识，生成一段面向当前投资组合的中文解读。\n"
        "要求：\n"
        "1. 先给 2-4 句执行摘要，再列出最多 3 个最重要的标的影响；\n"
        "2. 区分公司事件和系统性宏观风险；\n"
        "3. 分析师输入只是推荐数量统计，不是研报正文，不要伪装成读过研报；\n"
        "4. 只能解释证据，不得改变量化动作、编造目标价或给出自主交易指令；\n"
        "5. 明确指出证据冲突或低置信度。\n\n"
        f"新闻总览：{payload.get('overview') or '无'}\n"
        f"市场风险级别：{payload.get('market_risk_level') or 'UNKNOWN'}\n"
        "组合影响：\n"
        + ("\n".join(impacts) or "- 无")
        + "\n分析师结构化共识：\n"
        + ("\n".join(analyst_lines) or "- 无覆盖")
    )
    return [
        {
            "role": "system",
            "content": "You are a portfolio news analyst. Use only supplied evidence, preserve uncertainty, and never invent report content or prices.",
        },
        {"role": "user", "content": user_prompt},
    ]


def build_portfolio_risk_messages(*, risk_payload: Mapping, news_intelligence: Optional[Mapping] = None):
    risk_payload = dict(risk_payload or {})
    news_intelligence = dict(news_intelligence or {})
    account = dict(risk_payload.get("account", {}) or {})
    risk_lines = [
        f"- {row.get('level')}: {row.get('category')} | {row.get('message')} | action={row.get('action')}"
        for row in list(risk_payload.get("risk_items", []) or [])[:10]
    ]
    news_lines = [
        f"- {row.get('symbol')}: {row.get('direction')} | confidence={row.get('confidence')} | {row.get('summary')}"
        for row in list(news_intelligence.get("portfolio_impacts", []) or [])[:5]
    ]
    return [
        {
            "role": "system",
            "content": "You are a portfolio risk analyst. Explain supplied controls and evidence only. Never invent prices or override the risk gate.",
        },
        {
            "role": "user",
            "content": (
                "请解释当前组合纪律与风险状态。\n"
                "要求：先说明最重要的风险，再说明哪些只是观察项，最后给出执行时应遵守的纪律。"
                "不要改写系统限制，不要补充外部事实。\n\n"
                f"纪律状态：{risk_payload.get('regime') or 'UNKNOWN'}\n"
                f"风险状态：{risk_payload.get('risk_regime') or 'UNKNOWN'}\n"
                f"总资产：{account.get('total_capital')}，现金：{account.get('cash_available')}，暴露：{account.get('exposure_pct')}%\n"
                "风险条目：\n"
                + ("\n".join(risk_lines) or "- 无")
                + "\n新闻影响：\n"
                + ("\n".join(news_lines) or "- 无")
            ),
        },
    ]


def _core_etf_cache_key(
    *,
    symbol_row: Mapping,
    discipline_snapshot: Optional[Mapping],
    change_feed: Optional[Mapping],
    route_name: str,
    model_name: str,
):
    payload = {
        "symbol": dict(symbol_row or {}).get("symbol"),
        "action": dict(symbol_row or {}).get("action"),
        "target_weight_pct": dict(symbol_row or {}).get("target_weight_pct"),
        "target_weight_range_low_pct": dict(symbol_row or {}).get("target_weight_range_low_pct"),
        "target_weight_range_high_pct": dict(symbol_row or {}).get("target_weight_range_high_pct"),
        "rotation_score": dict(symbol_row or {}).get("rotation_score"),
        "signal_reason": dict(symbol_row or {}).get("signal_reason"),
        "discipline_regime": dict(discipline_snapshot or {}).get("regime"),
        "discipline_summary": dict(discipline_snapshot or {}).get("summary"),
        "change_generated_at": dict(change_feed or {}).get("generated_at"),
        "route_name": route_name,
        "model_name": model_name,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"core_etf::{digest}"


def _generic_cache_key(*, kind: str, payload: Mapping, route_name: str, model_name: str, mode: str):
    normalized_payload = {
        "kind": str(kind or "").strip(),
        "mode": str(mode or "").strip(),
        "route_name": str(route_name or "").strip(),
        "model_name": str(model_name or "").strip(),
        "payload": dict(payload or {}),
    }
    digest = hashlib.sha256(json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{kind}::{digest}"


def _call_openai_chat(messages, route_config: Mapping, *, urlopen=None):
    if urlopen is None:
        return oai.call_openai_compatible_chat(messages, route_config)
    return oai.call_openai_compatible_chat(messages, route_config, urlopen=urlopen)


def _run_route_candidates_with_cache(
    *,
    cache_kind: str,
    cache_payload: Mapping,
    messages,
    notification_config: Mapping,
    complexity: str,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
    cache_key_fn=None,
    cache_extra: Optional[Mapping] = None,
):
    routes = list_llm_routes(notification_config, complexity=complexity)
    if not routes:
        return False, "尚未配置可用的远程 LLM 或本地 SLM。", {"route_name": "", "model": ""}

    cache = load_explanation_cache(path=cache_path)
    fallback_attempts = []
    last_error = ""
    for route_name, route_config in routes:
        route_config = dict(route_config or {})
        model_name = str(route_config.get("model") or "").strip()
        if cache_key_fn is not None:
            cache_key = cache_key_fn(route_name, route_config)
        else:
            cache_key = _generic_cache_key(
                kind=cache_kind,
                payload=cache_payload,
                route_name=route_name,
                model_name=model_name,
                mode=complexity,
            )
        cached = dict(cache.get(cache_key, {}) or {})
        if str(cached.get("text") or "").strip():
            return True, str(cached.get("text") or "").strip(), {
                "route_name": route_name,
                "model": model_name,
                "cached": True,
                "fallback_attempts": fallback_attempts,
            }

        ok, text = _call_openai_chat(messages, route_config, urlopen=urlopen)
        if ok:
            cache[cache_key] = {
                "kind": cache_kind,
                "route_name": route_name,
                "model": model_name,
                "created_at": datetime.now().isoformat(),
                "text": text,
                "fallback_attempts": fallback_attempts,
                **dict(cache_extra or {}),
            }
            save_explanation_cache(cache, path=cache_path)
            return True, text, {
                "route_name": route_name,
                "model": model_name,
                "cached": False,
                "fallback_attempts": fallback_attempts,
            }
        last_error = str(text or "").strip()
        fallback_attempts.append(
            {
                "route_name": route_name,
                "model": model_name,
                "error": last_error,
            }
        )

    last_route_name, last_route_config = routes[-1]
    return False, last_error or "LLM 调用失败", {
        "route_name": last_route_name,
        "model": str(dict(last_route_config or {}).get("model") or "").strip(),
        "cached": False,
        "fallback_attempts": fallback_attempts,
    }


def explain_core_etf_decision(
    *,
    symbol_row: Mapping,
    notification_config: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    change_feed: Optional[Mapping] = None,
    complexity: str = "explanation",
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_core_etf_explanation_messages(
        symbol_row=symbol_row,
        discipline_snapshot=discipline_snapshot,
        change_feed=change_feed,
    )
    return _run_route_candidates_with_cache(
        cache_kind="core_etf_explanation",
        cache_payload={},
        messages=messages,
        notification_config=notification_config,
        complexity=complexity,
        cache_path=cache_path,
        urlopen=urlopen,
        cache_key_fn=lambda route_name, route_config: _core_etf_cache_key(
            symbol_row=symbol_row,
            discipline_snapshot=discipline_snapshot,
            change_feed=change_feed,
            route_name=route_name,
            model_name=str(dict(route_config or {}).get("model") or "").strip(),
        ),
        cache_extra={"symbol": str(dict(symbol_row or {}).get("symbol") or "").strip().upper()},
    )


def explain_satellite_candidate(
    *,
    candidate_row: Mapping,
    notification_config: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    change_feed: Optional[Mapping] = None,
    complexity: str = "explanation",
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_satellite_explanation_messages(
        candidate_row=candidate_row,
        discipline_snapshot=discipline_snapshot,
        change_feed=change_feed,
    )
    return _run_messages_with_cache(
        cache_kind="satellite_candidate_explanation",
        cache_payload={
            "symbol": dict(candidate_row or {}).get("symbol"),
            "recommendation_status": dict(candidate_row or {}).get("recommendation_status"),
            "candidate_state": dict(candidate_row or {}).get("candidate_state"),
            "plan_action": dict(candidate_row or {}).get("plan_action"),
            "suggested_weight_pct": dict(candidate_row or {}).get("suggested_weight_pct"),
            "satellite_score": dict(candidate_row or {}).get("satellite_score"),
            "membership_state": dict(candidate_row or {}).get("top3_membership_state"),
            "residency_days": dict(candidate_row or {}).get("top3_residency_days"),
            "reason": dict(candidate_row or {}).get("recommendation_reason") or dict(candidate_row or {}).get("signal_reason"),
            "discipline_regime": dict(discipline_snapshot or {}).get("regime"),
            "change_generated_at": dict(change_feed or {}).get("generated_at"),
        },
        messages=messages,
        notification_config=notification_config,
        complexity=complexity,
        cache_path=cache_path,
        urlopen=urlopen,
        cache_extra={"symbol": str(dict(candidate_row or {}).get("symbol") or "").strip().upper()},
    )


def _run_messages_with_cache(
    *,
    cache_kind: str,
    cache_payload: Mapping,
    messages,
    notification_config: Mapping,
    complexity: str,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
    cache_extra: Optional[Mapping] = None,
):
    return _run_route_candidates_with_cache(
        cache_kind=cache_kind,
        cache_payload=cache_payload,
        messages=messages,
        notification_config=notification_config,
        complexity=complexity,
        cache_path=cache_path,
        urlopen=urlopen,
        cache_extra=cache_extra,
    )


def narrate_change_feed(
    *,
    change_feed: Mapping,
    notification_config: Mapping,
    monthly_discipline_review: Optional[Mapping] = None,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_change_feed_messages(
        change_feed=change_feed,
        monthly_discipline_review=monthly_discipline_review,
        mode="narration",
    )
    return _run_messages_with_cache(
        cache_kind="change_feed_narration",
        cache_payload={
            "generated_at": dict(change_feed or {}).get("generated_at"),
            "summary": dict(dict(change_feed or {}).get("summary", {}) or {}),
            "high_items": list(dict(change_feed or {}).get("high_items", []) or []),
            "medium_items": list(dict(change_feed or {}).get("medium_items", []) or []),
            "monthly_status": dict(monthly_discipline_review or {}).get("status"),
            "monthly_summary": dict(monthly_discipline_review or {}).get("summary"),
        },
        messages=messages,
        notification_config=notification_config,
        complexity="narration",
        cache_path=cache_path,
        urlopen=urlopen,
    )


def explain_change_feed(
    *,
    change_feed: Mapping,
    notification_config: Mapping,
    monthly_discipline_review: Optional[Mapping] = None,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_change_feed_messages(
        change_feed=change_feed,
        monthly_discipline_review=monthly_discipline_review,
        mode="explanation",
    )
    return _run_messages_with_cache(
        cache_kind="change_feed_explanation",
        cache_payload={
            "generated_at": dict(change_feed or {}).get("generated_at"),
            "summary": dict(dict(change_feed or {}).get("summary", {}) or {}),
            "high_items": list(dict(change_feed or {}).get("high_items", []) or []),
            "medium_items": list(dict(change_feed or {}).get("medium_items", []) or []),
            "monthly_status": dict(monthly_discipline_review or {}).get("status"),
            "monthly_summary": dict(monthly_discipline_review or {}).get("summary"),
        },
        messages=messages,
        notification_config=notification_config,
        complexity="explanation",
        cache_path=cache_path,
        urlopen=urlopen,
    )


def narrate_discipline_review(
    *,
    review: Mapping,
    notification_config: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    latest_post_close_review: Optional[Mapping] = None,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_discipline_review_messages(
        review=review,
        discipline_snapshot=discipline_snapshot,
        latest_post_close_review=latest_post_close_review,
        mode="narration",
    )
    return _run_messages_with_cache(
        cache_kind="discipline_review_narration",
        cache_payload={
            "month": dict(review or {}).get("month"),
            "status": dict(review or {}).get("status"),
            "summary": dict(review or {}).get("summary"),
            "follow_days": dict(review or {}).get("follow_days"),
            "ignore_days": dict(review or {}).get("ignore_days"),
            "discipline_regime": dict(discipline_snapshot or {}).get("regime"),
        },
        messages=messages,
        notification_config=notification_config,
        complexity="narration",
        cache_path=cache_path,
        urlopen=urlopen,
    )


def explain_discipline_review(
    *,
    review: Mapping,
    notification_config: Mapping,
    discipline_snapshot: Optional[Mapping] = None,
    latest_post_close_review: Optional[Mapping] = None,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_discipline_review_messages(
        review=review,
        discipline_snapshot=discipline_snapshot,
        latest_post_close_review=latest_post_close_review,
        mode="explanation",
    )
    return _run_messages_with_cache(
        cache_kind="discipline_review_explanation",
        cache_payload={
            "month": dict(review or {}).get("month"),
            "status": dict(review or {}).get("status"),
            "summary": dict(review or {}).get("summary"),
            "follow_days": dict(review or {}).get("follow_days"),
            "ignore_days": dict(review or {}).get("ignore_days"),
            "discipline_regime": dict(discipline_snapshot or {}).get("regime"),
            "unplanned_trade_count": dict(latest_post_close_review or {}).get("unplanned_trade_count"),
        },
        messages=messages,
        notification_config=notification_config,
        complexity="explanation",
        cache_path=cache_path,
        urlopen=urlopen,
    )


def narrate_news_summary(
    *,
    summary_payload: Mapping,
    notification_config: Mapping,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    messages = build_news_summary_messages(summary_payload=summary_payload, mode="narration")
    return _run_messages_with_cache(
        cache_kind="news_summary_narration",
        cache_payload=dict(summary_payload or {}),
        messages=messages,
        notification_config=notification_config,
        complexity="narration",
        cache_path=cache_path,
        urlopen=urlopen,
    )


def analyze_portfolio_news(
    *,
    news_payload: Mapping,
    notification_config: Mapping,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    return _run_messages_with_cache(
        cache_kind="portfolio_news_analysis",
        cache_payload=dict(news_payload or {}),
        messages=build_portfolio_news_messages(news_payload=news_payload),
        notification_config=notification_config,
        complexity="analysis",
        cache_path=cache_path,
        urlopen=urlopen,
    )


def explain_portfolio_risk(
    *,
    risk_payload: Mapping,
    notification_config: Mapping,
    news_intelligence: Optional[Mapping] = None,
    cache_path: str = DEFAULT_EXPLANATION_CACHE_FILE,
    urlopen=None,
):
    return _run_messages_with_cache(
        cache_kind="portfolio_risk_explanation",
        cache_payload={
            "risk": dict(risk_payload or {}),
            "news": dict(news_intelligence or {}),
        },
        messages=build_portfolio_risk_messages(
            risk_payload=risk_payload,
            news_intelligence=news_intelligence,
        ),
        notification_config=notification_config,
        complexity="analysis",
        cache_path=cache_path,
        urlopen=urlopen,
    )
