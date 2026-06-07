import argparse
from datetime import datetime

from quant_core.data import storage as du
from quant_core.data import market_data as md
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
from quant_core.analytics import portfolio_analysis as qpa
from quant_core.analytics import core_etf_rotation as cer
from quant_core.analytics import candidate_pool as cpool
from quant_core.execution import nightly_planner as np
from quant_core.execution import post_close_review as pcr
from quant_core.execution import decision_journal as djour
from quant_core.execution import nightly_manifest as nman
from quant_core.monitoring import intraday_journal as ij
from quant_core.analytics.strategy_compare import compare_strategies_for_symbol
from quant_core.research import strategy_validation as sval
from quant_core.snapshots import system_snapshot as ss
from quant_core.ledger import transactions as tx
from signal_scoreboard import build_signal_scoreboard
from quant_core.risk.risk_gate import build_market_risk_snapshot_from_histories, evaluate_market_risk_gate
from strategies.registry import create_strategy
from strategies import ui as su
from engine import BacktraderEngine


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
    with_strategy_comparison=True,
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
    quant_analysis_snapshot_builder=None,
    quant_analysis_report_builder=None,
    quant_analysis_report_writer=None,
    quant_analysis_snapshot_path=qpa.DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE,
    trade_plan_path=np.DEFAULT_TRADE_PLAN_FILE,
    post_close_review_path=pcr.DEFAULT_POST_CLOSE_REVIEW_FILE,
    manifest_path=nman.DEFAULT_NIGHTLY_MANIFEST_FILE,
    change_feed_path=cf.DEFAULT_CHANGE_FEED_FILE,
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
    quant_analysis_snapshot_builder = quant_analysis_snapshot_builder or qpa.build_portfolio_quant_analysis_snapshot
    quant_analysis_report_builder = quant_analysis_report_builder or nr.build_quant_analysis_report
    quant_analysis_report_writer = quant_analysis_report_writer or nr.save_quant_analysis_report_files
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
    strategy_comparison_rows = []
    quant_analysis_snapshot = None
    quant_analysis_report_files = {}
    quant_analysis_change_results = []
    trade_plan = None
    premarket_brief_text = ""
    core_etf_rotation_snapshot = None
    core_etf_snapshot = None
    satellite_candidate_snapshot = None
    discipline_snapshot = None
    default_runtime_strategy = qpa.load_default_runtime_strategy(history_period=history_period)
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
    core_etf_universe = cer.load_core_etf_universe()
    core_etf_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in list(core_etf_universe.get("etfs", []) or [])
        if bool(row.get("enabled", True))
    }
    if with_strategy_comparison and symbols:
        symbol_for_compare = symbols[0]
        strategies = su.load_strategies()

        def _runtime_strategy(strategy):
            runtime = dict(strategy)
            params = dict(strategy.get("params", {}))
            params["period"] = history_period
            runtime["params"] = params
            return runtime

        strategy_comparison_rows = compare_strategies_for_symbol(
            symbol=symbol_for_compare,
            strategies=strategies,
            load_historical_data_fn=qa.get_historical_data,
            create_strategy_fn=create_strategy,
            engine_factory_fn=lambda: BacktraderEngine(initial_cash=100000),
            history_period=history_period,
            runtime_param_fn=_runtime_strategy,
        )

    if default_runtime_strategy is not None:
        previous_quant_snapshot = qpa.load_quant_analysis_snapshot(path=quant_analysis_snapshot_path)
        try:
            if nman.can_resume_step(manifest, step_name="quant_analysis_snapshot", output_file=quant_analysis_snapshot_path, now=now):
                quant_analysis_snapshot = qpa.load_quant_analysis_snapshot(path=quant_analysis_snapshot_path)
                manifest = nman.mark_step_completed(
                    manifest,
                    step_name="quant_analysis_snapshot",
                    output_file=quant_analysis_snapshot_path,
                    input_version=manifest_input_version,
                    reused=True,
                    path=manifest_path,
                    now=now,
                )
            else:
                manifest = nman.mark_step_started(
                    manifest,
                    step_name="quant_analysis_snapshot",
                    input_version=manifest_input_version,
                    path=manifest_path,
                    now=now,
                )
                quant_analysis_snapshot = quant_analysis_snapshot_builder(
                    data=data,
                    strategy=default_runtime_strategy,
                    history_period=history_period,
                    engine_name="backtrader",
                    risk_gate=risk_decision,
                    allocation_regime=allocation_regime,
                    now=now,
                )
                qpa.save_quant_analysis_snapshot(quant_analysis_snapshot, path=quant_analysis_snapshot_path)
                manifest = nman.mark_step_completed(
                    manifest,
                    step_name="quant_analysis_snapshot",
                    output_file=quant_analysis_snapshot_path,
                    input_version=manifest_input_version,
                    metadata={"top_buy_symbols": list((quant_analysis_snapshot or {}).get("summary", {}).get("top_buy_symbols", []) or [])},
                    path=manifest_path,
                    now=now,
                )
        except Exception as exc:
            manifest = nman.mark_step_failed(manifest, step_name="quant_analysis_snapshot", error_message=str(exc), path=manifest_path, now=now)
            raise
        quant_analysis_change_summary = qpa.build_quant_analysis_change_summary(previous_quant_snapshot, quant_analysis_snapshot)
        try:
            if nman.can_resume_step(manifest, step_name="satellite_candidate_pool", output_file=cpool.DEFAULT_SATELLITE_CANDIDATE_POOL_FILE, now=now):
                satellite_candidate_snapshot = cpool.load_satellite_candidate_pool_snapshot()
                manifest = nman.mark_step_completed(
                    manifest,
                    step_name="satellite_candidate_pool",
                    output_file=cpool.DEFAULT_SATELLITE_CANDIDATE_POOL_FILE,
                    input_version=manifest_input_version,
                    reused=True,
                    path=manifest_path,
                    now=now,
                )
            else:
                manifest = nman.mark_step_started(
                    manifest,
                    step_name="satellite_candidate_pool",
                    input_version=manifest_input_version,
                    path=manifest_path,
                    now=now,
                )
                satellite_candidate_snapshot = cpool.build_satellite_candidate_pool_snapshot(
                    data=data,
                    strategy=default_runtime_strategy,
                    history_period=history_period,
                    load_historical_data_fn=qa.get_historical_data,
                    universe=cpool.load_satellite_universe(),
                    core_symbols=core_etf_symbols,
                    previous_snapshot=previous_satellite_snapshot,
                    discipline_snapshot=discipline_snapshot,
                    policy=cer.load_engine_policy(),
                    risk_gate=risk_decision,
                    allocation_regime=allocation_regime,
                    now=now,
                )
                cpool.save_satellite_candidate_pool_snapshot(satellite_candidate_snapshot)
                manifest = nman.mark_step_completed(
                    manifest,
                    step_name="satellite_candidate_pool",
                    output_file=cpool.DEFAULT_SATELLITE_CANDIDATE_POOL_FILE,
                    input_version=manifest_input_version,
                    metadata={"top_symbols": list((satellite_candidate_snapshot or {}).get("summary", {}).get("top_symbols", []) or [])},
                    path=manifest_path,
                    now=now,
                )
        except Exception as exc:
            manifest = nman.mark_step_failed(manifest, step_name="satellite_candidate_pool", error_message=str(exc), path=manifest_path, now=now)
            raise
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
                trade_plan = plan_builder(
                    quant_analysis_snapshot,
                    satellite_candidate_snapshot=satellite_candidate_snapshot,
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
    else:
        previous_quant_snapshot = None
        quant_analysis_change_summary = {"has_changes": False, "message": ""}
        trade_plan = plan_builder(
            {"symbols": [], "allocation_regime": allocation_regime.to_dict() if hasattr(allocation_regime, "to_dict") else allocation_regime},
            satellite_candidate_snapshot=None,
            discipline_snapshot=discipline_snapshot,
            now=now,
        )
        plan_saver(trade_plan, path=trade_plan_path)
        premarket_brief_text = premarket_brief_builder(trade_plan, execution_review=execution_review)

    strategy_validation_snapshot = sval.load_strategy_validation_snapshot()

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
            "strategy_comparison": strategy_comparison_rows,
            "quant_analysis_summary": dict((quant_analysis_snapshot or {}).get("summary", {}) or {}),
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
        },
        current_state={
            "core_etf_snapshot": core_etf_snapshot,
            "satellite_candidate_snapshot": satellite_candidate_snapshot,
            "discipline_snapshot": discipline_snapshot,
            "trade_plan": trade_plan,
            "monthly_discipline_review": monthly_discipline_review,
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
            "quant_analysis_report_files": {},
            "quant_analysis_change_results": [],
            "premarket_brief_results": [],
            "dry_run": True,
            "snapshot": snapshot,
            "trade_plan": trade_plan,
            "execution_review": execution_review,
            "premarket_brief_text": premarket_brief_text,
            "satellite_candidate_snapshot": satellite_candidate_snapshot,
            "change_feed": change_feed,
            "manifest": manifest,
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
    if quant_analysis_snapshot is not None:
        qpa.save_quant_analysis_snapshot(quant_analysis_snapshot, path=quant_analysis_snapshot_path)
        quant_analysis_report_text = quant_analysis_report_builder(quant_analysis_snapshot)
        quant_analysis_report_files = quant_analysis_report_writer(
            quant_analysis_snapshot,
            report_text=quant_analysis_report_text,
            reports_dir=report_output_dir,
        )
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
            "quant_pdf_path": quant_analysis_report_files.get("pdf_path"),
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

    if (
        quant_analysis_snapshot is not None
        and bool(alert_settings.get("send_quant_analysis_change_summary", True))
    ):
        if quant_analysis_change_summary.get("has_changes"):
            try:
                quant_analysis_change_results = message_router(
                    "quant_analysis_change_summary",
                    subject=f"Quant Analysis Change Summary {now.strftime('%Y-%m-%d')}",
                    body=quant_analysis_change_summary.get("message", ""),
                    config=config,
                    slack_sender=slack_sender,
                    email_sender=email_sender,
                )
            except Exception as exc:
                quant_analysis_change_results.append({"channel": "router", "ok": False, "message": f"quant change summary failed: {exc}"})
        else:
            quant_analysis_change_results.append({"channel": "summary", "ok": False, "message": "quant change summary skipped: no material changes"})
    manifest = nman.mark_step_completed(
        manifest,
        step_name="notifications",
        input_version=manifest_input_version,
        metadata={
            "nightly_report_success": any(bool(row.get("ok")) for row in list(report_results or [])),
            "premarket_success": any(bool(row.get("ok")) for row in list(premarket_results or [])),
            "quant_change_success": any(bool(row.get("ok")) for row in list(quant_analysis_change_results or [])),
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
        "quant_analysis_report_files": quant_analysis_report_files,
        "quant_analysis_change_results": quant_analysis_change_results,
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
        "manifest": manifest,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run nightly quant alert checks and notifications.")
    parser.add_argument("--force", action="store_true", help="Force analyst consensus refresh even outside the normal cycle.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated alerts without sending notifications.")
    parser.add_argument("--history-period", default="2y", help="History period for market risk evaluation.")
    parser.add_argument("--no-strategy-comparison", action="store_true", help="Skip nightly strategy comparison.")
    args = parser.parse_args(argv)

    result = run_nightly_alerts(
        force=args.force,
        dry_run=args.dry_run,
        history_period=args.history_period,
        with_strategy_comparison=not args.no_strategy_comparison,
    )
    print(f"alerts={len(result['alerts'])} sent_results={len(result['sent_results'])} dry_run={result['dry_run']}")
    for alert in result["alerts"]:
        print(f"- {alert['severity']} {alert['title']}")
    for sent in result["sent_results"]:
        print(f"- {sent['channel']} ok={sent['ok']} {sent['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
