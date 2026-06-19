import argparse
from datetime import datetime

from quant_core import paths as qpaths
from quant_core.data import storage as du
from quant_core.data import market_data as md
from quant_core.data import data_health as dhealth
from quant_core.notifications import alert_engine as ae
from quant_core.notifications import notification_channels as nch
from quant_core.events import analyst_consensus as ac
from quant_core.notifications import notification_config as ncfg
from quant_core.notifications import delivery_router as dr
from quant_core.notifications import reporting as nr
from quant_core.notifications import change_feed as cf
from quant_core.portfolio import risk as pa
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from quant_core.portfolio import core_etf_engine as cee
from quant_core.portfolio import discipline as discipline
from quant_core.analytics import quant_analysis as qa
from quant_core.analytics import core_etf_rotation as cer
from quant_core.analytics import candidate_pool as cpool
from quant_core.execution import nightly_planner as np
from quant_core.execution import plan_quality as pqual
from quant_core.execution import post_close_review as pcr
from quant_core.execution import decision_journal as djour
from quant_core.execution import nightly_manifest as nman
from quant_core.monitoring import intraday_journal as ij
from quant_core.monitoring import market_monitor as mmonitor
from quant_core.research import strategy_validation as sval
from quant_core.research import strategy_governance as sgov
from quant_core.snapshots import system_snapshot as ss
from quant_core.ledger import transactions as tx
from quant_core.analytics.signal_scoreboard import build_signal_scoreboard
from quant_core.risk.risk_gate import build_market_risk_snapshot_from_histories, evaluate_market_risk_gate
from quant_core.models.multi_horizon import pipeline as mh_pipeline
from quant_core.models.multi_horizon import snapshot as mh_snapshot
from quant_core.models.multi_horizon import governance as mh_governance


def _tracked_symbols(data):
    return sorted(
        {
            str(item.get("symbol", "")).strip().upper()
            for item in (data.get("holdings", []) + data.get("watchlist", []))
            if item.get("symbol")
        }
    )


def _extract_end_of_day_prices(data):
    price_map = {}
    for row in list((data or {}).get("holdings", []) or []):
        symbol = str(row.get("symbol") or "").strip().upper()
        price = row.get("current_price")
        try:
            price = None if price is None else float(price)
        except (TypeError, ValueError):
            price = None
        if symbol and price is not None:
            price_map[symbol] = price
    for row in list((data or {}).get("watchlist", []) or []):
        symbol = str(row.get("symbol") or "").strip().upper()
        price = row.get("last_price")
        try:
            price = None if price is None else float(price)
        except (TypeError, ValueError):
            price = None
        if symbol and price is not None and symbol not in price_map:
            price_map[symbol] = price
    return price_map


def _extract_market_day_ranges(symbols, *, review_day):
    target_day = review_day.date() if isinstance(review_day, datetime) else review_day
    ranges = {}
    for symbol in list(symbols or []):
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            continue
        try:
            hist = qa.get_historical_data(normalized, period="1mo")
        except Exception:
            continue
        if hist is None or hist.empty:
            continue
        for idx, row in hist.iterrows():
            try:
                row_day = idx.date()
            except Exception:
                try:
                    row_day = datetime.fromisoformat(str(idx)).date()
                except Exception:
                    continue
            if row_day != target_day:
                continue
            try:
                ranges[normalized] = {
                    "open": float(row.get("Open")) if row.get("Open") is not None else None,
                    "high": float(row.get("High")) if row.get("High") is not None else None,
                    "low": float(row.get("Low")) if row.get("Low") is not None else None,
                    "close": float(row.get("Close")) if row.get("Close") is not None else None,
                }
            except Exception:
                pass
            break
    return ranges


