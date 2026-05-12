import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace

from tests.support import clear_modules, install_fake_yfinance, reload_module


class UIComponentsTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        sys.modules["streamlit"] = types.ModuleType("streamlit")
        clear_modules(
            "app.ui.components",
            "strategies.ui",
            "deep_learning_strategy",
            "quant_core.portfolio.allocation",
        )
        self.ui = reload_module("app.ui.components")

    def test_build_watchlist_records_includes_allocation_guidance_for_deep_tcn_buy(self):
        self.ui.su.get_signal = lambda strategy, symbol: ("BUY", f"{symbol} buy")
        self.ui.dl_utils.get_deep_tcn_signal_profile = lambda symbol, **kwargs: SimpleNamespace(
            signal="BUY",
            reason=f"{symbol} profile",
            probability=0.60,
            expected_return_pct=0.03,
            confidence=0.60,
            take_profit_price=103.0,
        )

        records = self.ui.build_watchlist_records(
            watchlist=[{"symbol": "MSFT", "notes": "watch", "last_price": 100.0}],
            strategy={"id": "deep_tcn", "params": {"period": "2y"}},
            account={
                "total_capital": 10000.0,
                "cash_available": 5000.0,
                "min_cash_buffer_pct": 0.10,
                "max_single_position_pct": 0.20,
                "max_total_exposure_pct": 1.0,
            },
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["建议动作"], "买入")
        self.assertEqual(records[0]["建议投入"], "$800.00")
        self.assertEqual(records[0]["建议股数"], "8.000")
        self.assertEqual(records[0]["上涨预期价"], "$101.00 ~ $105.68")
        self.assertIn("上涨概率", records[0]["资金说明"])

    def test_build_holding_records_prefers_quant_analysis_snapshot_fields_when_available(self):
        records = self.ui.build_holding_records(
            holdings=[{"symbol": "AAPL", "shares": 10.0, "cost": 90.0, "current_price": 100.0, "sector": "Tech"}],
            strategy={"id": "deep_tcn", "params": {"period": "2y"}},
            portfolio_value=1000.0,
            analysis_now=datetime.fromisoformat("2026-05-12T08:00:00"),
            analysis_snapshot={
                "generated_at": "2026-05-11T23:15:00",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "signal": "BUY",
                        "signal_reason": "snapshot reason",
                        "backtest": {"total_return": 0.15, "win_rate": 0.60},
                        "monte_carlo": {"expected_return": 0.03},
                        "guidance": {"suggested_exit_price": 112.0},
                        "position_advice": {"action": "TRIM", "target_weight_pct": 12.5, "reason": "snapshot advice"},
                    }
                ]
            },
        )

        self.assertEqual(records[0]["信号"], "BUY")
        self.assertEqual(records[0]["信号说明"], "snapshot reason")
        self.assertEqual(records[0]["仓位建议"], "TRIM")
        self.assertAlmostEqual(records[0]["回测收益"], 0.15)
        self.assertAlmostEqual(records[0]["回测胜率"], 0.60)
        self.assertAlmostEqual(records[0]["MC预期"], 0.03)
        self.assertAlmostEqual(records[0]["退出参考"], 112.0)
        self.assertEqual(records[0]["最近全量分析时间"], "2026-05-11 23:15")
        self.assertEqual(records[0]["分析新鲜度"], "新鲜")

    def test_build_watchlist_records_uses_quant_snapshot_and_sorts_by_priority(self):
        self.ui.su.get_signal = lambda strategy, symbol: ("HOLD", f"{symbol} hold")

        records = self.ui.build_watchlist_records(
            watchlist=[
                {"symbol": "MSFT", "notes": "watch", "last_price": 100.0},
                {"symbol": "TSLA", "notes": "watch", "last_price": 200.0},
            ],
            strategy={"id": "ma_crossover", "params": {"period": "2y"}},
            analysis_now=datetime.fromisoformat("2026-05-14T08:00:00"),
            analysis_snapshot={
                "generated_at": "2026-05-11T23:15:00",
                "symbols": [
                    {
                        "symbol": "MSFT",
                        "signal": "HOLD",
                        "signal_reason": "wait",
                        "backtest": {"total_return": 0.01},
                        "monte_carlo": {"expected_return": 0.01},
                    },
                    {
                        "symbol": "TSLA",
                        "signal": "BUY",
                        "signal_reason": "breakout",
                        "backtest": {"total_return": 0.12},
                        "monte_carlo": {"expected_return": 0.05},
                    },
                ]
            },
        )

        self.assertEqual(records[0]["代码"], "TSLA")
        self.assertEqual(records[0]["信号"], "BUY")
        self.assertAlmostEqual(records[0]["回测收益"], 0.12)
        self.assertAlmostEqual(records[0]["MC预期"], 0.05)
        self.assertEqual(records[0]["最近全量分析时间"], "2026-05-11 23:15")
        self.assertEqual(records[0]["分析新鲜度"], "过期")

    def test_build_holding_records_marks_analysis_stale_after_24_hours(self):
        records = self.ui.build_holding_records(
            holdings=[{"symbol": "AAPL", "shares": 1.0, "cost": 90.0, "current_price": 100.0, "sector": "Tech"}],
            strategy={"id": "deep_tcn", "params": {"period": "2y"}},
            portfolio_value=100.0,
            analysis_now=datetime.fromisoformat("2026-05-12T23:30:00"),
            analysis_snapshot={
                "generated_at": "2026-05-11T23:15:00",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "signal": "HOLD",
                        "signal_reason": "snapshot reason",
                    }
                ]
            },
        )

        self.assertEqual(records[0]["分析新鲜度"], "偏旧")

    def test_build_holdings_analysis_freshness_alert_reports_expired_and_missing_symbols(self):
        alert = self.ui.build_holdings_analysis_freshness_alert(
            holdings=[
                {"symbol": "AAPL", "shares": 1.0, "cost": 90.0, "current_price": 100.0, "sector": "Tech"},
                {"symbol": "MSFT", "shares": 1.0, "cost": 200.0, "current_price": 210.0, "sector": "Tech"},
            ],
            analysis_snapshot={
                "generated_at": "2026-05-11T23:15:00",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "signal": "BUY",
                        "signal_reason": "snapshot reason",
                    }
                ],
            },
            now=datetime.fromisoformat("2026-05-14T08:00:00"),
        )

        self.assertEqual(alert["expired_symbols"], ["AAPL"])
        self.assertEqual(alert["missing_symbols"], ["MSFT"])
        self.assertTrue(alert["needs_warning"])


if __name__ == "__main__":
    unittest.main()
