import unittest
from datetime import datetime, timedelta

from quant_core.data import data_health
from quant_core.execution import plan_quality
from quant_core.monitoring import market_monitor
from quant_core.research import strategy_governance
from quant_core.research import evidence_collector
from quant_core.models import registry as model_registry


class Step3FoundationsTests(unittest.TestCase):
    def test_data_health_marks_nan_and_missing_as_degraded(self):
        now = datetime.fromisoformat("2026-06-11T12:00:00")
        snapshot = data_health.build_data_health_snapshot(
            {
                "holdings": [{"symbol": "AAPL", "current_price": float("nan")}],
                "watchlist": [{"symbol": "MSFT", "last_price": None}],
            },
            data_sources={"prices": {"primary_symbols": 0, "fallback_symbols": 1, "last_error": "fallback used"}},
            price_cache={
                "AAPL": {"price": 100.0, "timestamp": now.timestamp(), "source": "yfinance"},
                "MSFT": {"price": 200.0, "timestamp": now.timestamp() - 10_000, "source": "stooq"},
            },
            now=now,
        )

        self.assertEqual(snapshot["status"], "BROKEN")
        self.assertEqual(snapshot["summary"]["invalid_price_count"], 1)
        self.assertEqual(snapshot["summary"]["missing_price_count"], 1)
        self.assertIn("AAPL", snapshot["invalid_symbols"])
        self.assertIn("MSFT", snapshot["missing_symbols"])

    def test_plan_quality_summarizes_reachable_missed_and_groups(self):
        snapshot = plan_quality.build_plan_quality_snapshot(
            trade_plan={
                "decision": "ACTION",
                "action_count": 2,
                "items": [
                    {"symbol": "VOO", "plan_action": "ACCUMULATE", "list_type": "core"},
                    {"symbol": "MU", "plan_action": "PROBE", "list_type": "candidate_pool"},
                ],
            },
            latest_review={
                "review_day": "2026-06-10",
                "executed_count": 1,
                "missed_count": 1,
                "missed_reachable_count": 1,
                "unplanned_trade_count": 1,
                "items": [
                    {"symbol": "VOO", "plan_action": "ACCUMULATE", "list_type": "core", "status": "EXECUTED"},
                    {
                        "symbol": "MU",
                        "plan_action": "PROBE",
                        "list_type": "candidate_pool",
                        "status": "MISSED",
                        "opportunity_status": "REACHABLE",
                    },
                ],
            },
            core_symbols=["VOO"],
            now=datetime.fromisoformat("2026-06-11T12:00:00"),
        )

        self.assertEqual(snapshot["status"], "DEGRADED")
        self.assertEqual(snapshot["summary"]["missed_reachable_count"], 1)
        self.assertEqual(snapshot["groups"]["core"]["executed_count"], 1)
        self.assertEqual(snapshot["groups"]["satellite"]["missed_reachable_count"], 1)

    def test_market_monitor_wraps_tactical_snapshot(self):
        snapshot = market_monitor.build_market_monitor_snapshot(
            tactical_snapshot={
                "generated_at": "2026-06-11T12:00:00",
                "state": "CAPITULATION",
                "recommended_action": "DO_NOT_CHASE",
                "recommended_symbol": "SQQQ",
                "message": "Do not chase inverse ETF.",
                "benchmark_rows": [{"symbol": "QQQ", "current_price": 100, "previous_close": 104, "change_pct": -0.038}],
                "tactical_rows": [{"symbol": "SQQQ", "current_price": 44, "previous_close": 40, "change_pct": 0.1}],
            },
            data_health_snapshot={"status": "OK"},
            now=datetime.fromisoformat("2026-06-11T12:00:00"),
        )

        self.assertEqual(snapshot["status"], "URGENT")
        self.assertEqual(snapshot["summary"]["recommended_action"], "DO_NOT_CHASE")
        self.assertEqual(snapshot["events"][0]["event_type"], "TACTICAL_DO_NOT_CHASE")

    def test_strategy_governance_never_auto_switches_default(self):
        validation = {
            "summary": {"status": "REVIEW", "symbol_count": 2},
            "symbols": [
                {"symbol": "AAPL", "best_strategy_id": "candidate_a"},
                {"symbol": "MSFT", "best_strategy_id": "candidate_a"},
            ],
        }

        snapshot = strategy_governance.build_strategy_governance_snapshot(
            strategies=[
                {"id": "production_model", "name": "Production", "enabled": True, "is_default": True},
                {"id": "candidate_a", "name": "Candidate A", "enabled": True},
            ],
            validation_snapshot=validation,
            now=datetime.fromisoformat("2026-06-11T12:00:00"),
        )

        self.assertEqual(snapshot["status"], "REVIEW")
        states = {row["strategy_id"]: row["lifecycle_state"] for row in snapshot["strategies"]}
        self.assertEqual(states["production_model"], "REVIEW")
        self.assertEqual(states["candidate_a"], "PROMOTION_WATCH")
        self.assertTrue(any(row["type"] == "DEFAULT_REVIEW" for row in snapshot["recommendations"]))

    def test_model_registry_defaults_to_foundation_engine(self):
        with self.subTest("default config"):
            config = model_registry.default_model_registry()
            self.assertEqual(config["models"][0]["model_id"], "foundation_quant_engine")
            self.assertTrue(config["models"][0]["is_default"])
            self.assertEqual(config["models"][0]["adapter_path"], "quant_core.models.foundation.pipeline.run_foundation_job")
            self.assertEqual(config["models"][1]["model_id"], "finance_multi_asset_transformer")
            self.assertEqual(config["models"][1]["role"], "legacy_benchmark")
            self.assertFalse(config["models"][1]["enabled"])

    def test_evidence_layer_collects_structured_sources(self):
        snapshot = evidence_collector.build_evidence_layer(
            core_snapshot={"generated_at": "2026-06-11T12:00:00", "summary": {"focus_symbols": ["VOO"], "accumulate_count": 1}},
            satellite_snapshot={"generated_at": "2026-06-11T12:00:00", "summary": {"top_symbols": ["MU"], "candidate_count": 10}},
            strategy_validation_snapshot={"generated_at": "2026-06-11T12:00:00", "summary": {"status": "READY", "message": "ok"}},
            now=datetime.fromisoformat("2026-06-11T12:00:00"),
        )

        self.assertEqual(snapshot["evidence_count"], 3)
        self.assertIn("LLM summaries are evidence only", snapshot["constraints"][1])


if __name__ == "__main__":
    unittest.main()