def evaluate_current_market_risk(data, history_period="2y"):
    holdings = data.get("holdings", [])
    priced_symbols = list(dict.fromkeys([h["symbol"] for h in holdings if h.get("current_price") is not None]))
    correlation_matrix = None
    if len(priced_symbols) > 1:
        try:
            correlation_matrix = qa.calculate_correlation_matrix(priced_symbols, period="6mo")
        except Exception:
            correlation_matrix = None

    portfolio_risk = pa.analyze_portfolio_risk(holdings, correlation_matrix=correlation_matrix)
    benchmark_history = qa.get_historical_data("SPY", period=history_period)
    vix_history = qa.get_historical_data("^VIX", period="6mo")
    snapshot = build_market_risk_snapshot_from_histories(
        benchmark_history=benchmark_history,
        vix_history=vix_history,
        sector_alert_count=len(portfolio_risk.sector_alerts),
        correlation_alert_count=len(portfolio_risk.correlation_alerts),
    )
    return evaluate_market_risk_gate(snapshot)


def run_nightly_alerts(
    *,
    now=None,
    force=False,
    dry_run=False,
    history_period="2y",
    notification_config_path=ncfg.NOTIFICATION_CONFIG_FILE,
    alert_state_path=ae.ALERT_STATE_FILE,
    snapshot_journal_path=ss.DEFAULT_NIGHTLY_JOURNAL_FILE,
    report_output_dir=nr.DEFAULT_REPORTS_DIR,
    slack_sender=None,
    email_sender=None,
    message_router=None,
    report_builder=None,
    report_writer=None,
    plan_builder=None,
    plan_loader=None,
    plan_saver=None,
    premarket_brief_builder=None,
    review_builder=None,
    review_saver=None,
    trade_plan_path=np.DEFAULT_TRADE_PLAN_FILE,
    post_close_review_path=pcr.DEFAULT_POST_CLOSE_REVIEW_FILE,
    manifest_path=nman.DEFAULT_NIGHTLY_MANIFEST_FILE,
    change_feed_path=cf.DEFAULT_CHANGE_FEED_FILE,
    multi_horizon_runner=None,
    multi_horizon_snapshot_path=mh_snapshot.DEFAULT_MULTI_HORIZON_SNAPSHOT_FILE,
    model_prediction_journal_path=mh_governance.DEFAULT_PREDICTION_JOURNAL_FILE,
    model_governance_path=mh_governance.DEFAULT_GOVERNANCE_FILE,
    model_validation_path=qpaths.MULTI_HORIZON_VALIDATION_FILE,
    environ=None,
):
    now = now or datetime.now()
    slack_sender = slack_sender or nch.send_slack_message
    email_sender = email_sender or nch.send_email_message
    message_router = message_router or dr.deliver_message
    report_builder = report_builder or nr.build_nightly_report
    report_writer = report_writer or nr.save_nightly_report_files
    plan_builder = plan_builder or np.build_next_day_trade_plan
    plan_loader = plan_loader or np.load_next_day_trade_plan
    plan_saver = plan_saver or np.save_next_day_trade_plan
    premarket_brief_builder = premarket_brief_builder or np.build_premarket_brief
    review_builder = review_builder or pcr.build_execution_review
    review_saver = review_saver or pcr.save_post_close_review
    md.reset_market_data_status()
    manifest = nman.initialize_nightly_run_manifest(now=now, force=force, path=manifest_path)
    manifest_input_version = str(manifest.get("run_id") or now.strftime("%Y%m%d-nightly"))
    data = du.load_data()
    symbols = _tracked_symbols(data)
    transaction_rows = tx.normalize_transactions(tx.load_transactions())

    if force or ac.should_run_nightly_consensus_update(now=now):
        ac.refresh_analyst_consensus_cache(symbols, now=now)

    analyst_cache = ac.load_analyst_consensus_cache()
    risk_decision = evaluate_current_market_risk(data, history_period=history_period) if data.get("holdings") else None
    alerts = ae.collect_alerts(
        analyst_cache=analyst_cache,
        risk_decision=risk_decision,
        symbols=symbols,
        now=now,
    )
    alert_dicts = ae.alerts_to_dicts(alerts)
    benchmark_history = qa.get_historical_data("SPY", period=history_period)
    daily_recap = tx.summarize_daily_activity(transaction_rows, day=now)
    signal_attribution = nr.build_signal_attribution(transaction_rows, day=now)
    previous_trade_plan = plan_loader(path=trade_plan_path)
    previous_trade_plan_symbols = [
        str(item.get("symbol") or "").strip().upper()
        for item in list(dict(previous_trade_plan or {}).get("items", []) or [])
        if str(item.get("symbol") or "").strip()
    ]
    previous_trade_plan_ranges = _extract_market_day_ranges(previous_trade_plan_symbols, review_day=now)
    previous_core_etf_snapshot = cee.load_core_etf_snapshot()
    previous_discipline_snapshot = discipline.load_discipline_snapshot()
    previous_satellite_snapshot = cpool.load_satellite_candidate_pool_snapshot()
    prior_snapshot_journal = ss.load_snapshot_journal(journal_path=snapshot_journal_path, limit=62)
    try:
        if nman.can_resume_step(manifest, step_name="execution_review", output_file=post_close_review_path, now=now):
            execution_review = pcr.load_post_close_review(path=post_close_review_path)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="execution_review",
                output_file=post_close_review_path,
                input_version=manifest_input_version,
                reused=True,
                path=manifest_path,
                now=now,
            )
        else:
            manifest = nman.mark_step_started(
                manifest,
                step_name="execution_review",
                input_version=manifest_input_version,
                path=manifest_path,
                now=now,
            )
            execution_review = review_builder(
                previous_trade_plan,
                transaction_rows,
                day=now,
                market_day_ranges=previous_trade_plan_ranges,
            )
            review_saver(execution_review, path=post_close_review_path)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="execution_review",
                output_file=post_close_review_path,
                input_version=manifest_input_version,
                metadata={
                    "executed_count": int((execution_review or {}).get("executed_count", 0) or 0),
                    "unplanned_trade_count": int((execution_review or {}).get("unplanned_trade_count", 0) or 0),
                },
                path=manifest_path,
                now=now,
            )
    except Exception as exc:
        manifest = nman.mark_step_failed(manifest, step_name="execution_review", error_message=str(exc), path=manifest_path, now=now)
        raise
    intraday_event_summary = {}
    try:
        manifest = nman.mark_step_started(
            manifest,
            step_name="intraday_event_outcomes",
            input_version=manifest_input_version,
            path=manifest_path,
            now=now,
        )
        intraday_event_summary = ij.annotate_intraday_event_outcomes(
            review_day=now,
            end_of_day_prices=_extract_end_of_day_prices(data),
            transactions=transaction_rows,
        )
        manifest = nman.mark_step_completed(
            manifest,
            step_name="intraday_event_outcomes",
            output_file=ij.DEFAULT_INTRADAY_EVENT_JOURNAL_FILE,
            input_version=manifest_input_version,
            metadata=dict(intraday_event_summary or {}),
            path=manifest_path,
            now=now,
        )
    except Exception as exc:
        manifest = nman.mark_step_failed(manifest, step_name="intraday_event_outcomes", error_message=str(exc), path=manifest_path, now=now)
        raise
    live_scoreboard = build_signal_scoreboard(
        transaction_rows,
        benchmark_history=benchmark_history,
    )
    account_snapshot = ss.build_account_snapshot(data)
    allocation_regime = evaluate_allocation_regime(
        live_scoreboard,
        risk_gate=risk_decision,
        account_snapshot=account_snapshot,
    )
    multi_horizon_runner = multi_horizon_runner or mh_pipeline.run_multi_horizon_job
    multi_horizon_snapshot = None
    try:
        if nman.can_resume_step(
            manifest,
            step_name="multi_horizon_inference",
            output_file=multi_horizon_snapshot_path,
            now=now,
        ):
            multi_horizon_snapshot = mh_snapshot.load_multi_horizon_snapshot(path=multi_horizon_snapshot_path)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="multi_horizon_inference",
                output_file=multi_horizon_snapshot_path,
                input_version=manifest_input_version,
                reused=True,
                path=manifest_path,
                now=now,
            )
        else:
            manifest = nman.mark_step_started(
                manifest,
                step_name="multi_horizon_inference",
                input_version=manifest_input_version,
                path=manifest_path,
                now=now,
            )
            risk_regime = (
                getattr(risk_decision, "regime", None)
                if risk_decision is not None
                else "NORMAL"
            )
            multi_horizon_snapshot = multi_horizon_runner(
                data=data,
                train=False,
                risk_regime=str(risk_regime or "NORMAL"),
                now=now,
            )
            manifest = nman.mark_step_completed(
                manifest,
                step_name="multi_horizon_inference",
                output_file=multi_horizon_snapshot_path,
                input_version=manifest_input_version,
                metadata={
                    "status": dict(multi_horizon_snapshot or {}).get("status"),
                    "symbol_count": int(dict(dict(multi_horizon_snapshot or {}).get("summary", {}) or {}).get("symbol_count", 0) or 0),
                },
                path=manifest_path,
                now=now,
            )
    except Exception as exc:
        multi_horizon_snapshot = {
            "status": "MODEL_ERROR",
            "generated_at": now.isoformat(),
            "summary": {"symbol_count": 0, "message": str(exc)},
            "symbols": [],
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
        mh_snapshot.save_multi_horizon_snapshot(multi_horizon_snapshot, path=multi_horizon_snapshot_path)
        manifest = nman.mark_step_failed(
            manifest,
            step_name="multi_horizon_inference",
            error_message=str(exc),
            path=manifest_path,
            now=now,
        )
    multi_horizon_snapshot = dict(multi_horizon_snapshot or {})
    model_governance_snapshot = {}
    if dict(multi_horizon_snapshot or {}).get("status") == "READY":
        mh_governance.append_prediction_journal(multi_horizon_snapshot, path=model_prediction_journal_path)
    model_governance_snapshot = mh_governance.refresh_model_governance(
        multi_horizon_snapshot or {},
        score_outcomes=False,
        validation_path=model_validation_path,
        journal_path=model_prediction_journal_path,
        governance_path=model_governance_path,
        now=now,
    )
    multi_horizon_snapshot = mh_governance.apply_production_gate(
        multi_horizon_snapshot,
        model_governance_snapshot,
    )
    mh_snapshot.save_multi_horizon_snapshot(multi_horizon_snapshot, path=multi_horizon_snapshot_path)
    trade_plan = None
    premarket_brief_text = ""
    core_etf_rotation_snapshot = None
    core_etf_snapshot = None
    satellite_candidate_snapshot = None
    discipline_snapshot = None
    try:
        if nman.can_resume_step(manifest, step_name="core_etf_snapshot", output_file=cee.DEFAULT_CORE_ETF_SNAPSHOT_FILE, now=now):
            core_etf_snapshot = cee.load_core_etf_snapshot()
            manifest = nman.mark_step_completed(
                manifest,
                step_name="core_etf_snapshot",
                output_file=cee.DEFAULT_CORE_ETF_SNAPSHOT_FILE,
                input_version=manifest_input_version,
                reused=True,
                path=manifest_path,
                now=now,
            )
        else:
            manifest = nman.mark_step_started(
                manifest,
                step_name="core_etf_snapshot",
                input_version=manifest_input_version,
                path=manifest_path,
                now=now,
            )
            core_etf_rotation_snapshot = cer.build_core_etf_rotation_snapshot(
                data=data,
                history_period=history_period,
                load_historical_data_fn=qa.get_historical_data,
                risk_gate=risk_decision,
                allocation_regime=allocation_regime,
                now=now,
            )
            core_etf_snapshot = cee.build_core_etf_snapshot(
                data=data,
                account_snapshot=account_snapshot,
                rotation_snapshot=core_etf_rotation_snapshot,
                risk_gate=risk_decision,
                allocation_regime=allocation_regime,
                previous_snapshot=previous_core_etf_snapshot,
                now=now,
            )
            cee.save_core_etf_snapshot(core_etf_snapshot)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="core_etf_snapshot",
                output_file=cee.DEFAULT_CORE_ETF_SNAPSHOT_FILE,
                input_version=manifest_input_version,
                metadata={"focus_symbols": list((core_etf_snapshot or {}).get("summary", {}).get("focus_symbols", []) or [])},
                path=manifest_path,
                now=now,
            )
    except Exception as exc:
        manifest = nman.mark_step_failed(manifest, step_name="core_etf_snapshot", error_message=str(exc), path=manifest_path, now=now)
        raise

    try:
        if nman.can_resume_step(manifest, step_name="discipline_snapshot", output_file=discipline.DEFAULT_DISCIPLINE_SNAPSHOT_FILE, now=now):
            discipline_snapshot = discipline.load_discipline_snapshot()
            manifest = nman.mark_step_completed(
                manifest,
                step_name="discipline_snapshot",
                output_file=discipline.DEFAULT_DISCIPLINE_SNAPSHOT_FILE,
                input_version=manifest_input_version,
                reused=True,
                path=manifest_path,
                now=now,
            )
        else:
            manifest = nman.mark_step_started(
                manifest,
                step_name="discipline_snapshot",
                input_version=manifest_input_version,
                path=manifest_path,
                now=now,
            )
            discipline_snapshot = discipline.build_discipline_snapshot(
                account_snapshot=account_snapshot,
                risk_gate=risk_decision,
                allocation_regime=allocation_regime,
                core_etf_snapshot=core_etf_snapshot,
                now=now,
            )
            discipline.save_discipline_snapshot(discipline_snapshot)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="discipline_snapshot",
                output_file=discipline.DEFAULT_DISCIPLINE_SNAPSHOT_FILE,
                input_version=manifest_input_version,
                metadata={"regime": (discipline_snapshot or {}).get("regime")},
                path=manifest_path,
                now=now,
            )
    except Exception as exc:
        manifest = nman.mark_step_failed(manifest, step_name="discipline_snapshot", error_message=str(exc), path=manifest_path, now=now)
        raise
    satellite_candidate_snapshot = mh_pipeline.build_satellite_snapshot_from_model(multi_horizon_snapshot)
    cpool.save_satellite_candidate_pool_snapshot(satellite_candidate_snapshot)
    try:
        if nman.can_resume_step(manifest, step_name="trade_plan", output_file=trade_plan_path, now=now):
            trade_plan = plan_loader(path=trade_plan_path)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="trade_plan",
                output_file=trade_plan_path,
                input_version=manifest_input_version,
                reused=True,
                path=manifest_path,
                now=now,
            )
        else:
            manifest = nman.mark_step_started(
                manifest,
                step_name="trade_plan",
                input_version=manifest_input_version,
                path=manifest_path,
                now=now,
            )
            model_plan_source = {
                **dict(multi_horizon_snapshot or {}),
                "allocation_regime": allocation_regime.to_dict() if hasattr(allocation_regime, "to_dict") else allocation_regime,
            }
            trade_plan = plan_builder(
                model_plan_source,
                satellite_candidate_snapshot=None,
                discipline_snapshot=discipline_snapshot,
                now=now,
            )
            plan_saver(trade_plan, path=trade_plan_path)
            manifest = nman.mark_step_completed(
                manifest,
                step_name="trade_plan",
                output_file=trade_plan_path,
                input_version=manifest_input_version,
                metadata={"decision": (trade_plan or {}).get("decision"), "action_count": int((trade_plan or {}).get("action_count", 0) or 0)},
                path=manifest_path,
                now=now,
            )
    except Exception as exc:
        manifest = nman.mark_step_failed(manifest, step_name="trade_plan", error_message=str(exc), path=manifest_path, now=now)
        raise
    premarket_brief_text = premarket_brief_builder(trade_plan, execution_review=execution_review)

    strategy_validation_snapshot = sval.load_strategy_validation_snapshot()
    try:
        data_health_snapshot = dhealth.build_data_health_snapshot(
            data,
            data_sources=md.get_market_data_status_snapshot(),
            now=now,
        )
        dhealth.save_data_health_snapshot(data_health_snapshot)
    except Exception:
        data_health_snapshot = {}
    try:
        prior_reviews = [
            dict((row or {}).get("execution_review", {}) or {})
            for row in list(prior_snapshot_journal or [])
            if dict((row or {}).get("execution_review", {}) or {})
        ]
        core_symbols_for_quality = [
            str((row or {}).get("symbol") or "").strip().upper()
            for row in list((core_etf_snapshot or {}).get("symbols", []) or [])
            if str((row or {}).get("symbol") or "").strip()
        ]
        plan_quality_snapshot = pqual.build_plan_quality_snapshot(
            trade_plan=trade_plan,
            latest_review=execution_review,
            review_history=prior_reviews,
            core_symbols=core_symbols_for_quality,
            now=now,
        )
        pqual.save_plan_quality_snapshot(plan_quality_snapshot)
    except Exception:
        plan_quality_snapshot = {}
    try:
        strategy_governance_snapshot = sgov.build_strategy_governance_snapshot(
            validation_snapshot=strategy_validation_snapshot,
            now=now,
        )
        sgov.save_strategy_registry_state(strategy_governance_snapshot)
    except Exception:
        strategy_governance_snapshot = {}
    try:
        market_monitor_snapshot = mmonitor.build_market_monitor_snapshot(
            data_health_snapshot=data_health_snapshot,
            now=now,
        )
        mmonitor.save_market_monitor_snapshot(market_monitor_snapshot)
    except Exception:
        market_monitor_snapshot = {}

    snapshot = ss.build_system_snapshot(
        data=data,
        risk_gate=risk_decision,
        alerts=alert_dicts,
        data_sources=md.get_market_data_status_snapshot(),
        performance={
            "live_scoreboard": {
                "completed_trades": int(getattr(live_scoreboard, "completed_trades", 0) or 0),
                "win_rate": getattr(live_scoreboard, "win_rate", None),
                "expectancy_return_pct": getattr(live_scoreboard, "expectancy_return_pct", None),
                "profit_factor": getattr(live_scoreboard, "profit_factor", None),
                "max_drawdown_pct": getattr(live_scoreboard, "max_drawdown_pct", None),
            },
        },
        allocation_regime=allocation_regime.to_dict(),
        daily_recap=daily_recap,
        signal_attribution=signal_attribution,
        trade_plan=trade_plan,
        execution_review=execution_review,
        core_etf_snapshot=core_etf_snapshot,
        satellite_candidate_snapshot=satellite_candidate_snapshot,
        discipline_snapshot=discipline_snapshot,
        strategy_validation_snapshot=strategy_validation_snapshot,
        data_health_snapshot=data_health_snapshot,
        plan_quality_snapshot=plan_quality_snapshot,
        market_monitor_snapshot=market_monitor_snapshot,
        strategy_governance_snapshot=strategy_governance_snapshot,
        multi_horizon_snapshot=multi_horizon_snapshot,
        intraday_event_summary=intraday_event_summary,
        generated_at=now,
    )
    manifest = nman.mark_step_started(
        manifest,
        step_name="monthly_discipline_review",
        input_version=manifest_input_version,
        path=manifest_path,
        now=now,
    )
    monthly_discipline_review = discipline.build_monthly_discipline_review(
        discipline_snapshot=discipline_snapshot,
        scoreboard=live_scoreboard,
        latest_post_close_review=execution_review,
        snapshot_journal=prior_snapshot_journal + [snapshot],
        now=now,
    )
    manifest = nman.mark_step_completed(
        manifest,
        step_name="monthly_discipline_review",
        input_version=manifest_input_version,
        metadata={
            "status": (monthly_discipline_review or {}).get("status"),
            "follow_days": int((monthly_discipline_review or {}).get("follow_days", 0) or 0),
            "ignore_days": int((monthly_discipline_review or {}).get("ignore_days", 0) or 0),
        },
        path=manifest_path,
        now=now,
    )
    manifest = nman.mark_step_started(
        manifest,
        step_name="change_feed",
        input_version=manifest_input_version,
        path=manifest_path,
        now=now,
    )
    change_feed = cf.build_change_feed(
        previous_state={
            "core_etf_snapshot": previous_core_etf_snapshot,
            "satellite_candidate_snapshot": previous_satellite_snapshot,
            "discipline_snapshot": previous_discipline_snapshot,
            "trade_plan": previous_trade_plan,
            "monthly_discipline_review": dict((prior_snapshot_journal[-1] if prior_snapshot_journal else {}).get("monthly_discipline_review", {}) or {}),
            "data_health_snapshot": dict((prior_snapshot_journal[-1] if prior_snapshot_journal else {}).get("data_health_snapshot", {}) or {}),
            "plan_quality_snapshot": dict((prior_snapshot_journal[-1] if prior_snapshot_journal else {}).get("plan_quality_snapshot", {}) or {}),
            "strategy_governance_snapshot": dict((prior_snapshot_journal[-1] if prior_snapshot_journal else {}).get("strategy_governance_snapshot", {}) or {}),
        },
        current_state={
            "core_etf_snapshot": core_etf_snapshot,
            "satellite_candidate_snapshot": satellite_candidate_snapshot,
            "discipline_snapshot": discipline_snapshot,
            "trade_plan": trade_plan,
            "monthly_discipline_review": monthly_discipline_review,
            "data_health_snapshot": data_health_snapshot,
            "plan_quality_snapshot": plan_quality_snapshot,
            "strategy_governance_snapshot": strategy_governance_snapshot,
        },
        now=now,
    )
    cf.save_change_feed(change_feed, path=change_feed_path)
    manifest = nman.mark_step_completed(
        manifest,
        step_name="change_feed",
        output_file=change_feed_path,
        input_version=manifest_input_version,
        metadata=dict(change_feed.get("summary", {}) or {}),
        path=manifest_path,
        now=now,
    )
    snapshot["monthly_discipline_review"] = monthly_discipline_review
    snapshot["intraday_event_summary"] = intraday_event_summary
    snapshot["change_feed"] = change_feed
    snapshot["nightly_manifest"] = manifest
    config = ncfg.apply_environment_overrides(
        ncfg.load_notification_config(notification_config_path),
        environ=environ,
    )

    if dry_run:
        manifest = nman.finalize_nightly_run_manifest(manifest, status="completed", path=manifest_path, now=now)
        snapshot["nightly_manifest"] = manifest
        return {
            "alerts": alert_dicts,
            "sent_results": [],
            "report_results": [],
            "report_files": {},
            "premarket_brief_results": [],
            "dry_run": True,
            "snapshot": snapshot,
            "trade_plan": trade_plan,
            "execution_review": execution_review,
            "premarket_brief_text": premarket_brief_text,
            "satellite_candidate_snapshot": satellite_candidate_snapshot,
            "change_feed": change_feed,
            "manifest": manifest,
            "multi_horizon_snapshot": multi_horizon_snapshot,
        }

    sent_results = ae.send_new_alerts(
        alerts,
        config=config,
        state_path=alert_state_path,
        now=now,
    )
    manifest = nman.mark_step_started(
        manifest,
        step_name="report_files",
        input_version=manifest_input_version,
        path=manifest_path,
        now=now,
    )
    report_text = report_builder(snapshot)
    report_files = report_writer(snapshot, report_text=report_text, reports_dir=report_output_dir)
    if core_etf_snapshot is not None:
        cee.save_core_etf_snapshot(core_etf_snapshot)
    if satellite_candidate_snapshot is not None:
        cpool.save_satellite_candidate_pool_snapshot(satellite_candidate_snapshot)
    if discipline_snapshot is not None:
        discipline.save_discipline_snapshot(discipline_snapshot)
    manifest = nman.mark_step_completed(
        manifest,
        step_name="report_files",
        output_file=report_files.get("markdown_path"),
        input_version=manifest_input_version,
        metadata={
            "json_path": report_files.get("json_path"),
        },
        path=manifest_path,
        now=now,
    )
    report_results = []
    premarket_results = []
    alert_settings = config.get("alert_settings", {}) if isinstance(config, dict) else {}
    manifest = nman.mark_step_started(
        manifest,
        step_name="notifications",
        input_version=manifest_input_version,
        path=manifest_path,
        now=now,
    )
    if bool(alert_settings.get("send_daily_summary", True)):
        try:
            report_results = message_router(
                "nightly_report",
                subject=f"Nightly Portfolio Report {now.strftime('%Y-%m-%d')}",
                body=report_text,
                config=config,
                slack_sender=slack_sender,
                email_sender=email_sender,
            )
        except Exception as exc:
            report_results = [{"channel": "router", "ok": False, "message": f"nightly report failed: {exc}"}]

        if not bool(alert_settings.get("send_premarket_brief", True)):
            premarket_results = [{"channel": "summary", "ok": False, "message": "premarket brief skipped: disabled"}]
        elif not nr.is_us_market_nightly_cycle_trading_day(now):
            premarket_results = [{"channel": "summary", "ok": False, "message": "premarket brief skipped: non-trading day"}]
        else:
            try:
                premarket_results = message_router(
                    "premarket_brief",
                    subject=f"Premarket Brief {trade_plan.get('plan_date') if isinstance(trade_plan, dict) else now.strftime('%Y-%m-%d')}",
                    body=premarket_brief_text,
                    config=config,
                    slack_sender=slack_sender,
                    email_sender=email_sender,
                )
            except Exception as exc:
                premarket_results = [{"channel": "router", "ok": False, "message": f"premarket brief failed: {exc}"}]
    else:
        report_results = [{"channel": "summary", "ok": False, "message": "nightly report skipped: daily summaries are disabled"}]
        premarket_results = [{"channel": "summary", "ok": False, "message": "premarket brief skipped: daily summaries are disabled"}]

    manifest = nman.mark_step_completed(
        manifest,
        step_name="notifications",
        input_version=manifest_input_version,
        metadata={
            "nightly_report_success": any(bool(row.get("ok")) for row in list(report_results or [])),
            "premarket_success": any(bool(row.get("ok")) for row in list(premarket_results or [])),
        },
        path=manifest_path,
        now=now,
    )
    manifest = nman.finalize_nightly_run_manifest(manifest, status="completed", path=manifest_path, now=now)
    snapshot["nightly_manifest"] = manifest
    manifest = nman.mark_step_started(
        manifest,
        step_name="snapshot_journal",
        input_version=manifest_input_version,
        path=manifest_path,
        now=now,
    )
    snapshot["nightly_manifest"] = manifest
    journal_path = ss.append_snapshot_journal(snapshot, journal_path=snapshot_journal_path)
    manifest = nman.mark_step_completed(
        manifest,
        step_name="snapshot_journal",
        output_file=snapshot_journal_path,
        input_version=manifest_input_version,
        metadata={"journal_path": journal_path},
        path=manifest_path,
        now=now,
    )
    manifest = nman.mark_step_started(
        manifest,
        step_name="decision_journal",
        input_version=manifest_input_version,
        path=manifest_path,
        now=now,
    )
    decision_journal_path = djour.append_nightly_decision_journal(snapshot)
    manifest = nman.mark_step_completed(
        manifest,
        step_name="decision_journal",
        output_file=djour.DEFAULT_NIGHTLY_DECISION_JOURNAL_FILE,
        input_version=manifest_input_version,
        metadata={"journal_path": decision_journal_path, "decision_signature": snapshot.get("decision_signature")},
        path=manifest_path,
        now=now,
    )
    manifest = nman.finalize_nightly_run_manifest(manifest, status="completed", path=manifest_path, now=now)
    snapshot["nightly_manifest"] = manifest
    return {
        "alerts": alert_dicts,
        "sent_results": sent_results,
        "report_results": report_results,
        "premarket_brief_results": premarket_results,
        "report_files": report_files,
        "dry_run": False,
        "snapshot": snapshot,
        "snapshot_journal_path": journal_path,
        "trade_plan": trade_plan,
        "execution_review": execution_review,
        "premarket_brief_text": premarket_brief_text,
        "core_etf_snapshot": core_etf_snapshot,
        "satellite_candidate_snapshot": satellite_candidate_snapshot,
        "discipline_snapshot": discipline_snapshot,
        "change_feed": change_feed,
        "multi_horizon_snapshot": multi_horizon_snapshot,
        "manifest": manifest,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run nightly quant alert checks and notifications.")
    parser.add_argument("--force", action="store_true", help="Force analyst consensus refresh even outside the normal cycle.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated alerts without sending notifications.")
    parser.add_argument("--history-period", default="2y", help="History period for market risk evaluation.")
    args = parser.parse_args(argv)

    result = run_nightly_alerts(
        force=args.force,
        dry_run=args.dry_run,
        history_period=args.history_period,
    )
    print(f"alerts={len(result['alerts'])} sent_results={len(result['sent_results'])} dry_run={result['dry_run']}")
    for alert in result["alerts"]:
        print(f"- {alert['severity']} {alert['title']}")
    for sent in result["sent_results"]:
        print(f"- {sent['channel']} ok={sent['ok']} {sent['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
