import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tests.support import clear_modules, reload_module


class AnalystConsensusTests(unittest.TestCase):
    def setUp(self):
        clear_modules("analyst_consensus")
        self.module = reload_module("analyst_consensus")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path = str(Path(self.temp_dir.name) / "analyst_consensus_cache.json")

    def test_evaluate_strong_buy_when_bullish_ratio_exceeds_threshold(self):
        record = self.module.build_consensus_record(
            "AAPL",
            {
                "period": "0m",
                "strongBuy": 10,
                "buy": 9,
                "hold": 1,
                "sell": 0,
                "strongSell": 0,
            },
            retrieved_at="2026-05-08T23:30:00",
        )

        self.assertEqual(record["signal"], "STRONG_BUY")
        self.assertEqual(record["bullish_count"], 19)
        self.assertAlmostEqual(record["bullish_ratio"], 0.95)

    def test_evaluate_strong_sell_when_bearish_ratio_exceeds_threshold(self):
        record = self.module.build_consensus_record(
            "TSLA",
            {
                "period": "0m",
                "strongBuy": 0,
                "buy": 0,
                "hold": 1,
                "sell": 6,
                "strongSell": 4,
            },
            retrieved_at="2026-05-08T23:30:00",
        )

        self.assertEqual(record["signal"], "STRONG_SELL")
        self.assertEqual(record["bearish_count"], 10)
        self.assertAlmostEqual(record["bearish_ratio"], 10 / 11)

    def test_small_sample_does_not_create_strong_signal(self):
        record = self.module.build_consensus_record(
            "NVDA",
            {
                "period": "0m",
                "strongBuy": 1,
                "buy": 0,
                "hold": 0,
                "sell": 0,
                "strongSell": 0,
            },
            retrieved_at="2026-05-08T23:30:00",
        )

        self.assertEqual(record["signal"], "NEUTRAL")
        self.assertIn("样本不足", record["reason"])

    def test_apply_analyst_consensus_overrides_only_fresh_strong_signals(self):
        now = datetime(2026, 5, 9, 10, 0, 0)
        fresh_record = self.module.build_consensus_record(
            "MSFT",
            {"period": "0m", "strongBuy": 9, "buy": 1, "hold": 0, "sell": 0, "strongSell": 0},
            retrieved_at=(now - timedelta(hours=8)).isoformat(),
        )
        stale_record = dict(fresh_record)
        stale_record["retrieved_at"] = (now - timedelta(days=10)).isoformat()

        signal, reason = self.module.apply_analyst_consensus_to_signal(
            "HOLD",
            "策略信号观望",
            fresh_record,
            now=now,
        )
        self.assertEqual(signal, "STRONG_BUY")
        self.assertIn("分析师共识", reason)

        signal, reason = self.module.apply_analyst_consensus_to_signal(
            "HOLD",
            "策略信号观望",
            stale_record,
            now=now,
        )
        self.assertEqual(signal, "HOLD")
        self.assertEqual(reason, "策略信号观望")

    def test_refresh_analyst_consensus_cache_writes_records_and_cycle_key(self):
        now = datetime(2026, 5, 8, 23, 30, 0)

        def fake_fetcher(symbol):
            return {
                "period": "0m",
                "strongBuy": 8,
                "buy": 2,
                "hold": 0,
                "sell": 0,
                "strongSell": 0,
            }

        ok, message = self.module.refresh_analyst_consensus_cache(
            ["aapl", "AAPL", "msft"],
            cache_path=self.cache_path,
            now=now,
            fetcher=fake_fetcher,
        )
        cache = self.module.load_analyst_consensus_cache(self.cache_path)

        self.assertTrue(ok)
        self.assertIn("成功 2", message)
        self.assertEqual(cache["last_cycle_key"], "2026-05-08")
        self.assertEqual(set(cache["recommendations"].keys()), {"AAPL", "MSFT"})
        self.assertEqual(cache["recommendations"]["AAPL"]["signal"], "STRONG_BUY")

    def test_build_etf_proxy_consensus_record_uses_weighted_component_sentiment(self):
        record = self.module.build_etf_proxy_consensus_record(
            "XLK",
            [
                {"symbol": "MSFT", "holding_percent": 0.45},
                {"symbol": "NVDA", "holding_percent": 0.35},
                {"symbol": "AAPL", "holding_percent": 0.20},
            ],
            {
                "MSFT": self.module.build_consensus_record(
                    "MSFT",
                    {"period": "0m", "strongBuy": 10, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0},
                    retrieved_at="2026-05-08T23:30:00",
                ),
                "NVDA": self.module.build_consensus_record(
                    "NVDA",
                    {"period": "0m", "strongBuy": 7, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0},
                    retrieved_at="2026-05-08T23:30:00",
                ),
                "AAPL": self.module.build_consensus_record(
                    "AAPL",
                    {"period": "0m", "strongBuy": 5, "buy": 5, "hold": 0, "sell": 0, "strongSell": 0},
                    retrieved_at="2026-05-08T23:30:00",
                ),
            },
            retrieved_at="2026-05-08T23:30:00",
        )

        self.assertIsNotNone(record)
        self.assertEqual(record["symbol"], "XLK")
        self.assertEqual(record["source"], "etf_proxy_holdings")
        self.assertEqual(record["signal"], "STRONG_BUY")
        self.assertGreaterEqual(record["bullish_ratio"], 0.90)
        self.assertEqual(record["covered_holdings"], 3)
        self.assertIn("ETF 持仓代理共识", record["reason"])

    def test_build_etf_proxy_consensus_record_stays_neutral_when_coverage_is_too_low(self):
        record = self.module.build_etf_proxy_consensus_record(
            "VOO",
            [
                {"symbol": "MSFT", "holding_percent": 0.30},
                {"symbol": "NVDA", "holding_percent": 0.30},
                {"symbol": "AAPL", "holding_percent": 0.40},
            ],
            {
                "MSFT": self.module.build_consensus_record(
                    "MSFT",
                    {"period": "0m", "strongBuy": 9, "buy": 1, "hold": 0, "sell": 0, "strongSell": 0},
                    retrieved_at="2026-05-08T23:30:00",
                ),
            },
            retrieved_at="2026-05-08T23:30:00",
            min_coverage_ratio=0.60,
        )

        self.assertIsNotNone(record)
        self.assertEqual(record["signal"], "NEUTRAL")
        self.assertLess(record["coverage_ratio"], 0.60)
        self.assertIn("覆盖不足", record["reason"])

    def test_summarize_consensus_status_reports_bullish_bias_without_strong_signal(self):
        record = self.module.build_consensus_record(
            "AMD",
            {
                "period": "0m",
                "strongBuy": 4,
                "buy": 3,
                "hold": 2,
                "sell": 1,
                "strongSell": 0,
            },
            retrieved_at="2026-05-08T23:30:00",
        )

        summary = self.module.summarize_consensus_status(record, now=datetime(2026, 5, 9, 10, 0, 0))

        self.assertEqual(summary["status"], "偏多")
        self.assertEqual(summary["bullish_display"], "70.0%")
        self.assertEqual(summary["sample_display"], "10")

    def test_summarize_consensus_status_reports_neutral_for_mixed_signal(self):
        record = self.module.build_consensus_record(
            "TSM",
            {
                "period": "0m",
                "strongBuy": 2,
                "buy": 2,
                "hold": 3,
                "sell": 2,
                "strongSell": 1,
            },
            retrieved_at="2026-05-08T23:30:00",
        )

        summary = self.module.summarize_consensus_status(record, now=datetime(2026, 5, 9, 10, 0, 0))

        self.assertEqual(summary["status"], "中性")
        self.assertEqual(summary["bearish_display"], "30.0%")

    def test_summarize_consensus_status_marks_etf_proxy_coverage_gap(self):
        record = self.module.build_etf_proxy_consensus_record(
            "VOO",
            [
                {"symbol": "MSFT", "holding_percent": 0.30},
                {"symbol": "NVDA", "holding_percent": 0.30},
                {"symbol": "AAPL", "holding_percent": 0.40},
            ],
            {
                "MSFT": self.module.build_consensus_record(
                    "MSFT",
                    {"period": "0m", "strongBuy": 9, "buy": 1, "hold": 0, "sell": 0, "strongSell": 0},
                    retrieved_at="2026-05-08T23:30:00",
                ),
            },
            retrieved_at="2026-05-08T23:30:00",
            min_coverage_ratio=0.60,
        )

        summary = self.module.summarize_consensus_status(record, now=datetime(2026, 5, 9, 10, 0, 0))

        self.assertEqual(summary["status"], "ETF代理覆盖不足")
        self.assertEqual(summary["sample_display"], "1/3 成分股")

    def test_refresh_analyst_consensus_cache_uses_etf_proxy_fallback(self):
        now = datetime(2026, 5, 8, 23, 30, 0)

        def fake_fetcher(symbol):
            if symbol == "XLK":
                return None
            return {
                "period": "0m",
                "strongBuy": 8,
                "buy": 2,
                "hold": 0,
                "sell": 0,
                "strongSell": 0,
            }

        def fake_holdings_fetcher(symbol):
            if symbol == "XLK":
                return [
                    {"symbol": "MSFT", "holding_percent": 0.5},
                    {"symbol": "NVDA", "holding_percent": 0.3},
                    {"symbol": "AAPL", "holding_percent": 0.2},
                ]
            return []

        ok, message = self.module.refresh_analyst_consensus_cache(
            ["XLK"],
            cache_path=self.cache_path,
            now=now,
            fetcher=fake_fetcher,
            holdings_fetcher=fake_holdings_fetcher,
        )
        cache = self.module.load_analyst_consensus_cache(self.cache_path)
        record = cache["recommendations"]["XLK"]

        self.assertTrue(ok)
        self.assertIn("成功 1", message)
        self.assertEqual(record["source"], "etf_proxy_holdings")
        self.assertEqual(record["signal"], "STRONG_BUY")
        self.assertEqual(record["covered_holdings"], 3)

    def test_should_run_nightly_update_respects_window_and_cycle(self):
        now = datetime(2026, 5, 8, 23, 30, 0)
        self.assertTrue(self.module.should_run_nightly_consensus_update(now=now, cache_path=self.cache_path))

        self.module.save_analyst_consensus_cache(
            {
                "last_cycle_key": "2026-05-08",
                "recommendations": {},
                "errors": {},
            },
            self.cache_path,
        )

        self.assertFalse(self.module.should_run_nightly_consensus_update(now=now, cache_path=self.cache_path))
        self.assertFalse(
            self.module.should_run_nightly_consensus_update(
                now=datetime(2026, 5, 8, 12, 0, 0),
                cache_path=self.cache_path,
            )
        )


if __name__ == "__main__":
    unittest.main()
