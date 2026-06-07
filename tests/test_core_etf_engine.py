import unittest
from datetime import datetime

from tests.support import clear_modules, reload_module


class CoreEtfEngineTests(unittest.TestCase):
    def setUp(self):
        clear_modules(
            "quant_core.analytics.core_etf_rotation",
            "quant_core.portfolio.core_etf_engine",
        )
        self.rotation = reload_module("quant_core.analytics.core_etf_rotation")
        self.engine = reload_module("quant_core.portfolio.core_etf_engine")

    def test_build_core_etf_snapshot_requires_confirmation_before_accumulate(self):
        rotation_snapshot = {
            "symbols": [
                {
                    "symbol": "VOO",
                    "enabled": True,
                    "role": "broad_market",
                    "current_price": 500.0,
                    "rotation_score": 82.0,
                    "rotation_status": "FOCUS",
                    "confidence": 0.82,
                    "expected_return_3m": 0.04,
                    "expected_return_12m": 0.12,
                    "ma50": 490.0,
                    "rotation_backtest": {"excess_return": 0.03},
                }
            ]
        }
        snapshot1 = self.engine.build_core_etf_snapshot(
            data={"holdings": [], "watchlist": []},
            account_snapshot={"total_capital": 10000.0},
            rotation_snapshot=rotation_snapshot,
            previous_snapshot=None,
            now=datetime(2026, 5, 13, 22, 0, 0),
        )
        snapshot2 = self.engine.build_core_etf_snapshot(
            data={"holdings": [], "watchlist": []},
            account_snapshot={"total_capital": 10000.0},
            rotation_snapshot=rotation_snapshot,
            previous_snapshot=snapshot1,
            now=datetime(2026, 5, 14, 22, 0, 0),
        )

        self.assertEqual(snapshot1["symbols"][0]["action"], "HOLD")
        self.assertEqual(snapshot1["symbols"][0]["proposed_action"], "ACCUMULATE")
        self.assertEqual(snapshot2["symbols"][0]["action"], "ACCUMULATE")
        self.assertGreater(snapshot2["symbols"][0]["target_weight_pct"], 0.0)

    def test_build_core_etf_snapshot_risk_off_for_growth_moves_to_risk_exit(self):
        rotation_snapshot = {
            "symbols": [
                {
                    "symbol": "QQQ",
                    "enabled": True,
                    "role": "growth",
                    "current_price": 450.0,
                    "rotation_score": 68.0,
                    "rotation_status": "WATCH",
                    "confidence": 0.68,
                    "expected_return_3m": 0.03,
                    "expected_return_12m": 0.10,
                    "ma50": 440.0,
                    "rotation_backtest": {"excess_return": -0.01},
                }
            ]
        }
        risk_gate = type("Risk", (), {"regime": "RISK_OFF", "block_new_buys": True})()
        allocation_regime = type(
            "Alloc",
            (),
            {
                "regime": "STOP",
                "block_new_buys": True,
                "target_exposure_min_pct": 10.0,
                "target_exposure_max_pct": 40.0,
            },
        )()
        snapshot = self.engine.build_core_etf_snapshot(
            data={
                "holdings": [{"symbol": "QQQ", "shares": 10.0, "current_price": 450.0}],
                "watchlist": [],
            },
            account_snapshot={"total_capital": 10000.0},
            rotation_snapshot=rotation_snapshot,
            risk_gate=risk_gate,
            allocation_regime=allocation_regime,
            now=datetime(2026, 5, 13, 22, 0, 0),
        )

        self.assertEqual(snapshot["symbols"][0]["action"], "RISK_EXIT")
        self.assertEqual(snapshot["symbols"][0]["regime_alignment"], "NEGATIVE")

    def test_build_core_etf_snapshot_adds_stability_fields(self):
        rotation_snapshot = {
            "symbols": [
                {
                    "symbol": "VOO",
                    "enabled": True,
                    "role": "broad_market",
                    "current_price": 500.0,
                    "rotation_score": 82.0,
                    "rotation_status": "FOCUS",
                    "confidence": 0.82,
                    "expected_return_3m": 0.04,
                    "expected_return_12m": 0.12,
                    "ma50": 490.0,
                    "volatility": 0.18,
                    "rotation_backtest": {"excess_return": 0.03},
                }
            ]
        }
        snapshot1 = self.engine.build_core_etf_snapshot(
            data={"holdings": [], "watchlist": []},
            account_snapshot={"total_capital": 10000.0},
            rotation_snapshot=rotation_snapshot,
            previous_snapshot=None,
            now=datetime(2026, 5, 13, 22, 0, 0),
        )
        snapshot2 = self.engine.build_core_etf_snapshot(
            data={"holdings": [], "watchlist": []},
            account_snapshot={"total_capital": 10000.0},
            rotation_snapshot=rotation_snapshot,
            previous_snapshot=snapshot1,
            now=datetime(2026, 5, 14, 22, 0, 0),
        )

        row = snapshot2["symbols"][0]
        self.assertIn("signal_stability_score", row)
        self.assertIn("days_in_same_action", row)
        self.assertIn("days_since_regime_change", row)
        self.assertGreaterEqual(row["signal_stability_score"], 0.0)
        self.assertGreaterEqual(row["days_in_same_action"], 1)
        self.assertGreaterEqual(snapshot2["summary"]["avg_signal_stability_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
