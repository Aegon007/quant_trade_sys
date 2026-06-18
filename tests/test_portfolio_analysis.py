import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from engine.base import BacktestResult


def make_ohlcv(close_values):
    index = pd.date_range("2026-01-01", periods=len(close_values), freq="D")
    close = pd.Series(close_values, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Volume": [1_000_000] * len(close),
        },
        index=index,
    )


class _FakeEngine:
    def __init__(self, result_map):
        self._result_map = result_map
        self._strategy = None

    def set_data(self, data):
        self._data = data

    def set_strategy(self, strategy):
        self._strategy = strategy

    def run(self):
        return self._result_map[self._strategy["symbol"]]


class PortfolioAnalysisTests(unittest.TestCase):
    def test_build_portfolio_quant_analysis_snapshot_aggregates_holdings_and_watchlist(self):
        from quant_core.analytics.portfolio_analysis import build_portfolio_quant_analysis_snapshot

        histories = {
            "AAPL": make_ohlcv([100, 101, 103, 105, 107, 109]),
            "MSFT": make_ohlcv([200, 201, 199, 202, 204, 206]),
        }
        result_map = {
            "AAPL": BacktestResult(
                total_return=0.15,
                sharpe_ratio=1.2,
                max_drawdown=-0.07,
                win_rate=0.60,
                total_trades=2,
                equity_curve=[100000, 103000, 115000],
                trade_log=[
                    {"action": "BUY", "price": 100.0, "date": "2026-01-02"},
                    {"action": "SELL", "price": 110.0, "date": "2026-01-05"},
                ],
            ),
            "MSFT": BacktestResult(
                total_return=-0.02,
                sharpe_ratio=-0.1,
                max_drawdown=-0.09,
                win_rate=0.0,
                total_trades=0,
                equity_curve=[100000, 99500, 98000],
                trade_log=[],
            ),
        }

        snapshot = build_portfolio_quant_analysis_snapshot(
            {
                "account": {"cash_available": 5000.0},
                "holdings": [{"symbol": "AAPL", "shares": 10.0, "current_price": 109.0, "cost": 95.0, "sector": "Tech"}],
                "watchlist": [{"symbol": "MSFT", "last_price": 206.0, "notes": "watch"}],
            },
            strategy={"id": "ma_crossover", "name": "MA", "params": {"period": "2y"}},
            history_period="2y",
            load_historical_data_fn=lambda symbol, period="2y": histories[symbol].copy(),
            get_signal_fn=lambda strategy, symbol: ("BUY", "trend healthy") if symbol == "AAPL" else ("HOLD", "waiting"),
            create_strategy_fn=lambda config: {"id": config["id"], "symbol": config["symbol"]},
            engine_factory_fn=lambda: _FakeEngine(result_map),
            monte_carlo_fn=lambda hist, horizon_days=20, simulations=2000, seed=42: SimpleNamespace(
                expected_return=0.03,
                positive_probability=0.62,
                var_95=-0.05,
                cvar_95=-0.08,
                expected_price=float(hist["Close"].iloc[-1]) * 1.03,
                p05_price=float(hist["Close"].iloc[-1]) * 0.95,
                p95_price=float(hist["Close"].iloc[-1]) * 1.08,
            ),
            now=datetime(2026, 5, 11, 23, 0, 0),
        )

        self.assertEqual(snapshot["summary"]["total_symbols"], 2)
        self.assertEqual(snapshot["summary"]["analyzed_symbols"], 2)
        self.assertEqual(snapshot["summary"]["buy_count"], 1)
        self.assertEqual(snapshot["summary"]["hold_count"], 1)
        self.assertEqual(snapshot["strategy"]["id"], "ma_crossover")
        self.assertEqual(snapshot["symbols"][0]["symbol"], "AAPL")
        self.assertEqual(snapshot["symbols"][0]["list_type"], "holding")
        self.assertEqual(snapshot["symbols"][0]["backtest"]["total_return"], 0.15)
        self.assertEqual(snapshot["symbols"][0]["position_advice"]["action"], "TRIM")
        self.assertEqual(snapshot["symbols"][1]["symbol"], "MSFT")
        self.assertEqual(snapshot["symbols"][1]["list_type"], "watchlist")
        self.assertIn("AAPL", snapshot["summary"]["top_buy_symbols"])

    def test_save_quant_analysis_report_files_writes_pdf_markdown_and_json(self):
        from quant_core.notifications.reporting import save_quant_analysis_report_files

        snapshot = {
            "generated_at": "2026-05-11T23:30:00",
            "strategy": {"id": "ma_crossover", "name": "MA"},
            "engine": {"name": "backtrader"},
            "history_period": "2y",
            "summary": {
                "total_symbols": 2,
                "analyzed_symbols": 2,
                "buy_count": 1,
                "sell_count": 0,
                "hold_count": 1,
                "error_count": 0,
                "top_buy_symbols": ["AAPL"],
            },
            "symbols": [
                {
                    "symbol": "AAPL",
                    "list_type": "holding",
                    "signal": "BUY",
                    "latest_price": 109.0,
                    "backtest": {"total_return": 0.15, "sharpe_ratio": 1.2, "win_rate": 0.6, "max_drawdown": -0.07},
                    "monte_carlo": {"expected_return": 0.03, "positive_probability": 0.62},
                    "position_advice": {"action": "ADD", "target_weight_pct": 15.0},
                },
                {
                    "symbol": "MSFT",
                    "list_type": "watchlist",
                    "signal": "HOLD",
                    "latest_price": 206.0,
                    "backtest": {"total_return": -0.02, "sharpe_ratio": -0.1, "win_rate": 0.0, "max_drawdown": -0.09},
                    "monte_carlo": {"expected_return": 0.01, "positive_probability": 0.52},
                    "position_advice": None,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            files = save_quant_analysis_report_files(snapshot, reports_dir=temp_dir)

            self.assertTrue(files["markdown_path"].endswith(".md"))
            self.assertTrue(files["json_path"].endswith(".json"))
            self.assertTrue(files["pdf_path"].endswith(".pdf"))
            self.assertTrue(pd.notna(files["saved_at_unix"]))

            with open(files["pdf_path"], "rb") as handle:
                self.assertEqual(handle.read(4), b"%PDF")

            with open(files["latest_json_path"], "r", encoding="utf-8") as handle:
                self.assertIn('"total_symbols": 2', handle.read())

    def test_save_and_load_quant_analysis_snapshot_round_trip(self):
        from quant_core.analytics.portfolio_analysis import load_quant_analysis_snapshot, save_quant_analysis_snapshot

        snapshot = {
            "generated_at": "2026-05-11T23:30:00",
            "summary": {"total_symbols": 1},
            "symbols": [{"symbol": "AAPL", "signal": "BUY"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/quant_analysis_snapshot.json"
            save_quant_analysis_snapshot(snapshot, path=path)
            loaded = load_quant_analysis_snapshot(path=path)

        self.assertEqual(loaded["summary"]["total_symbols"], 1)
        self.assertEqual(loaded["symbols"][0]["symbol"], "AAPL")

    def test_build_quant_analysis_change_summary_detects_signal_and_action_changes(self):
        from quant_core.analytics.portfolio_analysis import build_quant_analysis_change_summary

        previous = {
            "generated_at": "2026-05-10T23:00:00",
            "summary": {"top_buy_symbols": ["MSFT"]},
            "symbols": [
                {"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}},
                {"symbol": "MSFT", "signal": "BUY", "position_advice": {"action": "ADD"}},
            ],
        }
        current = {
            "generated_at": "2026-05-11T23:00:00",
            "summary": {"top_buy_symbols": ["AAPL"]},
            "symbols": [
                {"symbol": "AAPL", "signal": "BUY", "position_advice": {"action": "ADD"}},
                {"symbol": "MSFT", "signal": "HOLD", "position_advice": {"action": "HOLD"}},
            ],
        }

        change = build_quant_analysis_change_summary(previous, current)

        self.assertTrue(change["has_changes"])
        self.assertIn("AAPL", change["changed_symbols"])
        self.assertIn("MSFT", change["changed_symbols"])
        self.assertIn("AAPL", change["message"])
        self.assertIn("MSFT", change["message"])
        self.assertIn("Top buys", change["message"])


if __name__ == "__main__":
    unittest.main()
