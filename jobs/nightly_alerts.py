import argparse
from datetime import datetime

from quant_core.data import storage as du
from quant_core.notifications import alert_engine as ae
from quant_core.events import analyst_consensus as ac
from quant_core.notifications import notification_config as ncfg
from quant_core.portfolio import risk as pa
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from quant_core.analytics import quant_analysis as qa
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
):
    now = now or datetime.now()
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

    snapshot = ss.build_system_snapshot(
        data=data,
        risk_gate=risk_decision,
        alerts=alert_dicts,
        performance={
            "live_scoreboard": {
                "completed_trades": int(getattr(live_scoreboard, "completed_trades", 0) or 0),
                "win_rate": getattr(live_scoreboard, "win_rate", None),
                "expectancy_return_pct": getattr(live_scoreboard, "expectancy_return_pct", None),
                "profit_factor": getattr(live_scoreboard, "profit_factor", None),
                "max_drawdown_pct": getattr(live_scoreboard, "max_drawdown_pct", None),
            },
            "strategy_comparison": strategy_comparison_rows,
        },
        allocation_regime=allocation_regime.to_dict(),
        generated_at=now,
    )
    config = ncfg.load_notification_config(notification_config_path)

    if dry_run:
        return {
            "alerts": alert_dicts,
            "sent_results": [],
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
    return {
        "alerts": alert_dicts,
        "sent_results": sent_results,
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
