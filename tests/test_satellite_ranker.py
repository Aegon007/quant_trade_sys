import unittest


class SatelliteRankerTests(unittest.TestCase):
    def setUp(self):
        from quant_core.analytics import satellite_ranker

        self.module = satellite_ranker

    def test_rank_satellite_candidates_respects_discipline_gate(self):
        ranked = self.module.rank_satellite_candidates(
            {
                "symbols": [
                    {
                        "symbol": "MU",
                        "signal": "BUY",
                        "return_3m": 0.18,
                        "return_6m": 0.30,
                        "return_12m": 0.45,
                        "high_proximity": 0.98,
                        "monte_carlo": {"expected_return": 0.05, "positive_probability": 0.64},
                        "backtest": {"total_return": 0.15, "sharpe_ratio": 1.2, "win_rate": 0.61},
                    }
                ]
            },
            policy={"candidate_entry_threshold": 65.0, "candidate_exit_threshold": 45.0, "satellite_max_single_weight_pct": 5.0},
            discipline_snapshot={"can_open_new_satellite_positions": False},
        )

        row = ranked["symbols"][0]
        self.assertEqual(row["recommendation_status"], "CONFIRMED")
        self.assertEqual(row["plan_action"], "WATCH")
        self.assertEqual(ranked["summary"]["top_recommendation_count"], 1)

    def test_rank_satellite_candidates_requires_promotion_support_for_new_top3(self):
        ranked = self.module.rank_satellite_candidates(
            {
                "symbols": [
                    {
                        "symbol": "MU",
                        "signal": "BUY",
                        "return_3m": 0.20,
                        "return_6m": 0.32,
                        "return_12m": 0.48,
                        "high_proximity": 0.97,
                        "monte_carlo": {"expected_return": 0.05, "positive_probability": 0.64},
                        "backtest": {"total_return": 0.15, "sharpe_ratio": 1.2, "win_rate": 0.61},
                    }
                ]
            },
            policy={
                "candidate_entry_threshold": 65.0,
                "candidate_exit_threshold": 45.0,
                "satellite_max_single_weight_pct": 5.0,
                "top3_promotion_confirmation_days": 2,
                "top3_demotion_confirmation_days": 2,
                "minimum_top3_residency_days": 2,
            },
            discipline_snapshot={"can_open_new_satellite_positions": True},
            previous_snapshot=None,
        )

        row = ranked["symbols"][0]
        self.assertEqual(row["top3_membership_state"], "INITIAL")
        self.assertEqual(ranked["summary"]["top_recommendation_count"], 1)

    def test_rank_satellite_candidates_marks_overheated_confirmed(self):
        ranked = self.module.rank_satellite_candidates(
            {
                "symbols": [
                    {
                        "symbol": "NVDA",
                        "signal": "BUY",
                        "return_3m": 0.42,
                        "return_6m": 0.60,
                        "return_12m": 0.95,
                        "high_proximity": 0.999,
                        "monte_carlo": {"expected_return": 0.08, "positive_probability": 0.7},
                        "backtest": {"total_return": 0.22, "sharpe_ratio": 1.5, "win_rate": 0.64},
                    }
                ]
            },
            policy={
                "candidate_entry_threshold": 65.0,
                "candidate_exit_threshold": 45.0,
                "satellite_max_single_weight_pct": 5.0,
                "top3_promotion_confirmation_days": 1,
                "top3_demotion_confirmation_days": 2,
                "minimum_top3_residency_days": 2,
            },
            discipline_snapshot={"can_open_new_satellite_positions": True},
        )

        row = ranked["symbols"][0]
        self.assertEqual(row["recommendation_status"], "OVERHEATED_CONFIRMED")
        self.assertEqual(row["plan_action"], "WATCH")


if __name__ == "__main__":
    unittest.main()
