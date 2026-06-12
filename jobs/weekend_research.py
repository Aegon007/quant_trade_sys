from __future__ import annotations

import argparse
from datetime import datetime

from engine import BacktraderEngine
from jobs.nightly_alerts import evaluate_current_market_risk
from quant_core.analytics import candidate_pool as cpool
from quant_core.analytics import core_etf_rotation as cer
from quant_core.analytics import quant_analysis as qa
from quant_core.analytics import portfolio_analysis as qpa
from quant_core.analytics.strategy_compare import compare_strategies_for_symbol
from quant_core.data import storage as du
from quant_core.notifications import delivery_router as dr
from quant_core.notifications import notification_channels as nch
from quant_core.notifications import notification_config as ncfg
from quant_core.portfolio import core_etf_engine as cee
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from quant_core.research import strategy_validation as sval
from quant_core.research import strategy_governance as sgov
from quant_core.research import evidence_collector as evid
from quant_core.research import weekend_research as wr
from quant_core.snapshots import system_snapshot as ss
from quant_core.ledger import transactions as tx
from quant_core.analytics.signal_scoreboard import build_signal_scoreboard
from strategies import ui as su
from strategies.registry import create_strategy


def _runtime_strategy(strategy, *, history_period: str):
    runtime = dict(strategy or {})
    runtime_params = dict(runtime.get("params", {}) or {})
    runtime_params.setdefault("period", history_period)
    runtime["params"] = runtime_params
    return runtime


