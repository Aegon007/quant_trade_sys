from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from quant_core import paths as qpaths
from quant_core.api import snapshot_loader
from quant_core.data import prices
from quant_core.data.data_health import build_data_health_snapshot, save_data_health_snapshot
from quant_core.data.watchlist import add_to_watchlist, remove_from_watchlist
from quant_core.jobs import job_registry
from quant_core.llm import openai_compatible
from quant_core.notifications import notification_config
from quant_core.notifications import notification_channels
from quant_core.research.service import run_full_valuation_research, save_valuation_policy
from quant_core.research.universe import build_research_universe, save_universe_config
from quant_core.risk.market_regime import build_market_risk_snapshot, save_market_risk_snapshot


def _summary(payload) -> dict:
    value = dict(payload or {}) if isinstance(payload, Mapping) else {}
    return dict(
        value.get("summary", {})
        or {
            key: value.get(key)
            for key in ("status", "ran", "generated_at", "route", "channel", "model", "message")
            if value.get(key) is not None
        }
    )


def build_job_progress_callback(name: str):
    def report(stage: str, progress_pct: int, detail: str, **metadata):
        job_registry.update_job_status(name, state="running", detail=detail, metadata={"stage": stage, "progress_pct": progress_pct, **metadata})
    return report


def _job_group(name: str) -> str:
    lowered = str(name).lower()
    if "nightly" in lowered or "full-research" in lowered:
        return "valuation-research"
    if "weekend" in lowered:
        return "weekend-calibration"
    if "market-refresh" in lowered:
        return "market-refresh"
    return lowered.replace("/", "-")


@contextmanager
def _exclusive_job(name: str):
    path = qpaths.RESEARCH_STATE_DIR / f".{_job_group(name)}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    for attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"pid={os.getpid()} started={datetime.now().isoformat()}\n".encode("utf-8"))
            break
        except FileExistsError:
            if attempt == 0 and time.time() - path.stat().st_mtime > 12 * 3600:
                path.unlink(missing_ok=True)
                continue
    try:
        yield descriptor is not None
    finally:
        if descriptor is not None:
            os.close(descriptor)
            path.unlink(missing_ok=True)


def run_with_job_status(name: str, runner: Callable, *, run_async: bool = True) -> dict:
    registry = job_registry.mark_stale_jobs(job_registry.load_job_status())
    current = dict(registry.get("jobs", {}).get(name, {}) or {})
    if str(current.get("state") or "").lower() in {"queued", "started", "running"}:
        return {"accepted": False, "error": "任务已经在运行", "job": current}
    job_registry.update_job_status(name, state="queued", detail="任务已进入队列", metadata={"stage": "queued", "progress_pct": 0})

    outcome = {}

    def execute():
        job_registry.update_job_status(name, state="running", detail="任务开始", metadata={"stage": "starting", "progress_pct": 1})
        with _exclusive_job(name) as acquired:
            if not acquired:
                job_registry.update_job_status(name, state="failed", detail="同类任务已在另一个入口运行", metadata={"stage": "blocked", "progress_pct": 100})
                return
            try:
                result = runner()
            except Exception as exc:
                outcome["error"] = f"{type(exc).__name__}: {exc}"
                job_registry.update_job_status(name, state="failed", detail=f"{type(exc).__name__}: {exc}", metadata={"stage": "failed", "progress_pct": 100})
                return
        outcome["result"] = result
        result_detail = str(dict(result or {}).get("message") or "任务完成") if isinstance(result, Mapping) else "任务完成"
        job_registry.update_job_status(name, state="completed", detail=result_detail, metadata={"stage": "completed", "progress_pct": 100, "result_summary": _summary(result)})

    if run_async:
        threading.Thread(target=execute, name=f"quant-{name}", daemon=True).start()
        return {"accepted": True, "job_name": name, "state": "queued"}
    execute()
    job = dict(job_registry.load_job_status().get("jobs", {}).get(name, {}) or {})
    result = dict(outcome.get("result", {}) or {}) if isinstance(outcome.get("result"), Mapping) else {}
    return {"accepted": job.get("state") == "completed", "job_name": name, "job": job, **result, **({"error": outcome["error"]} if outcome.get("error") else {})}


def refresh_market_data_now(*, force_source_refresh: bool = True) -> dict:
    universe = build_research_universe()
    symbols = [str(row.get("symbol") or "") for row in universe]
    resolved = prices.fetch_latest_prices(symbols, force=force_source_refresh)
    histories = {
        symbol: prices.get_history(symbol, period="1y", force=force_source_refresh)
        for symbol in ("SPY", "QQQ", "^VIX")
    }
    market_risk = build_market_risk_snapshot(histories)
    save_market_risk_snapshot(market_risk)
    health = build_data_health_snapshot(
        opportunities=snapshot_loader._load(qpaths.OPPORTUNITY_SNAPSHOT_FILE),
        valuations=snapshot_loader._load(qpaths.VALUATION_SNAPSHOT_FILE),
        market_risk=market_risk,
        require_llm_route=bool(snapshot_loader.load_settings_response()["payload"]["valuation_policy"].get("require_llm_route_for_action", False)),
    )
    save_data_health_snapshot(health)
    return {"status": "READY", "summary": {"requested_count": len(symbols), "refreshed_count": len(resolved), "market_regime": market_risk.get("regime")}}


