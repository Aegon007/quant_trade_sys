import unittest
from datetime import datetime


class IntradayTacticalTests(unittest.TestCase):
    def setUp(self):
        from quant_core.monitoring import intraday_tactical

        self.module = intraday_tactical

    def test_build_intraday_tactical_snapshot_flags_panic_and_hedge(self):
        def fake_price_fetcher(symbols):
            lookup = {
                "QQQ": 470.0,
                "SPY": 560.0,
                "SQQQ": 40.0,
                "PSQ": 19.0,
                "SH": 15.0,
            }
            return {symbol: lookup[symbol] for symbol in symbols if symbol in lookup}

        def fake_history_loader(symbol, period="5d"):
            import pandas as pd

            closes = {
                "QQQ": [490.0],
                "SPY": [575.0],
                "SQQQ": [38.0],
                "PSQ": [18.6],
                "SH": [14.8],
            }
            return pd.DataFrame({"Close": closes.get(symbol, [100.0])})

        snapshot = self.module.build_intraday_tactical_snapshot(
            data={"holdings": [], "watchlist": []},
            config=self.module.default_intraday_tactical_config(),
            risk_gate=None,
            event_decision=None,
            active_events=[],
            now=datetime.fromisoformat("2026-06-05T13:00:00"),
            price_fetcher=fake_price_fetcher,
            history_loader=fake_history_loader,
        )

        self.assertEqual(snapshot["state"], "PANIC")
        self.assertEqual(snapshot["recommended_action"], "TACTICAL_HEDGE")
        self.assertEqual(snapshot["recommended_symbol"], "SQQQ")
        self.assertGreater(float(snapshot["suggested_weight_pct"]), 0.0)

        events = self.module.build_intraday_tactical_events(snapshot)
        self.assertEqual(events[0]["event_type"], "TACTICAL_HEDGE_TRIGGER")
        self.assertEqual(events[0]["symbol"], "SQQQ")

    def test_build_intraday_tactical_snapshot_flags_capitulation(self):
        def fake_price_fetcher(symbols):
            lookup = {
                "QQQ": 468.0,
                "SPY": 559.0,
                "SQQQ": 42.8,
                "PSQ": 19.4,
                "SH": 15.1,
            }
            return {symbol: lookup[symbol] for symbol in symbols if symbol in lookup}

        def fake_history_loader(symbol, period="5d"):
            import pandas as pd

            closes = {
                "QQQ": [490.0],
                "SPY": [575.0],
                "SQQQ": [39.0],
                "PSQ": [18.6],
                "SH": [14.8],
            }
            return pd.DataFrame({"Close": closes.get(symbol, [100.0])})

        snapshot = self.module.build_intraday_tactical_snapshot(
            data={"holdings": [], "watchlist": []},
            config=self.module.default_intraday_tactical_config(),
            risk_gate=None,
            event_decision=None,
            active_events=[],
            now=datetime.fromisoformat("2026-06-05T13:00:00"),
            price_fetcher=fake_price_fetcher,
            history_loader=fake_history_loader,
        )

        self.assertEqual(snapshot["state"], "CAPITULATION")
        self.assertEqual(snapshot["recommended_action"], "DO_NOT_CHASE")
        events = self.module.build_intraday_tactical_events(snapshot)
        self.assertEqual(events[0]["event_type"], "TACTICAL_DO_NOT_CHASE")


if __name__ == "__main__":
    unittest.main()
