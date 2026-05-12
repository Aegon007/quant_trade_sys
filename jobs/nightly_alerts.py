import argparse
from datetime import datetime

from quant_core.data import storage as du
from quant_core.data import market_data as md
from quant_core.notifications import alert_engine as ae
from quant_core.notifications import notification_channels as nch
from quant_core.events import analyst_consensus as ac
from quant_core.notifications import notification_config as ncfg
from quant_core.notifications import reporting as nr
from quant_core.portfolio import risk as pa
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from quant_core.analytics import quant_analysis as qa
from quant_core.analytics import portfolio_analysis as qpa
from quant_core.analytics.strategy_compare import compare_strategies_for_symbol
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
    report_builder=None,
    report_writer=None,
    quant_analysis_snapshot_builder=None,
    quant_analysis_report_builder=None,
    quant_analysis_report_writer=None,
    quant_analysis_snapshot_path=qpa.DEFAULT_QUANT_ANALYSIS_SNAPSHOT_FILE,
    environ=None,
):
    now = now or datetime.now()
    slack_sender = slack_sender or nch.send_slack_message
    report_builder = report_builder or nr.build_nightly_report
    report_writer = report_writer or nr.save_nightly_report_files
    quant_analysis_snapshot_builder = quant_analysis_snapshot_builder or qpa.build_portfolio_quant_analysis_snapshot
    quant_analysis_report_builder = quant_analysis_report_builder or nr.build_quant_analysis_report
    quant_analysis_report_writer = quant_analysis_report_writer or nr.save_quant_analysis_report_files
    md.reset_market_data_status()
    data = du.load_data()
    symbols = _tracked_symbols(data)

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
    transaction_rows = tx.normalize_transactions(tx.load_transactions())
    daily_recap = tx.summarize_daily_activity(transaction_rows, day=now)
    signal_attribution = nr.build_signal_attribution(transaction_rows, day=now)
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
    default_runtime_strategy = qpa.load_default_runtime_strategy(history_period=history_period)
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
        quant_analysis_snapshot = quant_analysis_snapshot_builder(
            data=data,
            strategy=default_runtime_strategy,
            history_period=history_period,
            engine_name="backtrader",
            risk_gate=risk_decision,
            allocation_regime=allocation_regime,
            now=now,
        )
        quant_analysis_change_summary = qpa.build_quant_analysis_change_summary(previous_quant_snapshot, quant_analysis_snapshot)
    else:
        previous_quant_snapshot = None
        quant_analysis_change_summary = {"has_changes": False, "message": ""}

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
        generated_at=now,
    )
    config = ncfg.apply_environment_overrides(
        ncfg.load_notification_config(notification_config_path),
        environ=environ,
    )

    if dry_run:
        return {
            "alerts": alert_dicts,
            "sent_results": [],
            "report_results": [],
            "report_files": {},
            "quant_analysis_report_files": {},
            "quant_analysis_change_results": [],
            "dry_run": True,
            "snapshot": snapshot,
        }

    sent_results = ae.send_new_alerts(
        alerts,
        config=config,
        state_path=alert_state_path,
        now=now,
    )
    journal_path = ss.append_snapshot_journal(snapshot, journal_path=snapshot_journal_path)
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
    report_results = []
    alert_settings = config.get("alert_settings", {}) if isinstance(config, dict) else {}
    if (
        config.get("slack", {}).get("enabled")
        and config.get("slack", {}).get("webhook_url")
        and bool(alert_settings.get("send_daily_summary", True))
    ):
        try:
            ok, message = slack_sender(report_text, config["slack"].get("webhook_url"))
            report_results.append({"channel": "slack", "ok": ok, "message": message})
        except Exception as exc:
            report_results.append({"channel": "slack", "ok": False, "message": f"nightly report failed: {exc}"})
    else:
        report_results.append({"channel": "slack", "ok": False, "message": "nightly report skipped: Slack webhook notifications are not enabled"})

    if (
        quant_analysis_snapshot is not None
        and bool(alert_settings.get("send_quant_analysis_change_summary", True))
        and config.get("slack", {}).get("enabled")
        and config.get("slack", {}).get("webhook_url")
    ):
        if quant_analysis_change_summary.get("has_changes"):
            try:
                ok, message = slack_sender(
                    quant_analysis_change_summary.get("message", ""),
                    config["slack"].get("webhook_url"),
                )
                quant_analysis_change_results.append({"channel": "slack", "ok": ok, "message": message})
            except Exception as exc:
                quant_analysis_change_results.append({"channel": "slack", "ok": False, "message": f"quant change summary failed: {exc}"})
        else:
            quant_analysis_change_results.append({"channel": "slack", "ok": False, "message": "quant change summary skipped: no material changes"})
    return {
        "alerts": alert_dicts,
        "sent_results": sent_results,
        "report_results": report_results,
        "report_files": report_files,
        "quant_analysis_report_files": quant_analysis_report_files,
        "quant_analysis_change_results": quant_analysis_change_results,
        "dry_run": False,
        "snapshot": snapshot,
        "snapshot_journal_path": journal_path,
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
