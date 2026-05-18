"""Unified supervisor that starts the UI, Slack bot, and nightly scheduler."""

from __future__ import annotations

import argparse
import copy
import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from quant_core.analytics import quant_analysis as qa
from quant_core.analytics import portfolio_analysis as qpa
from quant_core.data import market_data as md
from quant_core.data import storage as data_storage
from quant_core.events.analyst_consensus import should_run_nightly_consensus_update
from quant_core.events import event_news as en
from quant_core.execution import nightly_planner as np
from quant_core.ledger import transactions as tx
from quant_core.monitoring import intraday_journal as ij
from quant_core.monitoring import intraday_monitor as im
from quant_core.notifications import change_feed as cfeed
from quant_core.notifications import notification_channels as nch
from quant_core.notifications import notification_config as ncfg
from quant_core.notifications import delivery_router as dr
from quant_core.notifications import reporting as nr
from quant_core.portfolio import discipline as qdisc
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from quant_core.snapshots import system_snapshot as ss
from jobs.nightly_alerts import evaluate_current_market_risk, run_nightly_alerts
from signal_scoreboard import build_signal_scoreboard


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MONITOR_SECONDS = 10
DEFAULT_NIGHTLY_POLL_SECONDS = 300
DEFAULT_MARKET_REFRESH_POLL_SECONDS = 300
DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS = 3600
DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS = ncfg.DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS
DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT = ncfg.DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    command: List[str]
    cwd: str


@dataclass(frozen=True)
class ServiceStartupStatus:
    name: str
    state: str
    detail: str
    pid: Optional[int] = None

    def format_line(self) -> str:
        state_label = {
            "started": "OK",
            "skipped": "SKIP",
            "failed": "FAIL",
        }.get(self.state.lower(), self.state.upper())
        pid_fragment = f" pid={self.pid}" if self.pid is not None else ""
        return f"[{state_label}] {self.name}{pid_fragment} - {self.detail}"


def _has_slack_credentials(environ=None) -> bool:
    environ = environ or os.environ
    return bool(str(environ.get("SLACK_BOT_TOKEN") or "").strip() and str(environ.get("SLACK_APP_TOKEN") or "").strip())


