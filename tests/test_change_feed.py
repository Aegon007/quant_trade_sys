import unittest


class ChangeFeedTests(unittest.TestCase):
    def setUp(self):
        from quant_core.notifications import change_feed

        self.module = change_feed

    def test_build_change_feed_prioritizes_regime_and_top3_changes(self):
        feed = self.module.build_change_feed(
            previous_state={
                "discipline_snapshot": {"regime": "NORMAL", "risk_regime": "NORMAL"},
                "core_etf_snapshot": {"symbols": [{"symbol": "VOO", "action": "HOLD", "target_weight_pct": 50.0}]},
                "satellite_candidate_snapshot": {"summary": {"top_symbols": ["ANET"]}, "symbols": [{"symbol": "ANET", "recommendation_status": "PROBE"}]},
                "trade_plan": {"decision": "NO_ACTION", "action_count": 0},
                "monthly_discipline_review": {"status": "ALIGNED", "follow_days": 5, "ignore_days": 1, "defensive_override_days": 0},
            },
            current_state={
                "discipline_snapshot": {"regime": "LIGHT", "risk_regime": "CAUTION"},
                "core_etf_snapshot": {"symbols": [{"symbol": "VOO", "action": "ACCUMULATE", "target_weight_pct": 55.0}]},
                "satellite_candidate_snapshot": {
                    "summary": {"top_symbols": ["MU"]},
                    "symbols": [{"symbol": "MU", "recommendation_status": "CONFIRMED"}],
                },
                "trade_plan": {"decision": "ACTION", "action_count": 2},
                "monthly_discipline_review": {"status": "CAUTION", "follow_days": 3, "ignore_days": 4, "defensive_override_days": 2},
            },
        )

        self.assertGreaterEqual(feed["summary"]["high_count"], 4)
        titles = [row["title"] for row in feed["high_items"]]
        self.assertIn("纪律层状态切换", titles)
        self.assertTrue(any("Top 推荐" in title for title in titles))
        self.assertIn("月度纪律状态变化", titles)
        self.assertIn("月度 IGNORE 天数上升", titles)
        discipline_month_item = next(row for row in feed["high_items"] if row["title"] == "月度纪律状态变化")
        self.assertIn("reason_codes", discipline_month_item)
        self.assertIn("explanation_summary", discipline_month_item)
        self.assertIn("details", discipline_month_item)
        self.assertTrue(discipline_month_item["reason_codes"])
        self.assertTrue(discipline_month_item["explanation_summary"])

    def test_build_intraday_discipline_month_alert_extracts_high_priority_summary(self):
        alert = self.module.build_intraday_discipline_month_alert(
            {
                "generated_at": "2026-05-14T06:00:00",
                "high_items": [
                    {
                        "category": "discipline_month",
                        "title": "月度纪律状态变化",
                        "message": "月度纪律状态从 MONITOR 变为 CAUTION。",
                    },
                    {
                        "category": "discipline_month",
                        "title": "月度 IGNORE 天数上升",
                        "message": "月度 IGNORE 天数从 1 上升到 4，FOLLOW 为 3。",
                    },
                ],
            },
            monthly_discipline_review={"summary": "本月纪律偏离天数偏多，系统建议优先减少计划外交易。"},
        )

        self.assertIsNotNone(alert)
        self.assertIn("月度纪律状态变化", alert["message"])
        self.assertIn("Discipline month:", alert["message"])
        self.assertTrue(alert["signature"].startswith("2026-05-14T06:00:00"))

    def test_build_change_feed_surfaces_step3_health_and_governance(self):
        feed = self.module.build_change_feed(
            previous_state={
                "data_health_snapshot": {"status": "OK", "summary": {"status": "OK"}},
                "plan_quality_snapshot": {"status": "OK", "summary": {"status": "OK"}},
                "strategy_governance_snapshot": {"status": "OK", "summary": {"status": "OK"}},
            },
            current_state={
                "data_health_snapshot": {
                    "status": "BROKEN",
                    "summary": {
                        "status": "BROKEN",
                        "tracked_symbol_count": 3,
                        "missing_price_count": 2,
                        "invalid_price_count": 1,
                        "stale_price_count": 0,
                        "fallback_symbol_count": 0,
                    },
                },
                "plan_quality_snapshot": {
                    "status": "DEGRADED",
                    "summary": {
                        "status": "DEGRADED",
                        "missed_reachable_count": 2,
                        "unplanned_trade_count": 0,
                        "execution_rate": 0.5,
                    },
                },
                "strategy_governance_snapshot": {
                    "status": "REVIEW",
                    "summary": {
                        "status": "REVIEW",
                        "review_count": 1,
                        "promotion_watch_count": 1,
                    },
                },
            },
        )

        titles = [row["title"] for row in feed["high_items"]]
        self.assertIn("数据健康异常", titles)
        self.assertIn("计划执行质量下降", titles)
        self.assertIn("策略治理需要复核", titles)
        categories = {row["category"] for row in feed["items"]}
        self.assertTrue({"data_health", "plan_quality", "strategy_governance"}.issubset(categories))


if __name__ == "__main__":
    unittest.main()
