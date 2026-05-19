from datetime import datetime


def bootstrap_app_data(
    session_state,
    data_utils_module,
    *,
    refresh_interval_seconds: int,
    allow_startup_refresh: bool = True,
):
    """Load app data once, then auto-refresh prices when cache is stale."""
    if "app_data" not in session_state or data_utils_module.has_newer_editable_data():
        session_state["app_data"] = data_utils_module.load_data()

    if not allow_startup_refresh:
        return session_state["app_data"]

    refreshed_data, auto_refreshed = data_utils_module.auto_refresh_market_data(
        session_state["app_data"],
        refresh_interval_seconds=refresh_interval_seconds,
    )
    if auto_refreshed:
        session_state["app_data"] = refreshed_data
        data_utils_module.save_data(refreshed_data)
    return session_state["app_data"]

def apply_runtime_strategy_params(strategy, *, history_period: str):
    runtime_strategy = dict(strategy)
    runtime_params = dict(strategy.get("params", {}))
    runtime_params["period"] = history_period or runtime_params.get("period", "2y")
    runtime_strategy["params"] = runtime_params
    return runtime_strategy


def normalize_symbols(symbols):
    return sorted(
        {
            str(symbol).strip().upper()
            for symbol in (symbols or [])
            if symbol and str(symbol).strip()
        }
    )


def collect_tracked_symbols(data):
    combined = (data or {}).get("holdings", []) + (data or {}).get("watchlist", [])
    return normalize_symbols([item.get("symbol") for item in combined if item.get("symbol")])


def fetch_news_events_with_cache(
    *,
    session_state,
    fetcher_module,
    symbols,
    interval_seconds: int,
    force: bool = False,
    allow_initial_fetch: bool = True,
    now=None,
):
    now = now or datetime.now()
    normalized_symbols = normalize_symbols(symbols)
    cached_bundle = session_state.get("event_fetch_bundle")
    previous_symbols = cached_bundle.get("symbols", []) if isinstance(cached_bundle, dict) else []
    last_fetched_at = cached_bundle.get("fetched_at") if isinstance(cached_bundle, dict) else None

    should_refresh = fetcher_module.should_refresh_events_cache(
        last_fetched_at=last_fetched_at,
        previous_symbols=previous_symbols,
        current_symbols=normalized_symbols,
        interval_seconds=interval_seconds,
        now=now,
        force=force,
    )
    if should_refresh:
        if (
            not allow_initial_fetch
            and not isinstance(cached_bundle, dict)
            and not bool(session_state.get("_deferred_event_fetch_skipped_once"))
        ):
            session_state["_deferred_event_fetch_skipped_once"] = True
            return [], [], False
        events, source_reports = fetcher_module.fetch_events_from_sources(
            symbols=normalized_symbols,
            now=now,
        )
        session_state["event_fetch_bundle"] = {
            "events": events,
            "source_reports": source_reports,
            "symbols": normalized_symbols,
            "fetched_at": now.isoformat(),
        }
        return events, source_reports, True

    if not isinstance(cached_bundle, dict):
        return [], [], False
    return (
        list(cached_bundle.get("events", []) or []),
        list(cached_bundle.get("source_reports", []) or []),
        False,
    )


def enable_auto_news_rerun(
    *,
    session_state,
    interval_seconds: int,
    st_module,
    now_fn=None,
):
    fragment_decorator = getattr(st_module, "fragment", None) or getattr(st_module, "experimental_fragment", None)
    rerun_fn = getattr(st_module, "rerun", None) or getattr(st_module, "experimental_rerun", None)
    if fragment_decorator is None or rerun_fn is None:
        return False

    now_fn = now_fn or (lambda: datetime.now().timestamp())
    if "_news_auto_rerun_last" not in session_state:
        session_state["_news_auto_rerun_last"] = now_fn()

    @fragment_decorator(run_every=int(interval_seconds))
    def _news_refresh_heartbeat():
        now_ts = float(now_fn())
        last_ts = float(session_state.get("_news_auto_rerun_last", now_ts))
        if now_ts - last_ts < max(2.0, float(interval_seconds) * 0.8):
            return
        session_state["_news_auto_rerun_last"] = now_ts
        rerun_fn()

    _news_refresh_heartbeat()
    return True


def evaluate_market_risk_for_portfolio(
    *,
    holdings,
    history_period,
    load_historical_data_fn,
    load_correlation_matrix_fn,
    analyze_portfolio_risk_fn,
    build_market_risk_snapshot_fn,
    evaluate_market_risk_gate_fn,
    select_active_events_fn,
    evaluate_event_risk_switch_fn,
    merge_risk_gate_decisions_fn,
    fetch_events_from_sources_fn,
    event_symbols=None,
    now=None,
    fetched_events=None,
    source_reports=None,
):
    if not holdings:
        return None, None, None, None, [], None, []

    symbols = list(dict.fromkeys([h["symbol"] for h in holdings if h.get("current_price") is not None]))
    correlation_matrix = None
    if len(symbols) > 1:
        try:
            correlation_matrix = load_correlation_matrix_fn(tuple(sorted(symbols)), period="6mo")
        except Exception:
            correlation_matrix = None

    portfolio_risk = analyze_portfolio_risk_fn(
        holdings,
        correlation_matrix=correlation_matrix,
    )

    benchmark_history = load_historical_data_fn("SPY", period=history_period)
    vix_history = load_historical_data_fn("^VIX", period="6mo")
    snapshot = build_market_risk_snapshot_fn(
        benchmark_history=benchmark_history,
        vix_history=vix_history,
        sector_alert_count=len(portfolio_risk.sector_alerts),
        correlation_alert_count=len(portfolio_risk.correlation_alerts),
    )
    base_decision = evaluate_market_risk_gate_fn(snapshot)

    if fetched_events is None or source_reports is None:
        fetched_events, source_reports = fetch_events_from_sources_fn(
            symbols=event_symbols or symbols,
            now=now or datetime.now(),
        )
    active_events = select_active_events_fn(
        fetched_events,
        symbols=event_symbols or symbols,
        now=now,
        verified_only=False,
    )
    event_decision = evaluate_event_risk_switch_fn(
        active_events,
        vix=snapshot.vix,
        verified_only=True,
        now=now,
    )
    decision = merge_risk_gate_decisions_fn(base_decision, event_decision)
    return decision, snapshot, portfolio_risk, correlation_matrix, active_events, event_decision, source_reports