def build_service_specs(
    *,
    with_ui: bool = True,
    with_slack: bool = True,
    python_executable: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> List[ServiceSpec]:
    project_root = Path(project_root or PROJECT_ROOT)
    python_executable = python_executable or sys.executable
    specs: List[ServiceSpec] = []

    if with_slack:
        specs.append(
            ServiceSpec(
                name="slack-bot",
                command=[python_executable, "-m", "jobs.slack_bot"],
                cwd=str(project_root),
            )
        )

    if with_ui:
        specs.append(
            ServiceSpec(
                name="streamlit-ui",
                command=[python_executable, "-m", "streamlit", "run", str(project_root / "main.py")],
                cwd=str(project_root),
            )
        )

    return specs


def start_service_process(spec: ServiceSpec, *, popen=subprocess.Popen):
    return popen(spec.command, cwd=spec.cwd)


def emit_startup_summary(statuses, *, printer=print):
    statuses = list(statuses)
    if not statuses:
        return
    printer("Startup status:")
    for status in statuses:
        printer(status.format_line())


def maybe_run_nightly_alerts(
    *,
    now: Optional[datetime] = None,
    should_run: Callable[..., bool] = should_run_nightly_consensus_update,
    runner: Callable[..., object] = run_nightly_alerts,
    logger: Optional[logging.Logger] = None,
) -> bool:
    logger = logger or logging.getLogger(__name__)
    now = now or datetime.now()
    if not should_run(now=now):
        return False
    logger.info("Nightly alerts are due; running scheduled job.")
    runner(force=False, dry_run=False, now=now)
    return True


def _load_notification_config(config_loader, *, environ=None):
    try:
        base_config = config_loader()
    except TypeError:
        base_config = config_loader(ncfg.NOTIFICATION_CONFIG_FILE)
    return ncfg.apply_environment_overrides(base_config, environ=environ)


def _has_enabled_delivery_channel(config) -> bool:
    config = dict(config or {})
    slack = dict(config.get("slack", {}) or {})
    email = dict(config.get("email", {}) or {})
    return bool(
        (slack.get("enabled") and str(slack.get("webhook_url") or "").strip())
        or (email.get("enabled") and list(email.get("to_emails", []) or []))
    )


def _latest_monthly_discipline_review_from_journal(*, journal_entries):
    entries = list(journal_entries or [])
    if not entries:
        return {}
    latest_entry = dict(entries[-1] or {})
    return dict(latest_entry.get("monthly_discipline_review", {}) or {})


def _build_pending_intraday_discipline_alert(*, change_feed, monthly_discipline_review, state_path):
    alert = cfeed.build_intraday_discipline_month_alert(
        change_feed,
        monthly_discipline_review=monthly_discipline_review,
    )
    if not alert:
        return None
    previous_state = dict(cfeed.load_intraday_alert_state(path=state_path) or {})
    if str(previous_state.get("last_signature") or "").strip() == str(alert.get("signature") or "").strip():
        return None
    return alert


def _mark_intraday_discipline_alert_sent(*, alert, state_path, now):
    if not isinstance(alert, dict) or not str(alert.get("signature") or "").strip():
        return
    cfeed.save_intraday_alert_state(
        {
            "last_signature": str(alert.get("signature") or "").strip(),
            "last_sent_at": now.isoformat(),
            "last_title": str((list(alert.get("items", []) or [{}])[0] or {}).get("title") or "").strip(),
        },
        path=state_path,
    )


def _record_intraday_discipline_event(
    *,
    alert,
    monthly_discipline_review,
    discipline_snapshot,
    risk_decision,
    account_snapshot,
    now,
    was_alert_sent,
    send_context,
    skip_reason,
    journal_path,
):
    if not isinstance(alert, dict):
        return
    first_item = dict((list(alert.get("items", []) or [{}])[0]) or {})
    entry = ij.build_intraday_event_entry(
        event_type="DISCIPLINE_MONTH_DETERIORATION",
        priority="high",
        now=now,
        trigger_reason=str(first_item.get("title") or "discipline_month_alert").strip(),
        was_alert_sent=bool(was_alert_sent),
        send_context=send_context,
        skip_reason=skip_reason,
        payload={
            "alert_signature": str(alert.get("signature") or "").strip(),
            "alert_message": str(alert.get("message") or "").strip(),
            "discipline_regime": str(dict(discipline_snapshot or {}).get("regime") or "").strip(),
            "risk_regime": str(getattr(risk_decision, "regime", "") or dict(risk_decision or {}).get("regime") or "").strip(),
            "monthly_status": str(dict(monthly_discipline_review or {}).get("status") or "").strip(),
            "follow_days": int(dict(monthly_discipline_review or {}).get("follow_days") or 0),
            "ignore_days": int(dict(monthly_discipline_review or {}).get("ignore_days") or 0),
            "defensive_override_days": int(dict(monthly_discipline_review or {}).get("defensive_override_days") or 0),
            "cash_available": float(dict(account_snapshot or {}).get("cash_available") or 0.0),
            "exposure_pct": float(dict(account_snapshot or {}).get("exposure_pct") or 0.0),
        },
    )
    ij.append_intraday_event(entry, journal_path=journal_path)


def _build_pending_intraday_classifier_alert(*, events, now, state_path):
    alert = im.build_intraday_alert(events, now=now)
    if not alert:
        return None
    if not im.should_send_intraday_alert_signature(
        str(alert.get("signature") or "").strip(),
        now=now,
        path=state_path,
    ):
        return None
    return alert


def _record_intraday_classifier_events(
    *,
    alert,
    now,
    was_alert_sent,
    send_context,
    skip_reason,
    journal_path,
):
    if not isinstance(alert, dict):
        return
    for event in list(alert.get("events", []) or []):
        payload = dict(event.get("payload", {}) or {})
        payload.update(
            {
                "alert_signature": str(alert.get("signature") or "").strip(),
                "alert_message": str(alert.get("message") or "").strip(),
                "plan_action": event.get("plan_action"),
                "action_side": event.get("action_side"),
                "reason_codes": list(event.get("reason_codes", []) or []),
                "explanation_summary": event.get("explanation_summary"),
                "title": event.get("title"),
            }
        )
        entry = ij.build_intraday_event_entry(
            event_type=event.get("event_type"),
            priority=event.get("priority") or "high",
            now=now,
            symbol=event.get("symbol"),
            trigger_reason=event.get("trigger_reason") or event.get("title") or event.get("event_type"),
            was_alert_sent=bool(was_alert_sent),
            send_context=send_context,
            skip_reason=skip_reason,
            payload=payload,
        )
        ij.append_intraday_event(entry, journal_path=journal_path)


def maybe_run_market_refresh(
    *,
    now: Optional[datetime] = None,
    loader: Callable[[], dict] = data_storage.load_data,
    refresher: Callable[..., tuple] = data_storage.auto_refresh_market_data,
    saver: Callable[[dict], None] = data_storage.save_data,
    refresh_interval_seconds: int = DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS,
    config_loader: Callable[[], dict] = ncfg.load_notification_config,
    summary_builder: Callable[..., str] = nr.build_market_refresh_report,
    slack_sender: Callable[..., tuple] = nch.send_slack_message,
    email_sender: Callable[..., tuple] = nch.send_email_message,
    message_router: Callable[..., list] = dr.deliver_message,
    quant_analysis_snapshot_path: str = qpa.DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE,
    report_output_dir: str = nr.DEFAULT_REPORTS_DIR,
    intraday_alert_state_path: str = cfeed.DEFAULT_INTRADAY_ALERT_STATE_FILE,
    intraday_event_journal_path: str = ij.DEFAULT_INTRADAY_EVENT_JOURNAL_FILE,
    intraday_event_alert_state_path: str = im.DEFAULT_INTRADAY_EVENT_ALERT_STATE_FILE,
    auto_quant_analysis_min_interval_seconds: Optional[int] = None,
    auto_quant_analysis_price_jump_pct: Optional[float] = None,
    enable_auto_quant_analysis: Optional[bool] = None,
    environ=None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    logger = logger or logging.getLogger(__name__)
    now = now or datetime.now()
    data = loader()
    before_data = copy.deepcopy(data)
    refreshed_data, refreshed = refresher(
        data,
        refresh_interval_seconds=refresh_interval_seconds,
        now=now,
        force=False,
    )
    if not refreshed:
        return False
    saver(refreshed_data)
    config = _load_notification_config(config_loader, environ=environ)
    alert_settings = config.get("alert_settings", {}) if isinstance(config, dict) else {}
    slack_config = config.get("slack", {}) if isinstance(config, dict) else {}
    latest_change_feed = cfeed.load_change_feed() or {}
    latest_snapshot_journal = ss.load_snapshot_journal(limit=1)
    latest_trade_plan = np.load_next_day_trade_plan()
    latest_monthly_discipline_review = _latest_monthly_discipline_review_from_journal(
        journal_entries=latest_snapshot_journal
    )
    latest_discipline_snapshot = qdisc.load_discipline_snapshot() or {}
    intraday_alerts_enabled = bool(alert_settings.get("send_intraday_alerts", True))
    pending_intraday_discipline_alert = (
        _build_pending_intraday_discipline_alert(
            change_feed=latest_change_feed,
            monthly_discipline_review=latest_monthly_discipline_review,
            state_path=intraday_alert_state_path,
        )
        if intraday_alerts_enabled
        else None
    )
    notifications_enabled = _has_enabled_delivery_channel(config)
    try:
        resolved_auto_quant_analysis_min_interval_seconds = int(
            auto_quant_analysis_min_interval_seconds
            if auto_quant_analysis_min_interval_seconds is not None
            else alert_settings.get(
                "auto_quant_analysis_min_interval_seconds",
                DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS,
            )
        )
    except (TypeError, ValueError):
        resolved_auto_quant_analysis_min_interval_seconds = DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS
    try:
        resolved_auto_quant_analysis_price_jump_pct = float(
            auto_quant_analysis_price_jump_pct
            if auto_quant_analysis_price_jump_pct is not None
            else alert_settings.get(
                "auto_quant_analysis_price_jump_pct",
                DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT,
            )
        )
    except (TypeError, ValueError):
        resolved_auto_quant_analysis_price_jump_pct = DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT
    resolved_enable_auto_quant_analysis = (
        bool(enable_auto_quant_analysis)
        if enable_auto_quant_analysis is not None
        else bool(alert_settings.get("enable_auto_quant_analysis", True))
    )
    tracked_symbols = sorted(
        {
            str(item.get("symbol", "")).strip().upper()
            for item in (refreshed_data.get("holdings", []) + refreshed_data.get("watchlist", []))
            if item.get("symbol")
        }
    )

    try:
        account_snapshot = ss.build_account_snapshot(refreshed_data)
    except Exception:
        account_snapshot = {}
    try:
        risk_decision = evaluate_current_market_risk(refreshed_data, history_period="2y") if refreshed_data.get("holdings") else None
    except Exception:
        risk_decision = None
    try:
        raw_events = en.load_market_events(auto_bootstrap=True)
        active_events = en.select_active_events(raw_events, symbols=tracked_symbols, now=now, verified_only=False)
        event_decision = en.evaluate_event_risk_switch(active_events, verified_only=True, now=now, vix=None)
    except Exception:
        active_events = []
        event_decision = None
    try:
        transaction_rows = tx.normalize_transactions(tx.load_transactions())
    except Exception:
        transaction_rows = []
    try:
        benchmark_history = qa.get_historical_data("SPY", period="2y")
    except Exception:
        benchmark_history = None
    try:
        live_scoreboard = build_signal_scoreboard(transaction_rows, benchmark_history=benchmark_history)
    except Exception:
        live_scoreboard = None
    try:
        allocation_regime = evaluate_allocation_regime(
            live_scoreboard,
            risk_gate=risk_decision,
            account_snapshot=account_snapshot,
        )
    except Exception:
        allocation_regime = None
    intraday_classifier_events = im.classify_intraday_events(
        data=refreshed_data,
        trade_plan=latest_trade_plan,
        risk_gate=risk_decision,
        discipline_snapshot=latest_discipline_snapshot,
        active_events=active_events,
        event_decision=event_decision,
        now=now,
    )
    pending_intraday_classifier_alert = (
        _build_pending_intraday_classifier_alert(
            events=intraday_classifier_events,
            now=now,
            state_path=intraday_event_alert_state_path,
        )
        if intraday_alerts_enabled
        else None
    )

    previous_snapshot = None
    auto_trigger = {"should_run": False, "message": "Auto quant analysis disabled."}
    if resolved_enable_auto_quant_analysis:
        try:
            previous_snapshot = qpa.load_quant_analysis_snapshot(path=quant_analysis_snapshot_path)
            auto_trigger = qpa.evaluate_auto_refresh_trigger(
                before_data=before_data,
                after_data=refreshed_data,
                previous_snapshot=previous_snapshot,
                risk_decision=risk_decision,
                event_decision=event_decision,
                active_events=active_events,
                now=now,
                price_jump_threshold=resolved_auto_quant_analysis_price_jump_pct,
                min_interval_seconds=resolved_auto_quant_analysis_min_interval_seconds,
            )
        except Exception:
            logger.exception("Auto full-analysis trigger evaluation failed.")
            previous_snapshot = None
            auto_trigger = {"should_run": False, "message": "Auto trigger evaluation failed."}

        if auto_trigger.get("should_run"):
            try:
                runtime_strategy = qpa.load_default_runtime_strategy(history_period="2y")
                if runtime_strategy is not None:
                    analysis_snapshot = qpa.build_portfolio_quant_analysis_snapshot(
                        refreshed_data,
                        strategy=runtime_strategy,
                        history_period="2y",
                        engine_name="backtrader",
                        risk_gate=risk_decision,
                        allocation_regime=allocation_regime,
                        active_events=active_events,
                        event_decision=event_decision,
                        now=now,
                    )
                    qpa.save_quant_analysis_snapshot(analysis_snapshot, path=quant_analysis_snapshot_path)
                    analysis_report_text = nr.build_quant_analysis_report(analysis_snapshot)
                    nr.save_quant_analysis_report_files(
                        analysis_snapshot,
                        report_text=analysis_report_text,
                        reports_dir=report_output_dir,
                    )
                    if (
                        slack_config.get("enabled")
                        and slack_config.get("webhook_url")
                        and bool(alert_settings.get("send_quant_analysis_change_summary", True))
                    ):
                        change_summary = qpa.build_quant_analysis_change_summary(previous_snapshot, analysis_snapshot)
                        if change_summary.get("has_changes"):
                            message = auto_trigger.get("message", "")
                            if change_summary.get("message"):
                                message = f"{message}\n\n{change_summary['message']}".strip()
                            delivery_results = message_router(
                                "quant_analysis_change_summary",
                                subject=f"Quant Analysis Change Summary {now.strftime('%Y-%m-%d %H:%M')}",
                                body=message,
                                config=config,
                                environ=environ,
                                slack_sender=slack_sender,
                                email_sender=email_sender,
                            )
                            if dr.any_success(delivery_results):
                                logger.info("Auto full-analysis change summary sent to Slack.")
                            else:
                                logger.warning("Auto full-analysis change summary failed: %s", delivery_results)
            except Exception:
                logger.exception("Auto full-analysis refresh failed.")

    if notifications_enabled and bool(alert_settings.get("send_hourly_market_summary", True)):
        market_hours_only = bool(alert_settings.get("send_hourly_market_summary_market_hours_only", True))
        if market_hours_only and not nr.is_us_market_session(now):
            logger.info("Skipping hourly market summary outside regular US market hours.")
        else:
            try:
                summary_text = summary_builder(
                    before_data=before_data,
                    after_data=refreshed_data,
                    account_snapshot=account_snapshot,
                    risk_gate=risk_decision.to_dict() if hasattr(risk_decision, "to_dict") else risk_decision,
                    allocation_regime=allocation_regime.to_dict() if hasattr(allocation_regime, "to_dict") else allocation_regime,
                    data_sources=md.get_market_data_status_snapshot(),
                    now=now,
                )
                if pending_intraday_discipline_alert and pending_intraday_discipline_alert.get("message"):
                    summary_text = (
                        f"{summary_text}\n"
                        f"Discipline alert: {pending_intraday_discipline_alert['message']}"
                    ).strip()
                if pending_intraday_classifier_alert and pending_intraday_classifier_alert.get("message"):
                    summary_text = (
                        f"{summary_text}\n"
                        f"Intraday alert: {pending_intraday_classifier_alert['message']}"
                    ).strip()
                delivery_results = message_router(
                    "hourly_market_summary",
                    subject=f"Hourly Market Refresh {now.strftime('%Y-%m-%d %H:%M')}",
                    body=summary_text,
                    config=config,
                    environ=environ,
                    slack_sender=slack_sender,
                    email_sender=email_sender,
                )
                if dr.any_success(delivery_results):
                    if pending_intraday_discipline_alert:
                        _record_intraday_discipline_event(
                            alert=pending_intraday_discipline_alert,
                            monthly_discipline_review=latest_monthly_discipline_review,
                            discipline_snapshot=latest_discipline_snapshot,
                            risk_decision=risk_decision,
                            account_snapshot=account_snapshot,
                            now=now,
                            was_alert_sent=True,
                            send_context="hourly_market_summary",
                            skip_reason="",
                            journal_path=intraday_event_journal_path,
                        )
                        _mark_intraday_discipline_alert_sent(
                            alert=pending_intraday_discipline_alert,
                            state_path=intraday_alert_state_path,
                            now=now,
                        )
                    if pending_intraday_classifier_alert:
                        _record_intraday_classifier_events(
                            alert=pending_intraday_classifier_alert,
                            now=now,
                            was_alert_sent=True,
                            send_context="hourly_market_summary",
                            skip_reason="",
                            journal_path=intraday_event_journal_path,
                        )
                        im.mark_intraday_alert_sent(
                            str(pending_intraday_classifier_alert.get("signature") or "").strip(),
                            now=now,
                            path=intraday_event_alert_state_path,
                        )
                    logger.info("Hourly market refresh summary sent via notification channels.")
                else:
                    logger.warning("Hourly market refresh summary failed: %s", delivery_results)
                    if pending_intraday_discipline_alert:
                        _record_intraday_discipline_event(
                            alert=pending_intraday_discipline_alert,
                            monthly_discipline_review=latest_monthly_discipline_review,
                            discipline_snapshot=latest_discipline_snapshot,
                            risk_decision=risk_decision,
                            account_snapshot=account_snapshot,
                            now=now,
                            was_alert_sent=False,
                            send_context="hourly_market_summary",
                            skip_reason="delivery_failed",
                            journal_path=intraday_event_journal_path,
                        )
                    if pending_intraday_classifier_alert:
                        _record_intraday_classifier_events(
                            alert=pending_intraday_classifier_alert,
                            now=now,
                            was_alert_sent=False,
                            send_context="hourly_market_summary",
                            skip_reason="delivery_failed",
                            journal_path=intraday_event_journal_path,
                        )
            except Exception:
                logger.exception("Hourly market refresh summary failed.")
    elif notifications_enabled and nr.is_us_market_session(now) and (pending_intraday_discipline_alert or pending_intraday_classifier_alert):
        bodies = []
        if pending_intraday_discipline_alert and pending_intraday_discipline_alert.get("message"):
            bodies.append(f"Discipline alert: {pending_intraday_discipline_alert['message']}")
        if pending_intraday_classifier_alert and pending_intraday_classifier_alert.get("message"):
            bodies.append(f"Market alert: {pending_intraday_classifier_alert['message']}")
        try:
            delivery_results = message_router(
                "intraday_alert",
                subject=f"Intraday Market Alert {now.strftime('%Y-%m-%d %H:%M')}",
                body="\n\n".join(bodies),
                config=config,
                environ=environ,
                slack_sender=slack_sender,
                email_sender=email_sender,
            )
            delivered = dr.any_success(delivery_results)
            if pending_intraday_discipline_alert:
                _record_intraday_discipline_event(
                    alert=pending_intraday_discipline_alert,
                    monthly_discipline_review=latest_monthly_discipline_review,
                    discipline_snapshot=latest_discipline_snapshot,
                    risk_decision=risk_decision,
                    account_snapshot=account_snapshot,
                    now=now,
                    was_alert_sent=delivered,
                    send_context="intraday_alert",
                    skip_reason="" if delivered else "delivery_failed",
                    journal_path=intraday_event_journal_path,
                )
                if delivered:
                    _mark_intraday_discipline_alert_sent(
                        alert=pending_intraday_discipline_alert,
                        state_path=intraday_alert_state_path,
                        now=now,
                    )
            if pending_intraday_classifier_alert:
                _record_intraday_classifier_events(
                    alert=pending_intraday_classifier_alert,
                    now=now,
                    was_alert_sent=delivered,
                    send_context="intraday_alert",
                    skip_reason="" if delivered else "delivery_failed",
                    journal_path=intraday_event_journal_path,
                )
                if delivered:
                    im.mark_intraday_alert_sent(
                        str(pending_intraday_classifier_alert.get("signature") or "").strip(),
                        now=now,
                        path=intraday_event_alert_state_path,
                    )
            if delivered:
                logger.info("Intraday alert bundle sent via notification channels.")
            else:
                logger.warning("Intraday alert bundle failed: %s", delivery_results)
        except Exception:
            logger.exception("Intraday alert bundle failed.")
    else:
        logger.info("Hourly market summary skipped because no delivery channel is enabled.")
    logger.info("Market cache refresh completed.")
    return True


def nightly_scheduler_loop(
    stop_event: threading.Event,
    *,
    poll_seconds: int = DEFAULT_NIGHTLY_POLL_SECONDS,
    now_func: Callable[[], datetime] = datetime.now,
    should_run: Callable[..., bool] = should_run_nightly_consensus_update,
    runner: Callable[..., object] = run_nightly_alerts,
    logger: Optional[logging.Logger] = None,
):
    logger = logger or logging.getLogger(__name__)
    while not stop_event.is_set():
        try:
            maybe_run_nightly_alerts(now=now_func(), should_run=should_run, runner=runner, logger=logger)
        except Exception:
            logger.exception("Nightly scheduler tick failed.")
        if stop_event.wait(poll_seconds):
            break


def market_refresh_loop(
    stop_event: threading.Event,
    *,
    poll_seconds: int = DEFAULT_MARKET_REFRESH_POLL_SECONDS,
    refresh_interval_seconds: int = DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS,
    now_func: Callable[[], datetime] = datetime.now,
    loader: Callable[[], dict] = data_storage.load_data,
    refresher: Callable[..., tuple] = data_storage.auto_refresh_market_data,
    saver: Callable[[dict], None] = data_storage.save_data,
    quant_analysis_snapshot_path: str = qpa.DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE,
    report_output_dir: str = nr.DEFAULT_REPORTS_DIR,
    auto_quant_analysis_min_interval_seconds: Optional[int] = None,
    auto_quant_analysis_price_jump_pct: Optional[float] = None,
    enable_auto_quant_analysis: Optional[bool] = None,
    logger: Optional[logging.Logger] = None,
):
    logger = logger or logging.getLogger(__name__)
    while not stop_event.is_set():
        try:
            maybe_run_market_refresh(
                now=now_func(),
                loader=loader,
                refresher=refresher,
                saver=saver,
                refresh_interval_seconds=refresh_interval_seconds,
                quant_analysis_snapshot_path=quant_analysis_snapshot_path,
                report_output_dir=report_output_dir,
                auto_quant_analysis_min_interval_seconds=auto_quant_analysis_min_interval_seconds,
                auto_quant_analysis_price_jump_pct=auto_quant_analysis_price_jump_pct,
                enable_auto_quant_analysis=enable_auto_quant_analysis,
                logger=logger,
            )
        except Exception:
            logger.exception("Market refresh tick failed.")
        if stop_event.wait(poll_seconds):
            break


def _terminate_process(process, *, timeout_seconds: float = 10.0):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except Exception:
        process.kill()


def run_supervisor(
    *,
    with_ui: bool = True,
    with_slack: bool = True,
    with_nightly: bool = True,
    with_market_refresh: bool = True,
    monitor_seconds: int = DEFAULT_MONITOR_SECONDS,
    nightly_poll_seconds: int = DEFAULT_NIGHTLY_POLL_SECONDS,
    market_refresh_poll_seconds: int = DEFAULT_MARKET_REFRESH_POLL_SECONDS,
    market_refresh_interval_seconds: int = DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS,
    auto_quant_analysis_min_interval_seconds: Optional[int] = None,
    auto_quant_analysis_price_jump_pct: Optional[float] = None,
    enable_auto_quant_analysis: Optional[bool] = None,
    python_executable: Optional[str] = None,
    project_root: Optional[Path] = None,
    popen=subprocess.Popen,
    should_run: Callable[..., bool] = should_run_nightly_consensus_update,
    runner: Callable[..., object] = run_nightly_alerts,
    now_func: Callable[[], datetime] = datetime.now,
    status_printer: Callable[[str], None] = print,
):
    logger = logging.getLogger(__name__)
    stop_event = threading.Event()
    services = []
    launched_processes = []
    startup_statuses = []
    install_signal_handlers = threading.current_thread() is threading.main_thread()
    previous_sigterm = previous_sigint = None

    def _signal_handler(signum, frame):  # noqa: ARG001
        stop_event.set()

    if install_signal_handlers:
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    scheduler_thread = None
    market_refresh_thread = None
    reported_exits = set()
    try:
        effective_with_slack = with_slack and _has_slack_credentials()
        if with_slack and not effective_with_slack:
            logger.warning("Slack bot skipped because SLACK_BOT_TOKEN or SLACK_APP_TOKEN is missing.")
            startup_statuses.append(
                ServiceStartupStatus(
                    name="slack-bot",
                    state="skipped",
                    detail="SLACK_BOT_TOKEN or SLACK_APP_TOKEN is missing.",
                )
            )

        service_specs = build_service_specs(
            with_ui=with_ui,
            with_slack=effective_with_slack,
            python_executable=python_executable,
            project_root=project_root,
        )
        if with_nightly:
            scheduler_thread = threading.Thread(
                target=nightly_scheduler_loop,
                args=(stop_event,),
                kwargs={
                    "poll_seconds": nightly_poll_seconds,
                    "now_func": now_func,
                    "should_run": should_run,
                    "runner": runner,
                    "logger": logger,
                },
                daemon=True,
                name="nightly-scheduler",
            )
            scheduler_thread.start()
            startup_statuses.append(
                ServiceStartupStatus(
                    name="nightly-scheduler",
                    state="started",
                    detail=f"running in-process; poll={nightly_poll_seconds}s.",
                )
            )

        if with_market_refresh:
            market_refresh_thread = threading.Thread(
                target=market_refresh_loop,
                args=(stop_event,),
                kwargs={
                    "poll_seconds": market_refresh_poll_seconds,
                    "refresh_interval_seconds": market_refresh_interval_seconds,
                    "now_func": now_func,
                    "loader": data_storage.load_data,
                    "refresher": data_storage.auto_refresh_market_data,
                    "saver": data_storage.save_data,
                    "quant_analysis_snapshot_path": qpa.DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE,
                    "report_output_dir": nr.DEFAULT_REPORTS_DIR,
                    "auto_quant_analysis_min_interval_seconds": auto_quant_analysis_min_interval_seconds,
                    "auto_quant_analysis_price_jump_pct": auto_quant_analysis_price_jump_pct,
                    "enable_auto_quant_analysis": enable_auto_quant_analysis,
                    "logger": logger,
                },
                daemon=True,
                name="market-refresh",
            )
            market_refresh_thread.start()
            startup_statuses.append(
                ServiceStartupStatus(
                    name="market-refresh",
                    state="started",
                    detail=f"running in-process; poll={market_refresh_poll_seconds}s interval={market_refresh_interval_seconds}s.",
                )
            )

        if not with_nightly and not with_market_refresh and not service_specs:
            logger.warning("No services were requested; nothing to start.")
            emit_startup_summary(startup_statuses, printer=status_printer)
            return {
                "services": [],
                "launch_count": 0,
                "startup_statuses": [asdict(status) for status in startup_statuses],
            }

        for spec in service_specs:
            try:
                process = start_service_process(spec, popen=popen)
            except Exception as exc:
                logger.exception("Failed to start %s", spec.name)
                startup_statuses.append(
                    ServiceStartupStatus(
                        name=spec.name,
                        state="failed",
                        detail=str(exc),
                    )
                )
                continue
            services.append(spec)
            launched_processes.append((spec, process))
            logger.info("Started %s: %s", spec.name, " ".join(spec.command))
            startup_statuses.append(
                ServiceStartupStatus(
                    name=spec.name,
                    state="started",
                    detail=" ".join(spec.command),
                    pid=getattr(process, "pid", None),
                )
            )

        emit_startup_summary(startup_statuses, printer=status_printer)
        if not launched_processes and scheduler_thread is None and market_refresh_thread is None:
            return {
                "services": [],
                "launch_count": 0,
                "startup_statuses": [asdict(status) for status in startup_statuses],
            }

        while not stop_event.is_set():
            for spec, process in launched_processes:
                code = process.poll()
                if code is not None and spec.name not in reported_exits:
                    reported_exits.add(spec.name)
                    logger.warning("%s exited with code %s", spec.name, code)
            if stop_event.wait(monitor_seconds):
                break
    finally:
        stop_event.set()
        for spec, process in launched_processes:
            _terminate_process(process)
        if scheduler_thread is not None and scheduler_thread.is_alive():
            scheduler_thread.join(timeout=2.0)
        if market_refresh_thread is not None and market_refresh_thread.is_alive():
            market_refresh_thread.join(timeout=2.0)
        if install_signal_handlers:
            signal.signal(signal.SIGTERM, previous_sigterm)
            signal.signal(signal.SIGINT, previous_sigint)

    return {
        "services": [spec.name for spec in services],
        "launch_count": len(launched_processes),
        "startup_statuses": [asdict(status) for status in startup_statuses],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start the Streamlit UI, Slack bot, and nightly scheduler together.")
    parser.add_argument("--no-ui", action="store_true", help="Do not start Streamlit UI.")
    parser.add_argument("--no-slack", action="store_true", help="Do not start the Slack bot.")
    parser.add_argument("--no-nightly", action="store_true", help="Do not start the nightly scheduler.")
    parser.add_argument("--no-market-refresh", action="store_true", help="Do not start the hourly market cache refresher.")
    parser.add_argument("--monitor-seconds", type=int, default=DEFAULT_MONITOR_SECONDS, help="How often to check child processes.")
    parser.add_argument("--nightly-poll-seconds", type=int, default=DEFAULT_NIGHTLY_POLL_SECONDS, help="How often to check whether nightly alerts are due.")
    parser.add_argument("--market-refresh-poll-seconds", type=int, default=DEFAULT_MARKET_REFRESH_POLL_SECONDS, help="How often to check whether market cache refresh is due.")
    parser.add_argument("--market-refresh-interval-seconds", type=int, default=DEFAULT_MARKET_REFRESH_INTERVAL_SECONDS, help="Minimum interval between market cache refreshes.")
    parser.add_argument("--auto-quant-analysis-min-interval-seconds", type=int, default=None, help="Override config-page minimum interval between auto-triggered full quant analysis runs.")
    parser.add_argument("--auto-quant-analysis-price-jump-pct", type=float, default=None, help="Override config-page absolute price change threshold that triggers auto full quant analysis.")
    parser.add_argument("--disable-auto-quant-analysis", action="store_true", help="Do not auto-run full quant analysis during market refresh.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    result = run_supervisor(
        with_ui=not args.no_ui,
        with_slack=not args.no_slack,
        with_nightly=not args.no_nightly,
        with_market_refresh=not args.no_market_refresh,
        monitor_seconds=args.monitor_seconds,
        nightly_poll_seconds=args.nightly_poll_seconds,
        market_refresh_poll_seconds=args.market_refresh_poll_seconds,
        market_refresh_interval_seconds=args.market_refresh_interval_seconds,
        auto_quant_analysis_min_interval_seconds=args.auto_quant_analysis_min_interval_seconds,
        auto_quant_analysis_price_jump_pct=args.auto_quant_analysis_price_jump_pct,
        enable_auto_quant_analysis=False if args.disable_auto_quant_analysis else None,
    )
    print(f"Supervisor exited. services={result['services']} launch_count={result['launch_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