def run_weekend_research(
    *,
    now=None,
    force=False,
    notification_config_path=ncfg.NOTIFICATION_CONFIG_FILE,
    snapshot_path=wr.DEFAULT_WEEKEND_RESEARCH_SNAPSHOT_FILE,
    state_path=wr.DEFAULT_WEEKEND_RESEARCH_STATE_FILE,
    reports_dir=wr.DEFAULT_WEEKEND_REPORTS_DIR,
    slack_sender=None,
    email_sender=None,
    message_router=None,
    environ=None,
):
    now = now or datetime.now()
    config = ncfg.load_notification_config(notification_config_path)
    normalized_config = ncfg.apply_environment_overrides(config, environ=environ)
    alert_settings = dict(normalized_config.get("alert_settings", {}) or {})
    schedule = wr.normalize_weekend_research_schedule(alert_settings)
    if not force and not wr.should_run_weekend_research(now=now, alert_settings=alert_settings, state_path=state_path):
        return {"ran": False, "reason": "not_due", "schedule": schedule}

    slack_sender = slack_sender or nch.send_slack_message
    email_sender = email_sender or nch.send_email_message
    message_router = message_router or dr.deliver_message

    history_period = schedule["history_period"]
    data = du.load_data()
    transaction_rows = tx.normalize_transactions(tx.load_transactions())
    benchmark_history = qa.get_historical_data("SPY", period=history_period)
    live_scoreboard = build_signal_scoreboard(transaction_rows, benchmark_history=benchmark_history)
    account_snapshot = ss.build_account_snapshot(data)
    risk_gate = evaluate_current_market_risk(data, history_period=history_period) if data.get("holdings") else None
    allocation_regime = evaluate_allocation_regime(
        live_scoreboard,
        risk_gate=risk_gate,
        account_snapshot=account_snapshot,
    )

    core_universe = cer.load_core_etf_universe()
    policy = cer.load_engine_policy()
    core_rotation_snapshot = cer.build_core_etf_rotation_snapshot(
        data=data,
        history_period=history_period,
        universe=core_universe,
        policy=policy,
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        now=now,
    )
    core_snapshot = cee.build_core_etf_snapshot(
        data=data,
        account_snapshot=account_snapshot,
        rotation_snapshot=core_rotation_snapshot,
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        previous_snapshot=cee.load_core_etf_snapshot(),
        policy=policy,
        now=now,
    )

    satellite_universe = cpool.load_satellite_universe()
    weekend_universe = dict(satellite_universe or {})
    weekend_universe["max_candidate_pool_size"] = max(int(weekend_universe.get("max_candidate_pool_size", 100) or 100), 100)
    weekend_universe["max_deep_analysis_size"] = max(int(weekend_universe.get("max_deep_analysis_size", 20) or 20), 30)
    weekend_universe["max_recommendations"] = max(int(weekend_universe.get("max_recommendations", 3) or 3), 5)
    strategies = su.load_strategies()
    runtime_strategy = qpa.load_default_runtime_strategy(history_period="2y")
    if runtime_strategy is None and strategies:
        runtime_strategy = _runtime_strategy(strategies[0], history_period="2y")
    satellite_snapshot = cpool.build_satellite_candidate_pool_snapshot(
        data=data,
        strategy=runtime_strategy,
        history_period="2y",
        universe=weekend_universe,
        core_symbols={str(row.get("symbol") or "").strip().upper() for row in list((core_snapshot or {}).get("symbols", []) or [])},
        previous_snapshot=cpool.load_satellite_candidate_pool_snapshot(),
        discipline_snapshot=None,
        policy=policy,
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        now=now,
    )

    top_symbols = [
        str(row.get("symbol") or "").strip().upper()
        for row in list((satellite_snapshot or {}).get("top_recommendations", []) or [])[:3]
        if str(row.get("symbol") or "").strip()
    ]
    core_focus_symbols = [
        str(symbol or "").strip().upper()
        for symbol in list((core_snapshot or {}).get("summary", {}).get("focus_symbols", []) or [])[:2]
        if str(symbol or "").strip()
    ]
    validation_targets = []
    for symbol in top_symbols:
        if symbol:
            validation_targets.append((symbol, "satellite"))
    for symbol in core_focus_symbols:
        if symbol and symbol not in {item[0] for item in validation_targets}:
            validation_targets.append((symbol, "core"))
    validation_targets = validation_targets[:5]
    strategy_rows = []
    if validation_targets:
        for symbol, focus_role in validation_targets:
            comparisons = compare_strategies_for_symbol(
                symbol=symbol,
                strategies=strategies,
                load_historical_data_fn=qa.get_historical_data,
                create_strategy_fn=create_strategy,
                engine_factory_fn=BacktraderEngine,
                history_period="2y",
                runtime_param_fn=lambda strategy: _runtime_strategy(strategy, history_period="2y"),
            )
            if comparisons:
                best = dict(comparisons[0] or {})
                strategy_rows.append(
                    {
                        "symbol": symbol,
                        "focus_role": focus_role,
                        "best_strategy_id": best.get("strategy_id"),
                        "best_strategy_name": best.get("strategy_name"),
                        "best_strategy_score": best.get("composite_score"),
                        "comparison_rows": comparisons,
                        "top_rows": comparisons[:3],
                    }
                )

    strategy_validation_snapshot = sval.build_strategy_validation_snapshot(
        now=now,
        history_period=history_period,
        default_strategy=runtime_strategy or {},
        strategy_research_rows=strategy_rows,
        source="weekend_research",
    )
    sval.save_strategy_validation_snapshot(strategy_validation_snapshot)
    sval.append_strategy_experiment_journal(strategy_validation_snapshot)
    strategy_governance_snapshot = sgov.build_strategy_governance_snapshot(
        strategies=strategies,
        validation_snapshot=strategy_validation_snapshot,
        now=now,
    )
    sgov.save_strategy_registry_state(strategy_governance_snapshot)
    evidence_layer = evid.build_evidence_layer(
        core_snapshot=core_snapshot,
        satellite_snapshot=satellite_snapshot,
        strategy_validation_snapshot=strategy_validation_snapshot,
        now=now,
    )

    snapshot = wr.build_weekend_research_snapshot(
        now=now,
        history_period=history_period,
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        core_rotation_snapshot=core_rotation_snapshot,
        core_snapshot=core_snapshot,
        satellite_snapshot=satellite_snapshot,
        strategy_research_rows=strategy_rows,
        strategy_validation_snapshot=strategy_validation_snapshot,
        strategy_governance_snapshot=strategy_governance_snapshot,
        evidence_layer=evidence_layer,
    )
    wr.save_weekend_research_snapshot(snapshot, path=snapshot_path)
    evid.append_weekend_research_journal(snapshot)
    report_text = wr.build_weekend_research_report(snapshot)
    report_files = wr.save_weekend_research_report_files(snapshot, report_text=report_text, reports_dir=reports_dir)
    wr.mark_weekend_research_done(now=now, alert_settings=alert_settings, snapshot=snapshot, state_path=state_path)

    delivery_results = []
    if bool(schedule["send_summary"]):
        delivery_results = message_router(
            "weekend_research_summary",
            subject=f"Weekend Research Report {now.strftime('%Y-%m-%d')}",
            body=report_text,
            config=normalized_config,
            environ=environ,
            slack_sender=slack_sender,
            email_sender=email_sender,
        )

    return {
        "ran": True,
        "snapshot": snapshot,
        "report_files": report_files,
        "delivery_results": delivery_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run the weekend research workflow.")
    parser.add_argument("--force", action="store_true", help="Run even if the weekend schedule is not due.")
    args = parser.parse_args()
    result = run_weekend_research(force=bool(args.force))
    print(f"Weekend research ran: {bool(result.get('ran'))}")
    if result.get("reason"):
        print(f"Reason: {result['reason']}")


if __name__ == "__main__":
    main()
