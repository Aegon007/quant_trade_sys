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
