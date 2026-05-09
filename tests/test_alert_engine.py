import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tests.support import clear_modules, reload_module


class AlertEngineTests(unittest.TestCase):
    def setUp(self):
        clear_modules("alert_engine")
        self.module = reload_module("alert_engine")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_path = str(Path(self.temp_dir.name) / "alert_state.json")

    def _strong_record(self, symbol="NVDA", signal="STRONG_BUY", retrieved_at="2026-05-08T23:00:00"):
        bullish_ratio = 0.95 if signal == "STRONG_BUY" else 0.02
        bearish_ratio = 0.02 if signal == "STRONG_BUY" else 0.95
        return {
            "symbol": symbol,
            "retrieved_at": retrieved_at,
            "signal": signal,
            "bullish_ratio": bullish_ratio,
            "bearish_ratio": bearish_ratio,
            "bullish_count": 57 if signal == "STRONG_BUY" else 1,
            "bearish_count": 1 if signal == "STRONG_BUY" else 57,
            "total": 60,
            "reason": "分析师共识触发。",
        }

    def test_build_analyst_signal_alerts_only_emits_fresh_strong_signals(self):
        now = datetime(2026, 5, 9, 9, 0, 0)
        cache = {
            "recommendations": {
                "NVDA": self._strong_record("NVDA", "STRONG_BUY", (now - timedelta(hours=5)).isoformat()),
                "AAPL": {"symbol": "AAPL", "signal": "NEUTRAL", "retrieved_at": now.isoformat()},
                "OLD": self._strong_record("OLD", "STRONG_SELL", (now - timedelta(days=10)).isoformat()),
            }
        }

        alerts = self.module.build_analyst_signal_alerts(cache, symbols=["NVDA", "AAPL", "OLD"], now=now)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].symbol, "NVDA")
        self.assertEqual(alerts[0].alert_type, "ANALYST_STRONG_BUY")
        self.assertIn("95.0%", alerts[0].body)

    def test_build_analyst_signal_alerts_preserves_proxy_source_and_sample_display(self):
        now = datetime(2026, 5, 9, 9, 0, 0)
        proxy_record = self._strong_record("XLK", "STRONG_BUY", now.isoformat())
        proxy_record["source"] = "etf_proxy_holdings"
        proxy_record["sample_display"] = "3/10 成分股"

        alerts = self.module.build_analyst_signal_alerts(
            {"recommendations": {"XLK": proxy_record}},
            symbols=["XLK"],
            now=now,
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].source, "etf_proxy_holdings")
        self.assertIn("3/10 成分股", alerts[0].body)

    def test_build_risk_alert_emits_risk_off_only(self):
        from risk_gate import MarketRiskGateDecision

        decision = MarketRiskGateDecision(
            regime="RISK_OFF",
            risk_score=6,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=["VIX 35.0 偏高。"],
        )

        alerts = self.module.build_risk_alerts(decision, now=datetime(2026, 5, 9, 9, 0, 0))

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, "MARKET_RISK_OFF")
        self.assertEqual(alerts[0].severity, "critical")
        self.assertIn("RISK_OFF", alerts[0].body)

    def test_filter_new_alerts_dedupes_until_state_changes(self):
        now = datetime(2026, 5, 9, 9, 0, 0)
        alert = self.module.build_analyst_signal_alerts(
            {"recommendations": {"NVDA": self._strong_record("NVDA", "STRONG_BUY", now.isoformat())}},
            now=now,
        )[0]
        state = self.module.load_alert_state(self.state_path)

        first = self.module.filter_new_alerts([alert], state, now=now)
        self.module.record_sent_alerts(first, state, now=now)
        second = self.module.filter_new_alerts([alert], state, now=now + timedelta(days=2))

        changed = self.module.build_analyst_signal_alerts(
            {"recommendations": {"NVDA": self._strong_record("NVDA", "STRONG_SELL", now.isoformat())}},
            now=now,
        )[0]
        third = self.module.filter_new_alerts([changed], state, now=now + timedelta(days=2))

        self.assertEqual(first, [alert])
        self.assertEqual(second, [])
        self.assertEqual(third, [changed])

    def test_risk_alert_repeats_after_cooldown(self):
        from risk_gate import MarketRiskGateDecision

        now = datetime(2026, 5, 9, 9, 0, 0)
        decision = MarketRiskGateDecision(
            regime="RISK_OFF",
            risk_score=6,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=["risk"],
        )
        alert = self.module.build_risk_alerts(decision, now=now)[0]
        state = self.module.load_alert_state(self.state_path)

        first = self.module.filter_new_alerts([alert], state, now=now)
        self.module.record_sent_alerts(first, state, now=now)
        blocked = self.module.filter_new_alerts([alert], state, now=now + timedelta(hours=2))
        repeated = self.module.filter_new_alerts([alert], state, now=now + timedelta(hours=7))

        self.assertEqual(first, [alert])
        self.assertEqual(blocked, [])
        self.assertEqual(repeated, [alert])

    def test_send_new_alerts_dispatches_enabled_channels_and_records_state(self):
        now = datetime(2026, 5, 9, 9, 0, 0)
        alert = self.module.build_analyst_signal_alerts(
            {"recommendations": {"NVDA": self._strong_record("NVDA", "STRONG_BUY", now.isoformat())}},
            now=now,
        )[0]
        sent = {"slack": [], "email": []}

        def fake_slack(text, webhook_url):
            sent["slack"].append((text, webhook_url))
            return True, "slack ok"

        def fake_email(subject, body, email_config):
            sent["email"].append((subject, body, email_config))
            return True, "email ok"

        results = self.module.send_new_alerts(
            [alert],
            config={
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "email": {
                    "enabled": True,
                    "smtp_host": "smtp-mail.outlook.com",
                    "smtp_port": 587,
                    "from_email": "sender@outlook.com",
                    "to_emails": ["target@gmail.com"],
                },
            },
            state_path=self.state_path,
            now=now,
            slack_sender=fake_slack,
            email_sender=fake_email,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(len(sent["slack"]), 1)
        self.assertEqual(len(sent["email"]), 1)
        state = self.module.load_alert_state(self.state_path)
        self.assertIn("analyst:NVDA", state["sent_alerts"])


if __name__ == "__main__":
    unittest.main()
