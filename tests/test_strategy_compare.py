import unittest

import pandas as pd

from engine.base import BacktestResult


class _FakeEngine:
    def __init__(self, result_map):
        self._result_map = result_map
        self._strategy = None
        self._data = None

    def set_data(self, data):
        self._data = data

    def set_strategy(self, strategy):
        self._strategy = strategy

    def run(self):
        strategy_id = self._strategy["id"]
        return self._result_map[strategy_id]


class StrategyCompareTests(unittest.TestCase):
    def test_compare_strategies_for_symbol_sorts_by_composite_score(self):
        from quant_core.analytics.strategy_compare import compare_strategies_for_symbol

        history = pd.DataFrame(
            {
                "Open": [100, 101, 102],
                "High": [101, 102, 103],
                "Low": [99, 100, 101],
                "Close": [100, 102, 101],
                "Volume": [1000, 1200, 1100],
            },
            index=pd.date_range("2026-01-01", periods=3, freq="D"),
        )

        result_map = {
            "strong": BacktestResult(
                total_return=0.20,
                sharpe_ratio=1.5,
                max_drawdown=-0.08,
                win_rate=0.65,
                total_trades=6,
                equity_curve=[100000, 102000, 104000],
                trade_log=[
                    {"action": "BUY", "price": 100, "date": "2026-01-01"},
                    {"action": "SELL", "price": 108, "date": "2026-01-03"},
                ],
            ),
            "weak": BacktestResult(
                total_return=-0.05,
                sharpe_ratio=-0.2,
                max_drawdown=-0.20,
                win_rate=0.35,
                total_trades=6,
                equity_curve=[100000, 99000, 95000],
                trade_log=[
                    {"action": "BUY", "price": 100, "date": "2026-01-01"},
                    {"action": "SELL", "price": 95, "date": "2026-01-03"},
                ],
            ),
        }

        rows = compare_strategies_for_symbol(
            symbol="AAPL",
            strategies=[
                {"id": "weak", "name": "Weak"},
                {"id": "strong", "name": "Strong"},
            ],
            load_historical_data_fn=lambda symbol, period: history,
            create_strategy_fn=lambda config: {"id": config["id"]},
            engine_factory_fn=lambda: _FakeEngine(result_map),
            history_period="2y",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["strategy_id"], "strong")
        self.assertGreater(rows[0]["composite_score"], rows[1]["composite_score"])


if __name__ == "__main__":
    unittest.main()

