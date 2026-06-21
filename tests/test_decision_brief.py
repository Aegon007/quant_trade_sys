import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class DecisionBriefTests(unittest.TestCase):
    def setUp(self):
        from quant_core.llm import decision_brief

        self.module = decision_brief

    def test_build_decision_context_collects_actions_risk_and_changes(self):
        context = self.module.build_decision_context(
            account={"total_capital": 10000, "cash_available": 2500, "exposure_pct": 75},
            multi_horizon_snapshot={
                "status": "READY",
                "symbols": [
                    {
                        "symbol": "MSFT",
                        "long_horizon": {"state": "ATTRACTIVE"},
                        "timing": {"state": "CONFIRMED"},
                        "decision": {"action": "ACCUMULATE", "target_weight_range_pct": [4, 7]},
                    },
                    {
                        "symbol": "QQQM",
                        "long_horizon": {"state": "ATTRACTIVE"},
                        "timing": {"state": "DETERIORATING"},
                        "decision": {"action": "HOLD"},
                    },
                ],
            },
            discipline_snapshot={"regime": "LIGHT", "risk_regime": "CAUTION"},
            trade_plan={"decision": "ACTION", "items": [{"symbol": "MSFT", "plan_action": "ACCUMULATE"}]},
            change_feed={"high_items": [{"title": "风险状态变化", "message": "NORMAL to CAUTION"}]},
        )

        self.assertEqual(context["approved_actions"][0]["symbol"], "MSFT")
        self.assertEqual(context["signal_conflicts"][0]["symbol"], "QQQM")
        self.assertEqual(context["discipline"]["regime"], "LIGHT")
        self.assertEqual(len(context["high_priority_changes"]), 1)
        self.assertEqual(context["canonical_decision"]["mode"], "ACTION")

    def test_refresh_decision_brief_calls_llm_only_when_signature_changes(self):
        calls = []

        def runner(**kwargs):
            calls.append(kwargs["decision_context"])
            return True, "当前轻仓，优先复核 MSFT 加仓条件。", {
                "route_name": "llm",
                "model": "test-model",
                "cached": False,
                "fallback_attempts": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "decision_brief.json")
            kwargs = dict(
                context={
                    "account": {"exposure_pct": 70},
                    "discipline": {"regime": "LIGHT"},
                    "approved_actions": [{"symbol": "MSFT", "action": "ACCUMULATE"}],
                    "high_priority_changes": [],
                },
                notification_config={"llm": {"enabled": True}},
                llm_runner=runner,
                path=path,
                now=datetime(2026, 6, 20, 1, 0, 0),
            )
            first = self.module.refresh_decision_brief(trigger="NIGHTLY", **kwargs)
            second = self.module.refresh_decision_brief(trigger="MATERIAL_CHANGE", **kwargs)
            changed = self.module.refresh_decision_brief(
                trigger="MATERIAL_CHANGE",
                **{**kwargs, "context": {**kwargs["context"], "discipline": {"regime": "STOP"}}},
            )

        self.assertTrue(first["refreshed"])
        self.assertFalse(second["refreshed"])
        self.assertTrue(changed["refreshed"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(changed["status"], "READY")

    def test_refresh_decision_brief_has_structured_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = self.module.refresh_decision_brief(
                context={
                    "discipline": {"regime": "NORMAL", "risk_regime": "NORMAL"},
                    "approved_actions": [],
                    "signal_conflicts": [],
                    "high_priority_changes": [],
                },
                notification_config={},
                trigger="NIGHTLY",
                llm_runner=lambda **kwargs: (False, "not configured", {}),
                path=str(Path(temp_dir) / "decision_brief.json"),
            )

        self.assertEqual(snapshot["status"], "STRUCTURED_ONLY")
        self.assertIn("无强交易信号", snapshot["executive_summary"])


if __name__ == "__main__":
    unittest.main()
