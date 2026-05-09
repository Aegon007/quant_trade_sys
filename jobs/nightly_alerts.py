import argparse
from datetime import datetime

import alert_engine as ae
import analyst_consensus as ac
import data_utils as du
import notification_config as ncfg
import portfolio_advisor as pa
import quant_analysis as qa
from risk_gate import build_market_risk_snapshot_from_histories, evaluate_market_risk_gate


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
    notification_config_path=ncfg.NOTIFICATION_CONFIG_FILE,
    alert_state_path=ae.ALERT_STATE_FILE,
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
    config = ncfg.load_notification_config(notification_config_path)

    if dry_run:
        return {
            "alerts": ae.alerts_to_dicts(alerts),
            "sent_results": [],
            "dry_run": True,
        }

    sent_results = ae.send_new_alerts(
        alerts,
        config=config,
        state_path=alert_state_path,
        now=now,
    )
    return {
        "alerts": ae.alerts_to_dicts(alerts),
        "sent_results": sent_results,
        "dry_run": False,
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
