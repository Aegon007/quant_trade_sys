import unittest
from types import SimpleNamespace


class IntradayMonitorTests(unittest.TestCase):
    def setUp(self):
        from quant_core.monitoring import intraday_monitor

        self.module = intraday_monitor

    def test_classify_intraday_events_flags_risk_break_and_buy_zone_trigger(self):
        data = {
            "holdings": [
                {"symbol": "AAPL", "shares": 1.0, "cost": 100.0, "current_price": 94.0},
            ],
            "watchlist": [
                {"symbol": "MSFT", "last_price": 99.0},
            ],
        }
        trade_plan = {
            "items": [
                {
                    "symbol": "AAPL",
                    "plan_action": "EXIT",
                    "reference_price": 100.0,
                    "risk_break_level": 95.0,
                },
                {
                    "symbol": "MSFT",
                    "plan_action": "PROBE",
                    "reference_price": 99.0,
                    "buy_zone_low": 98.0,
                    "buy_zone_high": 100.0,
                    "max_chase_price": 101.0,
                },
            ]
        }
        discipline_snapshot = {
            "regime": "NORMAL",
            "can_open_new_core_positions": True,
            "can_open_new_satellite_positions": True,
        }

        events = self.module.classify_intraday_events(
            data=data,
            trade_plan=trade_plan,
            discipline_snapshot=discipline_snapshot,
        )

        event_types = {row["event_type"] for row in events}
        self.assertIn("PLAN_RISK_BREAK", event_types)
        self.assertIn("PLAN_BUY_ZONE_TRIGGER", event_types)
        sell_event = next(row for row in events if row["event_type"] == "PLAN_RISK_BREAK")
        self.assertTrue(sell_event["should_notify"])
        self.assertEqual(sell_event["symbol"], "AAPL")
        buy_event = next(row for row in events if row["event_type"] == "PLAN_BUY_ZONE_TRIGGER")
        self.assertEqual(buy_event["symbol"], "MSFT")
        self.assertEqual(buy_event["plan_action"], "PROBE")

    def test_classify_intraday_events_flags_market_risk_off(self):
        data = {
            "holdings": [
                {"symbol": "QQQ", "shares": 2.0, "cost": 450.0, "current_price": 438.0},
            ],
            "watchlist": [],
        }

        events = self.module.classify_intraday_events(
            data=data,
            trade_plan={"items": []},
            risk_gate=SimpleNamespace(regime="CAUTION"),
            event_decision=SimpleNamespace(regime="RISK_OFF"),
            active_events=[{"title": "FOMC shock"}],
        )

        event_types = {row["event_type"] for row in events}
        self.assertIn("MARKET_RISK_OFF", event_types)
        risk_event = next(row for row in events if row["event_type"] == "MARKET_RISK_OFF")
        self.assertTrue(risk_event["should_notify"])
        self.assertEqual(risk_event["priority"], "high")

    def test_build_intraday_alert_collapses_top_priority_events(self):
        alert = self.module.build_intraday_alert(
            [
                {
                    "event_type": "PLAN_RISK_BREAK",
                    "priority": "high",
                    "symbol": "AAPL",
                    "title": "AAPL 跌破风险破坏位",
                    "message": "AAPL 已跌破风控位。",
                    "trigger_reason": "risk_break",
                    "should_notify": True,
                },
                {
                    "event_type": "PLAN_BUY_ZONE_TRIGGER",
                    "priority": "high",
                    "symbol": "MSFT",
                    "title": "MSFT 进入买入区间",
                    "message": "MSFT 已进入计划买入区间。",
                    "trigger_reason": "buy_zone",
                    "should_notify": True,
                },
            ]
        )

        self.assertIsNotNone(alert)
        self.assertIn("AAPL", alert["message"])
        self.assertIn("MSFT", alert["message"])
        self.assertTrue(alert["signature"])


if __name__ == "__main__":
    unittest.main()