def run_nightly_once(*, progress=None) -> dict:
    return run_full_valuation_research(force=True, progress=progress or build_job_progress_callback("manual-nightly-run"), notify=True)


def run_weekend_research_once(*, progress=None) -> dict:
    from jobs.weekend_research import run_weekend_research
    return run_weekend_research(force=True, progress=progress or build_job_progress_callback("manual-weekend-research"), notify=True)


def test_llm_settings(*, route: str, submitted_config: Mapping | None = None) -> dict:
    existing = notification_config.load_notification_config()
    config = notification_config.preserve_unsubmitted_secrets(submitted_config, existing) if submitted_config else existing
    config = notification_config.apply_environment_overrides(config)
    selected = dict(config.get("local_slm" if str(route).lower() == "local_slm" else "llm", {}) or {})
    ok, message = openai_compatible.test_llm_connection(selected)
    if not ok:
        raise RuntimeError(message)
    return {"status": "READY", "route": route, "message": message, "model": selected.get("model")}


def test_notification_channel(channel: str, *, submitted_config: Mapping | None = None) -> dict:
    channel = str(channel or "").strip().lower()
    existing = notification_config.load_notification_config()
    config = notification_config.preserve_unsubmitted_secrets(submitted_config, existing) if submitted_config else existing
    config = notification_config.apply_environment_overrides(config)
    message = notification_channels.build_test_notification_message(channel)
    if channel == "slack":
        slack = dict(config.get("slack", {}) or {})
        if not slack.get("enabled") or not slack.get("webhook_url"):
            raise RuntimeError("Slack推送尚未启用或Webhook URL为空")
        ok, detail = notification_channels.send_slack_message(message, slack.get("webhook_url"))
    elif channel == "email":
        email = dict(config.get("email", {}) or {})
        if not email.get("enabled") or not email.get("to_emails"):
            raise RuntimeError("Email尚未启用或收件人为空")
        ok, detail = notification_channels.send_email_message("估值雷达连接测试", message, email)
    else:
        raise ValueError(f"不支持的通知渠道：{channel}")
    if not ok:
        raise RuntimeError(detail)
    return {"status": "READY", "channel": channel, "message": detail}


def explain_security(symbol: str) -> dict:
    symbol = str(symbol or "").strip().upper()
    valuation = snapshot_loader.load_valuations_response(symbol)["payload"]
    recommendations = snapshot_loader._load(qpaths.RECOMMENDATION_SNAPSHOT_FILE)
    row = next((dict(item) for item in list(recommendations.get("recommendations", []) or []) if str(item.get("symbol") or "").upper() == symbol), {})
    valuation_row = next(iter(list(valuation.get("valuations", []) or [])), {})
    if not row or not valuation_row:
        raise LookupError(f"没有 {symbol} 的最新估值结果")
    llm = dict(notification_config.load_notification_config().get("llm", {}) or {})
    messages = [
        {"role": "system", "content": "Explain the supplied valuation result in natural Chinese. Preserve all numbers, distinguish assumptions from facts, and do not create a new recommendation."},
        {"role": "user", "content": json.dumps({"recommendation": row, "valuation": valuation_row}, ensure_ascii=False, default=str)},
    ]
    ok, text = openai_compatible.call_openai_compatible_chat(messages, {**llm, "max_tokens": max(int(llm.get("max_tokens") or 300), 1800)})
    if not ok:
        raise RuntimeError(text)
    return {"status": "READY", "symbol": symbol, "explanation": text, "model": llm.get("model")}


def save_notification_settings(config: Mapping) -> dict:
    existing = notification_config.load_notification_config()
    merged = notification_config.preserve_unsubmitted_secrets(dict(config or {}), existing)
    saved = notification_config.save_notification_config(merged)
    return {"status": "READY", "message": "通知与LLM设置已保存", "notification_config": snapshot_loader._sanitize(saved)}


def save_runtime_schedule(schedule: Mapping) -> dict:
    path = snapshot_loader.save_runtime_schedule(schedule)
    return {"status": "READY", "path": path, "runtime_schedule": snapshot_loader.load_runtime_schedule()}


def save_research_universe(config: Mapping) -> dict:
    path = save_universe_config(config)
    return {"status": "READY", "path": path, "research_universe": snapshot_loader.load_settings_response()["payload"]["research_universe"]}


def save_valuation_settings(config: Mapping) -> dict:
    path = save_valuation_policy(config)
    return {"status": "READY", "path": path, "valuation_policy": dict(config or {})}


def update_watchlist(symbol: str, *, remove: bool = False) -> dict:
    symbols = remove_from_watchlist(symbol) if remove else add_to_watchlist(symbol)
    return {"status": "READY", "symbols": symbols, "message": f"{str(symbol).upper()} 已{'移出' if remove else '加入'}关注列表"}
