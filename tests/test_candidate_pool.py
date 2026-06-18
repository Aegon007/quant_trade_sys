import unittest

import pandas as pd


class SatelliteCandidatePoolTests(unittest.TestCase):
    def setUp(self):
        from quant_core.analytics import candidate_pool

        self.module = candidate_pool

    def test_build_satellite_candidate_pool_snapshot_ranks_and_limits_candidates(self):
        history = pd.DataFrame(
            {
                "Close": [100 + idx for idx in range(260)],
            }
        )

        snapshot = self.module.build_satellite_candidate_pool_snapshot(
            data={
                "account": {},
                "holdings": [{"symbol": "AAPL"}],
                "watchlist": [{"symbol": "MSFT"}],
            },
            strategy={"id": "ma_crossover", "params": {"period": "2y"}},
            history_period="2y",
            load_historical_data_fn=lambda symbol, period="2y": history,
            universe={
                "manual_include": ["MU", "ANET", "VRT"],
                "manual_exclude": [],
                "max_candidate_pool_size": 4,
                "max_deep_analysis_size": 2,
                "max_recommendations": 3,
                "candidate_persistence_days": 1,
            },
            core_symbols={"QQQ", "VOO"},
            policy={
                "candidate_entry_threshold": 55.0,
                "candidate_exit_threshold": 40.0,
                "candidate_persistence_days": 1,
                "satellite_max_single_weight_pct": 5.0,
            },
            discipline_snapshot={"can_open_new_satellite_positions": True},
            quant_analysis_snapshot_builder=lambda data, **kwargs: {
                "symbols": [
                    {
                        "symbol": row["symbol"],
                        "signal": "BUY",
                        "backtest": {"total_return": 0.12, "win_rate": 0.6, "sharpe_ratio": 1.0},
                        "monte_carlo": {"expected_return": 0.05, "positive_probability": 0.62},
                    }
                    for row in list(data.get("watchlist", []) or [])
                ]
            },
        )

        self.assertEqual(snapshot["summary"]["candidate_count"], 4)
        self.assertEqual(snapshot["summary"]["deep_analysis_count"], 2)
        self.assertLessEqual(len(snapshot["top_recommendations"]), 3)
        self.assertTrue(any(row["symbol"] == "MU" for row in snapshot["symbols"]))
        self.assertIn("confirmed_count", snapshot["summary"])


if __name__ == "__main__":
    unittest.main()
