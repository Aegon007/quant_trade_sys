import unittest

import numpy as np
import pandas as pd


class MonteCarloTests(unittest.TestCase):
    def test_simulate_price_paths_returns_distribution_metrics(self):
        from monte_carlo import simulate_return_distribution

        index = pd.date_range("2025-01-01", periods=260, freq="D")
        close = 100 + np.linspace(0, 15, 260) + np.sin(np.arange(260) / 8)
        history = pd.DataFrame({"Close": close}, index=index)

        dist = simulate_return_distribution(
            history,
            horizon_days=20,
            simulations=2000,
            seed=7,
        )

        self.assertIsNotNone(dist)
        self.assertEqual(dist.horizon_days, 20)
        self.assertEqual(dist.simulations, 2000)
        self.assertLessEqual(dist.var_95, dist.p05_return)
        self.assertLessEqual(dist.p05_return, dist.p95_return)
        self.assertLessEqual(dist.cvar_95, dist.var_95)
        self.assertGreaterEqual(dist.positive_probability, 0.0)
        self.assertLessEqual(dist.positive_probability, 1.0)
        self.assertAlmostEqual(
            dist.expected_price,
            dist.latest_price * (1.0 + dist.expected_return),
            places=6,
        )

    def test_simulate_price_paths_returns_none_when_insufficient_data(self):
        from monte_carlo import simulate_return_distribution

        history = pd.DataFrame({"Close": [100.0, 101.0, 102.0]})
        self.assertIsNone(simulate_return_distribution(history, horizon_days=20, simulations=500))


if __name__ == "__main__":
    unittest.main()
