import unittest
from datetime import datetime
from types import SimpleNamespace


class RuntimeOrchestrationTests(unittest.TestCase):
    def test_bootstrap_app_data_loads_and_saves_when_auto_refreshed(self):
        from app.orchestration import runtime

        session_state = {}
        saved_payloads = []

        data_utils_module = SimpleNamespace(
            has_newer_editable_data=lambda: False,
            load_data=lambda: {"holdings": [], "watchlist": [], "loaded": True},
            auto_refresh_market_data=lambda data, refresh_interval_seconds: (
                {**data, "prices_last_updated": "2026-05-10T00:00:00"},
                True,
            ),
            save_data=lambda data: saved_payloads.append(data),
        )

        data = runtime.bootstrap_app_data(session_state, data_utils_module, refresh_interval_seconds=300)

        self.assertIn("app_data", session_state)
        self.assertEqual(data["prices_last_updated"], "2026-05-10T00:00:00")
        self.assertEqual(len(saved_payloads), 1)

    def test_bootstrap_app_data_skips_save_when_not_refreshed(self):
        from app.orchestration import runtime

        session_state = {}
        saved_payloads = []

        data_utils_module = SimpleNamespace(
            has_newer_editable_data=lambda: False,
            load_data=lambda: {"holdings": [], "watchlist": []},
            auto_refresh_market_data=lambda data, refresh_interval_seconds: (data, False),
            save_data=lambda data: saved_payloads.append(data),
        )

        runtime.bootstrap_app_data(session_state, data_utils_module, refresh_interval_seconds=300)

        self.assertEqual(saved_payloads, [])

    def test_bootstrap_app_data_can_skip_startup_refresh(self):
        from app.orchestration import runtime

        session_state = {}
        call_state = {"refresh_calls": 0, "save_calls": 0}

        data_utils_module = SimpleNamespace(
            has_newer_editable_data=lambda: False,
            load_data=lambda: {"holdings": [], "watchlist": [], "loaded": True},
            auto_refresh_market_data=lambda data, refresh_interval_seconds: (
                call_state.__setitem__("refresh_calls", call_state["refresh_calls"] + 1) or data,
                False,
            ),
            save_data=lambda data: call_state.__setitem__("save_calls", call_state["save_calls"] + 1),
        )

        data = runtime.bootstrap_app_data(
            session_state,
            data_utils_module,
            refresh_interval_seconds=300,
            allow_startup_refresh=False,
        )

        self.assertTrue(data["loaded"])
        self.assertEqual(call_state["refresh_calls"], 0)
        self.assertEqual(call_state["save_calls"], 0)

    def test_apply_runtime_strategy_params_overrides_period(self):
        from app.orchestration import runtime

        strategy = {"id": "deep_tcn", "params": {"period": "1y", "epochs": 50}}
        runtime_strategy = runtime.apply_runtime_strategy_params(strategy, history_period="2y")

        self.assertEqual(runtime_strategy["params"]["period"], "2y")
        self.assertEqual(runtime_strategy["params"]["epochs"], 50)
        self.assertEqual(strategy["params"]["period"], "1y")

    def test_normalize_and_collect_symbols(self):
        from app.orchestration import runtime

        normalized = runtime.normalize_symbols([" aapl ", "MSFT", "", None, "aapl"])
        self.assertEqual(normalized, ["AAPL", "MSFT"])

        tracked = runtime.collect_tracked_symbols(
            {
                "holdings": [{"symbol": "qqq"}, {"symbol": "AAPL"}],
                "watchlist": [{"symbol": " tsla "}],
            }
        )
        self.assertEqual(tracked, ["AAPL", "QQQ", "TSLA"])

    def test_fetch_news_events_with_cache_refreshes_then_reuses_cache(self):
        from app.orchestration import runtime

        session_state = {}
        call_state = {"refresh_checks": 0, "fetch_calls": 0}

        def should_refresh_events_cache(**kwargs):
            call_state["refresh_checks"] += 1
            return call_state["refresh_checks"] == 1

        def fetch_events_from_sources(symbols, now):
            call_state["fetch_calls"] += 1
            return ([{"title": "headline", "symbols": symbols}], [{"source": "mock"}])

        fetcher_module = SimpleNamespace(
            should_refresh_events_cache=should_refresh_events_cache,
            fetch_events_from_sources=fetch_events_from_sources,
        )

        events, reports, refreshed = runtime.fetch_news_events_with_cache(
            session_state=session_state,
            fetcher_module=fetcher_module,
            symbols=["AAPL"],
            interval_seconds=600,
            now=datetime(2026, 5, 10, 8, 0, 0),
        )
        self.assertTrue(refreshed)
        self.assertEqual(call_state["fetch_calls"], 1)
        self.assertEqual(events[0]["symbols"], ["AAPL"])
        self.assertEqual(len(reports), 1)

        events2, reports2, refreshed2 = runtime.fetch_news_events_with_cache(
            session_state=session_state,
            fetcher_module=fetcher_module,
            symbols=["AAPL"],
            interval_seconds=600,
            now=datetime(2026, 5, 10, 8, 1, 0),
        )
        self.assertFalse(refreshed2)
        self.assertEqual(call_state["fetch_calls"], 1)
        self.assertEqual(events2[0]["title"], "headline")
        self.assertEqual(reports2[0]["source"], "mock")

    def test_fetch_news_events_with_cache_can_defer_initial_fetch_once(self):
        from app.orchestration import runtime

        session_state = {}
        call_state = {"fetch_calls": 0}

        def fetch_events_from_sources(symbols, now):
            call_state["fetch_calls"] += 1
            return ([{"title": "headline", "symbols": symbols}], [{"source": "mock"}])

        fetcher_module = SimpleNamespace(
            should_refresh_events_cache=lambda **kwargs: True,
            fetch_events_from_sources=fetch_events_from_sources,
        )

        events1, reports1, refreshed1 = runtime.fetch_news_events_with_cache(
            session_state=session_state,
            fetcher_module=fetcher_module,
            symbols=["AAPL"],
            interval_seconds=600,
            allow_initial_fetch=False,
            now=datetime(2026, 5, 10, 8, 0, 0),
        )
        self.assertEqual(events1, [])
        self.assertEqual(reports1, [])
        self.assertFalse(refreshed1)
        self.assertEqual(call_state["fetch_calls"], 0)

        events2, reports2, refreshed2 = runtime.fetch_news_events_with_cache(
            session_state=session_state,
            fetcher_module=fetcher_module,
            symbols=["AAPL"],
            interval_seconds=600,
            allow_initial_fetch=False,
            now=datetime(2026, 5, 10, 8, 0, 2),
        )
        self.assertTrue(refreshed2)
        self.assertEqual(call_state["fetch_calls"], 1)
        self.assertEqual(events2[0]["title"], "headline")
        self.assertEqual(reports2[0]["source"], "mock")

    def test_evaluate_market_risk_for_portfolio_returns_empty_result_without_holdings(self):
        from app.orchestration import runtime

        result = runtime.evaluate_market_risk_for_portfolio(
            holdings=[],
            history_period="2y",
            load_historical_data_fn=lambda symbol, period: None,
            load_correlation_matrix_fn=lambda symbols, period: None,
            analyze_portfolio_risk_fn=lambda holdings, correlation_matrix=None: None,
            build_market_risk_snapshot_fn=lambda **kwargs: None,
            evaluate_market_risk_gate_fn=lambda snapshot: None,
            select_active_events_fn=lambda events, symbols, now, verified_only: [],
            evaluate_event_risk_switch_fn=lambda active_events, vix, verified_only, now: None,
            merge_risk_gate_decisions_fn=lambda base, override: None,
            fetch_events_from_sources_fn=lambda symbols, now: ([], []),
        )

        self.assertEqual(result, (None, None, None, None, [], None, []))

    def test_enable_auto_news_rerun_triggers_rerun_on_interval_tick(self):
        from app.orchestration import runtime

        call_state = {"rerun_called": 0}

        class FakeSt:
            @staticmethod
            def fragment(run_every=0):
                def _decorator(func):
                    return func

                return _decorator

            @staticmethod
            def rerun():
                call_state["rerun_called"] += 1

        session_state = {"_news_auto_rerun_last": 0.0}
        enabled = runtime.enable_auto_news_rerun(
            session_state=session_state,
            interval_seconds=10,
            st_module=FakeSt,
            now_fn=lambda: 100.0,
        )

        self.assertTrue(enabled)
        self.assertEqual(call_state["rerun_called"], 1)

    def test_evaluate_market_risk_for_portfolio_uses_prefetched_events_when_provided(self):
        from app.orchestration import runtime

        call_state = {"fetch_calls": 0}

        def fetch_events_from_sources_fn(symbols, now):
            call_state["fetch_calls"] += 1
            return ([], [])

        holdings = [
            {"symbol": "AAPL", "current_price": 100.0},
            {"symbol": "MSFT", "current_price": 200.0},
        ]
        portfolio_risk = SimpleNamespace(sector_alerts=["x"], correlation_alerts=["y"])
        snapshot = SimpleNamespace(vix=20.0)
        base = SimpleNamespace(name="base")
        event = SimpleNamespace(name="event")
        merged = SimpleNamespace(name="merged")
        prefetched_events = [{"title": "prefetched"}]
        prefetched_reports = [{"source_id": "mock"}]

        result = runtime.evaluate_market_risk_for_portfolio(
            holdings=holdings,
            history_period="2y",
            load_historical_data_fn=lambda symbol, period: f"{symbol}:{period}",
            load_correlation_matrix_fn=lambda symbols, period: {"symbols": symbols, "period": period},
            analyze_portfolio_risk_fn=lambda holdings, correlation_matrix=None: portfolio_risk,
            build_market_risk_snapshot_fn=lambda **kwargs: snapshot,
            evaluate_market_risk_gate_fn=lambda snapshot: base,
            select_active_events_fn=lambda events, symbols, now, verified_only: events,
            evaluate_event_risk_switch_fn=lambda active_events, vix, verified_only, now: event,
            merge_risk_gate_decisions_fn=lambda base_decision, event_decision: merged,
            fetch_events_from_sources_fn=fetch_events_from_sources_fn,
            event_symbols=["AAPL", "MSFT"],
            fetched_events=prefetched_events,
            source_reports=prefetched_reports,
        )

        decision, risk_snapshot, portfolio_risk_out, corr, active_events, event_decision, reports = result
        self.assertIs(decision, merged)
        self.assertIs(risk_snapshot, snapshot)
        self.assertIs(portfolio_risk_out, portfolio_risk)
        self.assertEqual(corr["period"], "6mo")
        self.assertEqual(active_events, prefetched_events)
        self.assertIs(event_decision, event)
        self.assertEqual(reports, prefetched_reports)
        self.assertEqual(call_state["fetch_calls"], 0)


if __name__ == "__main__":
    unittest.main()
