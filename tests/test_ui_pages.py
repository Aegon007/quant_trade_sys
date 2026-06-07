import unittest
from types import SimpleNamespace


class UIPagesHelpersTests(unittest.TestCase):
    def setUp(self):
        from app.ui import pages

        self.pages = pages

    def test_build_holdings_markdown_contains_rows_and_summary(self):
        records = [
            {
                "代码": "AAPL",
                "股数": 1.5,
                "成本价": 100.0,
                "现价": 110.0,
                "市值": 165.0,
                "盈亏 ($)": 15.0,
                "盈亏 (%)": 10.0,
                "信号": "BUY",
                "分析师意见": "看多",
            },
            {
                "代码": "MSFT",
                "股数": 2.0,
                "成本价": 200.0,
                "现价": None,
                "市值": None,
                "盈亏 ($)": None,
                "盈亏 (%)": None,
                "信号": "HOLD",
                "分析师意见": "无数据",
            },
        ]
        summary = SimpleNamespace(total_cost=550.0, total_value=565.0, total_pl=15.0, total_pl_pct=2.73)

        md_text = self.pages.build_holdings_markdown(
            records,
            summary,
            format_share_quantity_fn=lambda x: f"{float(x):.3f}",
            labels={
                "total_cost": "总成本",
                "total_value": "总市值",
                "total_pl": "总盈亏",
            },
        )

        self.assertIn("| AAPL | 1.500 | $100.00 | $110.00 | $165.00 | $+15.00 | +10.00% | BUY | 看多 |", md_text)
        self.assertIn("| MSFT | 2.000 | $200.00 | — | — | — | — | HOLD | 无数据 |", md_text)
        self.assertIn("**总成本**: $550.00", md_text)
        self.assertIn("**总市值**: $565.00", md_text)
        self.assertIn("**总盈亏**: $+15.00 (+2.73%)", md_text)

    def test_build_transaction_display_dataframe_formats_columns(self):
        rows = [
            {
                "date": "2026-05-10 10:00",
                "event_type": "SELL",
                "symbol": "AAPL",
                "side": "SELL",
                "shares": 1.234,
                "price": 100.0,
                "cost_basis": 90.0,
                "proceeds": 123.4,
                "pl": 12.3,
                "pl_pct": 11.2,
                "notes": "ok",
            },
            {
                "date": "2026-05-10 11:00",
                "event_type": "MOVE_TO_HOLDING",
                "symbol": "MSFT",
                "side": "BUY",
                "shares": 1.0,
                "price": None,
                "cost_basis": None,
                "proceeds": None,
                "pl": None,
                "pl_pct": None,
                "notes": "move",
            },
        ]

        df = self.pages.build_transaction_display_dataframe(
            rows,
            format_share_quantity_fn=lambda x: f"{float(x):.3f}",
        )

        self.assertEqual(
            list(df.columns),
            ["日期", "类型", "代码", "方向", "股数", "价格", "成本价", "收入", "盈亏 ($)", "盈亏 (%)", "备注"],
        )
        self.assertEqual(df.iloc[0]["股数"], "1.234")
        self.assertEqual(df.iloc[0]["价格"], "$100.00")
        self.assertEqual(df.iloc[0]["盈亏 (%)"], "+11.20%")
        self.assertEqual(df.iloc[1]["价格"], "—")
        self.assertEqual(df.iloc[1]["收入"], "—")

    def test_summarize_trade_records_counts_trade_only(self):
        rows = [
            {"record_type": "TRADE", "proceeds": 100.0, "pl": 10.0},
            {"record_type": "PORTFOLIO_EVENT", "proceeds": 999.0, "pl": 999.0},
            {"record_type": "TRADE", "proceeds": 200.0, "pl": -20.0},
        ]

        proceeds, total_pl = self.pages.summarize_trade_records(rows)

        self.assertAlmostEqual(proceeds, 300.0)
        self.assertAlmostEqual(total_pl, -10.0)

    def test_build_snapshot_alerts_from_event_objects(self):
        events = [
            SimpleNamespace(
                title="FOMC meeting",
                symbols=["SPY"],
                severity="high",
                sentiment="negative",
                source="mock",
                verified=True,
            )
        ]

        alerts = self.pages.build_snapshot_alerts(events)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["title"], "FOMC meeting")
        self.assertEqual(alerts[0]["symbols"], ["SPY"])
        self.assertTrue(alerts[0]["verified"])

    def test_format_robinhood_import_result_message_includes_dedupe_counts(self):
        message = self.pages.format_robinhood_import_result_message(
            {
                "imported_count": 3,
                "duplicate_count": 2,
                "skipped_count": 4,
            }
        )

        self.assertIn("新增 3", message)
        self.assertIn("重复跳过 2", message)
        self.assertIn("不支持/缺失字段跳过 4", message)

    def test_format_robinhood_reconcile_result_message_includes_cash_and_issues(self):
        message = self.pages.format_robinhood_reconcile_result_message(
            {
                "holdings": [{"symbol": "AAPL"}],
                "cash_available": 860.0,
                "cash_mode": "imported_cash_events",
                "issues": ["history may be incomplete"],
            }
        )

        self.assertIn("持仓 1 个", message)
        self.assertIn("$860.00", message)
        self.assertIn("imported_cash_events", message)
        self.assertIn("history may be incomplete", message)

    def test_build_core_etf_display_dataframe_and_discipline_constraints(self):
        core_df = self.pages.build_core_etf_display_dataframe(
            {
                "symbols": [
                    {
                        "symbol": "VOO",
                        "role": "broad_market",
                        "action": "ACCUMULATE",
                        "current_weight_pct": 20.0,
                        "target_weight_pct": 25.0,
                        "target_weight_range_low_pct": 20.0,
                        "target_weight_range_high_pct": 40.0,
                        "rotation_score": 78.0,
                        "expected_return_3m": 0.04,
                        "expected_return_12m": 0.10,
                        "regime_alignment": "POSITIVE",
                        "recommended_buy_zone_low": 495.0,
                        "recommended_buy_zone_high": 505.0,
                        "rotation_backtest": {"excess_return": 0.03},
                        "signal_reason": "trend confirmed",
                    }
                ]
            }
        )
        discipline_df = self.pages.build_discipline_constraints_dataframe(
            {
                "regime": "LIGHT",
                "risk_regime": "CAUTION",
                "allocation_regime": "LIGHT",
                "can_open_new_core_positions": True,
                "can_open_new_satellite_positions": False,
                "satellite_max_total_weight_pct": 15.0,
                "satellite_max_single_weight_pct": 5.0,
                "target_exposure_min_pct": 20.0,
                "target_exposure_max_pct": 65.0,
            }
        )

        self.assertEqual(core_df.iloc[0]["代码"], "VOO")
        self.assertEqual(core_df.iloc[0]["仓位"], "20.00% → 25.00%")
        self.assertIn("495.00", core_df.iloc[0]["价位"])
        self.assertEqual(discipline_df.iloc[0]["当前值"], "LIGHT")
        self.assertEqual(discipline_df.iloc[4]["当前值"], "否")

    def test_build_satellite_candidate_dataframe_formats_snapshot_rows(self):
        candidate_df = self.pages.build_satellite_candidate_dataframe(
            {
                "generated_at": "2026-05-13T23:10:00",
                "top_recommendations": [
                    {
                        "symbol": "MU",
                        "recommendation_status": "CONFIRMED",
                        "plan_action": "ACCUMULATE",
                        "suggested_weight_pct": 4.0,
                        "light_score": 74.5,
                        "satellite_score": 82.3,
                        "signal": "BUY",
                        "backtest": {"total_return": 0.18},
                        "monte_carlo": {"expected_return": 0.06},
                        "recommendation_reason": "趋势确认",
                        "sources": ["manual_include"],
                    }
                ],
            },
            top_only=True,
        )

        self.assertEqual(candidate_df.iloc[0]["代码"], "MU")
        self.assertEqual(candidate_df.iloc[0]["状态"], "CONFIRMED")
        self.assertEqual(candidate_df.iloc[0]["动作"], "ACCUMULATE")
        self.assertEqual(candidate_df.iloc[0]["仓位"], "4.00%")
        self.assertIn("+18.00%", candidate_df.iloc[0]["预期"])
        self.assertEqual(candidate_df.iloc[0]["亮点"], "趋势确认")


if __name__ == "__main__":
    unittest.main()
