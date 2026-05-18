import importlib
import unittest

from tests.support import clear_modules, install_fake_yfinance, reload_module


class PackageImportTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules(
            "quant_core.paths",
            "quant_core.data.storage",
            "quant_core.ledger.transactions",
            "quant_core.ledger.robinhood_csv",
            "quant_core.portfolio.actions",
            "quant_core.portfolio.reconciliation",
            "quant_core.portfolio.metrics",
            "quant_core.portfolio.risk",
            "quant_core.portfolio.allocation",
            "quant_core.portfolio.core_etf_engine",
            "quant_core.portfolio.discipline",
            "quant_core.portfolio.position",
            "quant_core.analytics.quant_analysis",
            "quant_core.analytics.monte_carlo",
            "quant_core.analytics.core_etf_rotation",
            "quant_core.analytics.candidate_pool",
            "quant_core.analytics.satellite_ranker",
            "quant_core.analytics.portfolio_analysis",
            "quant_core.risk.risk_gate",
            "quant_core.events.event_news",
            "quant_core.events.event_fetcher",
            "quant_core.events.news_summary",
            "quant_core.events.analyst_consensus",
            "quant_core.events.finbert_sentiment",
            "quant_core.notifications.notification_config",
            "quant_core.notifications.notification_channels",
            "quant_core.notifications.delivery_router",
            "quant_core.notifications.change_feed",
            "quant_core.notifications.alert_engine",
            "quant_core.notifications.reporting",
            "quant_core.execution.nightly_planner",
            "quant_core.execution.nightly_manifest",
            "quant_core.execution.post_close_review",
            "quant_core.monitoring.intraday_monitor",
            "quant_core.llm.openai_compatible",
            "quant_core.snapshots.system_snapshot",
            "integrations.slack.command_parser",
            "integrations.slack.command_service",
            "app.ui.components",
            "strategies.ui",
            "strategies.registry",
        )

    def test_package_paths_are_importable(self):
        storage = reload_module("quant_core.data.storage")
        market_data = reload_module("quant_core.data.market_data")
        ledger = reload_module("quant_core.ledger.transactions")
        robinhood_csv = reload_module("quant_core.ledger.robinhood_csv")
        portfolio_actions = reload_module("quant_core.portfolio.actions")
        portfolio_reconciliation = reload_module("quant_core.portfolio.reconciliation")
        portfolio_metrics_pkg = reload_module("quant_core.portfolio.metrics")
        portfolio_risk_pkg = reload_module("quant_core.portfolio.risk")
        portfolio_allocation_pkg = reload_module("quant_core.portfolio.allocation")
        core_etf_engine_pkg = reload_module("quant_core.portfolio.core_etf_engine")
        discipline_pkg = reload_module("quant_core.portfolio.discipline")
        portfolio_position_pkg = reload_module("quant_core.portfolio.position")
        quant_analysis = reload_module("quant_core.analytics.quant_analysis")
        monte_carlo = reload_module("quant_core.analytics.monte_carlo")
        core_etf_rotation = reload_module("quant_core.analytics.core_etf_rotation")
        candidate_pool = reload_module("quant_core.analytics.candidate_pool")
        satellite_ranker = reload_module("quant_core.analytics.satellite_ranker")
        portfolio_analysis = reload_module("quant_core.analytics.portfolio_analysis")
        risk_gate = reload_module("quant_core.risk.risk_gate")
        event_news = reload_module("quant_core.events.event_news")
        finbert_sentiment = reload_module("quant_core.events.finbert_sentiment")
        event_fetcher = reload_module("quant_core.events.event_fetcher")
        news_summary = reload_module("quant_core.events.news_summary")
        analyst_consensus = reload_module("quant_core.events.analyst_consensus")
        notification_config = reload_module("quant_core.notifications.notification_config")
        notification_channels = reload_module("quant_core.notifications.notification_channels")
        delivery_router = reload_module("quant_core.notifications.delivery_router")
        change_feed = reload_module("quant_core.notifications.change_feed")
        alert_engine = reload_module("quant_core.notifications.alert_engine")
        reporting = reload_module("quant_core.notifications.reporting")
        nightly_planner = reload_module("quant_core.execution.nightly_planner")
        nightly_manifest = reload_module("quant_core.execution.nightly_manifest")
        post_close_review = reload_module("quant_core.execution.post_close_review")
        intraday_monitor = reload_module("quant_core.monitoring.intraday_monitor")
        llm_client = reload_module("quant_core.llm.openai_compatible")
        system_snapshot = reload_module("quant_core.snapshots.system_snapshot")
        parser = reload_module("integrations.slack.command_parser")
        service = reload_module("integrations.slack.command_service")
        ui_components = reload_module("app.ui.components")
        strategy_ui = reload_module("strategies.ui")
        strategy_registry = reload_module("strategies.registry")

        self.assertTrue(hasattr(storage, "load_data"))
        self.assertTrue(hasattr(market_data, "fetch_stooq_history"))
        self.assertTrue(hasattr(ledger, "add_transaction"))
        self.assertTrue(hasattr(ledger, "import_robinhood_activity_csv"))
        self.assertTrue(hasattr(robinhood_csv, "parse_robinhood_activity_csv"))
        self.assertTrue(hasattr(portfolio_actions, "buy_symbol"))
        self.assertTrue(hasattr(portfolio_actions, "reconcile_portfolio_from_robinhood_imports"))
        self.assertTrue(hasattr(portfolio_reconciliation, "build_robinhood_reconciled_portfolio"))
        self.assertTrue(hasattr(portfolio_metrics_pkg, "summarize_holdings"))
        self.assertTrue(hasattr(portfolio_risk_pkg, "analyze_portfolio_risk"))
        self.assertTrue(hasattr(portfolio_allocation_pkg, "recommend_allocation"))
        self.assertTrue(hasattr(core_etf_engine_pkg, "build_core_etf_snapshot"))
        self.assertTrue(hasattr(discipline_pkg, "build_discipline_snapshot"))
        self.assertTrue(hasattr(portfolio_position_pkg, "recommend_position_action"))
        self.assertTrue(hasattr(quant_analysis, "get_historical_data"))
        self.assertTrue(hasattr(monte_carlo, "simulate_return_distribution"))
        self.assertTrue(hasattr(core_etf_rotation, "build_core_etf_rotation_snapshot"))
        self.assertTrue(hasattr(candidate_pool, "build_satellite_candidate_pool_snapshot"))
        self.assertTrue(hasattr(satellite_ranker, "rank_satellite_candidates"))
        self.assertTrue(hasattr(portfolio_analysis, "build_portfolio_quant_analysis_snapshot"))
        self.assertTrue(hasattr(portfolio_analysis, "save_quant_analysis_snapshot"))
        self.assertTrue(hasattr(portfolio_analysis, "evaluate_auto_refresh_trigger"))
        self.assertTrue(hasattr(risk_gate, "evaluate_market_risk_gate"))
        self.assertTrue(hasattr(event_news, "load_market_events"))
        self.assertTrue(hasattr(event_fetcher, "fetch_events_from_sources"))
        self.assertTrue(hasattr(news_summary, "summarize_news_events"))
        self.assertTrue(hasattr(analyst_consensus, "refresh_analyst_consensus_cache"))
        self.assertTrue(hasattr(finbert_sentiment, "analyze_financial_sentiment"))
        self.assertTrue(hasattr(notification_config, "load_notification_config"))
        self.assertTrue(hasattr(notification_channels, "send_slack_message"))
        self.assertTrue(hasattr(delivery_router, "deliver_message"))
        self.assertTrue(hasattr(change_feed, "build_change_feed"))
        self.assertTrue(hasattr(alert_engine, "collect_alerts"))
        self.assertTrue(hasattr(reporting, "build_nightly_report"))
        self.assertTrue(hasattr(nightly_planner, "build_next_day_trade_plan"))
        self.assertTrue(hasattr(nightly_manifest, "initialize_nightly_run_manifest"))
        self.assertTrue(hasattr(post_close_review, "build_execution_review"))
        self.assertTrue(hasattr(intraday_monitor, "classify_intraday_event"))
        self.assertTrue(hasattr(llm_client, "call_openai_compatible_chat"))
        self.assertTrue(hasattr(system_snapshot, "build_system_snapshot"))
        self.assertTrue(hasattr(parser, "parse_slack_command"))
        self.assertTrue(hasattr(service, "execute_slack_command"))
        self.assertTrue(hasattr(ui_components, "build_watchlist_records"))
        self.assertTrue(hasattr(strategy_ui, "load_strategies"))
        self.assertTrue(hasattr(strategy_registry, "create_strategy"))

    def test_legacy_root_compat_modules_are_removed(self):
        removed = [
            "alert_engine",
            "analyst_consensus",
            "capital_allocator",
            "data_utils",
            "event_fetcher",
            "event_news",
            "finbert_sentiment",
            "monte_carlo",
            "news_summary",
            "notification_channels",
            "notification_config",
            "portfolio_actions",
            "portfolio_advisor",
            "portfolio_metrics",
            "position_advisor",
            "quant_analysis",
            "risk_gate",
            "slack_command_parser",
            "slack_command_service",
            "system_snapshot",
            "transactions",
            "ui_components",
            "strategy_ui",
            "strategy_registry",
        ]
        for module_name in removed:
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
