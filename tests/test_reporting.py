import unittest
from datetime import datetime


class ReportingTests(unittest.TestCase):
    def test_is_us_market_session_detects_regular_hours(self):
        from quant_core.notifications.reporting import is_us_market_session

        self.assertTrue(is_us_market_session(datetime.fromisoformat("2026-05-11T10:30:00-04:00")))
        self.assertFalse(is_us_market_session(datetime.fromisoformat("2026-05-11T08:45:00-04:00")))
        self.assertFalse(is_us_market_session(datetime.fromisoformat("2026-05-09T11:00:00-04:00")))

    def test_build_market_refresh_report_includes_movers_and_regime(self):
        from quant_core.notifications.reporting import build_market_refresh_report

        text = build_market_refresh_report(
            before_data={
                "holdings": [{"symbol": "AAPL", "current_price": 100.0}],
                "watchlist": [{"symbol": "MSFT", "last_price": 200.0}],
            },
            after_data={
                "holdings": [{"symbol": "AAPL", "current_price": 105.0}],
                "watchlist": [{"symbol": "MSFT", "last_price": 190.0}],
            },
            account_snapshot={"total_capital": 10000.0, "cash_available": 3000.0, "exposure_pct": 70.0},
            risk_gate={"regime": "CAUTION", "block_new_buys": False, "reasons": ["VIX elevated"]},
            allocation_regime={"regime": "LIGHT", "reasons": ["drawdown elevated"]},
            data_sources={"prices": {"primary_source": "stooq", "last_source": "stooq", "fallback_symbols": 0}},
            now=datetime(2026, 5, 11, 10, 0, 0),
        )

        self.assertIn("Hourly Market Refresh", text)
        self.assertIn("CAUTION", text)
        self.assertIn("LIGHT", text)
        self.assertIn("AAPL", text)
        self.assertIn("MSFT", text)
        self.assertIn("stooq (primary)", text.lower())

    def test_build_signal_attribution_groups_effective_ineffective_and_pending(self):
        from quant_core.notifications.reporting import build_signal_attribution

        attribution = build_signal_attribution(
            [
                {"record_type": "TRADE", "event_type": "BUY", "side": "BUY", "date": "2026-05-11 09:35", "symbol": "AAPL", "shares": 1.0, "price": 100.0},
                {"record_type": "TRADE", "event_type": "SELL", "side": "SELL", "date": "2026-05-11 15:55", "symbol": "AAPL", "shares": 1.0, "price": 108.0, "pl": 8.0},
                {"record_type": "TRADE", "event_type": "SELL", "side": "SELL", "date": "2026-05-11 15:10", "symbol": "TSLA", "shares": 1.0, "price": 190.0, "pl": -12.0},
                {"record_type": "TRADE", "event_type": "BUY", "side": "BUY", "date": "2026-05-11 11:00", "symbol": "MSFT", "shares": 1.0, "price": 300.0},
            ],
            day="2026-05-11",
        )

        self.assertEqual(attribution["effective_count"], 1)
        self.assertEqual(attribution["ineffective_count"], 1)
        self.assertEqual(attribution["pending_count"], 1)
        self.assertEqual(attribution["effective_symbols"], ["AAPL"])
        self.assertEqual(attribution["ineffective_symbols"], ["TSLA"])
        self.assertEqual(attribution["pending_symbols"], ["MSFT"])

    def test_build_nightly_report_includes_daily_recap_scoreboard_and_attribution(self):
        from quant_core.notifications.reporting import build_nightly_report

        text = build_nightly_report(
            {
                "generated_at": "2026-05-11T23:15:00",
                "account": {
                    "total_capital": 12000.0,
                    "cash_available": 2500.0,
                    "exposure_pct": 79.2,
                },
                "risk": {
                    "regime": "NORMAL",
                    "risk_score": 2,
                    "reasons": ["trend healthy"],
                },
                "allocation_regime": {
                    "regime": "HEAVY",
                    "reasons": ["expectancy positive"],
                },
                "performance": {
                    "live_scoreboard": {
                        "completed_trades": 8,
                        "win_rate": 0.625,
                        "expectancy_return_pct": 0.034,
                        "profit_factor": 1.8,
                    },
                },
                "alerts": [{"title": "Risk alert"}],
                "daily_recap": {
                    "day": "2026-05-11",
                    "trade_count": 3,
                    "buy_count": 1,
                    "sell_count": 2,
                    "portfolio_event_count": 1,
                    "realized_pl": 55.5,
                    "symbols": ["AAPL", "MSFT"],
                },
                "signal_attribution": {
                    "effective_count": 1,
                    "ineffective_count": 1,
                    "pending_count": 1,
                    "effective_symbols": ["AAPL"],
                    "ineffective_symbols": ["TSLA"],
                    "pending_symbols": ["MSFT"],
                },
                "core_etf_snapshot": {
                    "summary": {
                        "accumulate_count": 1,
                        "trim_count": 0,
                        "focus_symbols": ["VOO"],
                    }
                },
                "satellite_candidate_snapshot": {
                    "summary": {
                        "scanned_symbols": 44,
                        "candidate_count": 20,
                        "deep_analysis_count": 10,
                        "top_symbols": ["MU", "ANET", "VRT"],
                        "confirmed_count": 2,
                        "probe_count": 1,
                        "watch_count": 7,
                        "overheated_count": 1,
                    }
                },
                "discipline_snapshot": {
                    "regime": "NORMAL",
                    "can_open_new_core_positions": True,
                    "can_open_new_satellite_positions": False,
                    "summary": "当前可正常执行计划，但不建议无计划追价。",
                },
                "monthly_discipline_review": {
                    "status": "ALIGNED",
                    "follow_days": 6,
                    "ignore_days": 1,
                    "follow_realized_pl": 220.0,
                    "ignore_realized_pl": -45.0,
                    "summary": "本月已有的计划执行整体保持纪律，没有检测到明显的偏离日。",
                },
                "strategy_validation_snapshot": {
                    "summary": {
                        "status": "CAUTION",
                        "symbol_count": 3,
                        "validated_count": 1,
                        "warning_symbols": ["QQQ"],
                        "message": "默认策略整体仍可用，但领先优势不够稳或样本偏少。",
                    }
                },
                "change_feed": {
                    "summary": {"high_count": 2, "medium_count": 1, "low_count": 0},
                },
                "nightly_manifest": {
                    "run_id": "20260511-nightly",
                    "status": "completed",
                    "steps": {
                        "quant_analysis_snapshot": {"status": "completed"},
                        "trade_plan": {"status": "completed"},
                    },
                },
            }
        )

        self.assertIn("Nightly Portfolio Report", text)
        self.assertIn("HEAVY", text)
        self.assertIn("55.50", text)
        self.assertIn("62.5%", text)
        self.assertIn("AAPL, MSFT", text)
        self.assertIn("Signal attribution", text)
        self.assertIn("effective=1", text.lower())
        self.assertIn("Core ETF engine", text)
        self.assertIn("Satellite radar", text)
        self.assertIn("MU, ANET, VRT", text)
        self.assertIn("Change feed", text)
        self.assertIn("Nightly manifest", text)
        self.assertIn("Discipline:", text)
        self.assertIn("Discipline month:", text)
        self.assertIn("follow=6", text.lower())
        self.assertIn("ignore=1", text.lower())
        self.assertIn("Strategy validation:", text)
        self.assertIn("status=CAUTION", text)

    def test_build_quant_analysis_report_includes_summary_and_symbols(self):
        from quant_core.notifications.reporting import build_quant_analysis_report

        text = build_quant_analysis_report(
            {
                "generated_at": "2026-05-11T23:15:00",
                "strategy": {"id": "deep_tcn", "name": "TCN"},
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
                        "signal_reason": "trend healthy",
                        "latest_price": 109.0,
                        "backtest": {"total_return": 0.15, "sharpe_ratio": 1.2, "win_rate": 0.6},
                        "monte_carlo": {"expected_return": 0.03, "positive_probability": 0.62},
                        "position_advice": {"action": "ADD", "target_weight_pct": 15.0},
                    },
                    {
                        "symbol": "MSFT",
                        "list_type": "watchlist",
                        "signal": "HOLD",
                        "signal_reason": "waiting",
                        "latest_price": 206.0,
                        "backtest": {"total_return": -0.02, "sharpe_ratio": -0.1, "win_rate": 0.0},
                        "monte_carlo": {"expected_return": 0.01, "positive_probability": 0.52},
                        "position_advice": None,
                    },
                ],
            }
        )

        self.assertIn("Quant Analysis Report", text)
        self.assertIn("AAPL", text)
        self.assertIn("MSFT", text)
        self.assertIn("BUY=1", text)


if __name__ == "__main__":
    unittest.main()
