import json
import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, install_fake_yfinance, reload_module


class SlackCommandServiceTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules(
            "quant_core.common.share_utils",
            "quant_core.data.storage",
            "quant_core.ledger.transactions",
            "quant_core.portfolio.actions",
            "integrations.slack.command_parser",
            "integrations.slack.command_service",
        )
        self.data_utils = reload_module("quant_core.data.storage")
        self.transactions = reload_module("quant_core.ledger.transactions")
        self.actions = reload_module("quant_core.portfolio.actions")
        self.service = reload_module("integrations.slack.command_service")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)

        self.data_utils.DATA_FILE = str(root / "portfolio_data.json")
        self.data_utils.CACHE_FILE = str(root / "price_cache.json")
        self.data_utils.EDITABLE_DATA_FILE = str(root / "portfolio_input.json")
        self.transactions.TRANS_FILE = str(root / "transactions.json")
        self.actions.du.DATA_FILE = self.data_utils.DATA_FILE
        self.actions.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.actions.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.actions.tx.TRANS_FILE = self.transactions.TRANS_FILE
        self.service.du.DATA_FILE = self.data_utils.DATA_FILE
        self.service.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.service.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.service.pactions.du.DATA_FILE = self.data_utils.DATA_FILE
        self.service.pactions.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.service.pactions.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.service.pactions.tx.TRANS_FILE = self.transactions.TRANS_FILE
        self.audit_path = root / "command_audit.jsonl"
        self.service.COMMAND_AUDIT_FILE = str(self.audit_path)
        self.plan_path = root / "next_day_trade_plan.json"
        self.discipline_path = root / "discipline_snapshot.json"
        self.core_etf_path = root / "core_etf_snapshot.json"
        self.satellite_path = root / "satellite_candidate_pool.json"
        self.journal_path = root / "nightly_snapshot_journal.jsonl"
        self.service.TRADE_PLAN_FILE = str(self.plan_path)
        self.service.DISCIPLINE_SNAPSHOT_FILE = str(self.discipline_path)
        self.service.CORE_ETF_SNAPSHOT_FILE = str(self.core_etf_path)
        self.service.SATELLITE_CANDIDATE_POOL_FILE = str(self.satellite_path)
        self.service.NIGHTLY_JOURNAL_FILE = str(self.journal_path)
        self.validation_path = root / "strategy_validation_snapshot.json"
        self.service.STRATEGY_VALIDATION_SNAPSHOT_FILE = str(self.validation_path)
        self.data_health_path = root / "data_health_snapshot.json"
        self.plan_quality_path = root / "plan_quality_snapshot.json"
        self.service.DATA_HEALTH_SNAPSHOT_FILE = str(self.data_health_path)
        self.service.PLAN_QUALITY_SNAPSHOT_FILE = str(self.plan_quality_path)

    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_journal(self, payload):
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def test_help_command_lists_supported_commands(self):
        result = self.service.execute_slack_command("可用命令")

        self.assertTrue(result.ok)
        self.assertIn("系统概览", result.message)
        self.assertIn("今日计划 / 明日计划", result.message)
        self.assertIn("核心ETF", result.message)
        self.assertIn("卫星雷达 / top3", result.message)
        self.assertIn("买入 <代码> <股数>", result.message)

    def test_current_holdings_command_formats_positions_and_cash(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 2500.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 0.90,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 1.5, "cost": 100.0, "current_price": 120.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("当前持仓")

        self.assertTrue(result.ok)
        self.assertIn("当前持仓 (1)", result.message)
        self.assertIn("AAPL", result.message)
        self.assertIn("1.500 股", result.message)
        self.assertIn("可用现金", result.message)

    def test_plan_command_reads_next_day_trade_plan_snapshot(self):
        self._write_json(
            self.plan_path,
            {
                "plan_date": "2026-05-18",
                "decision": "ACTION",
                "summary_reason": "明日有 2 条可执行计划。",
                "items": [
                    {
                        "symbol": "VOO",
                        "plan_action": "ACCUMULATE",
                        "plan_weight_delta_pct": 3.0,
                        "buy_zone_low": 501.0,
                        "buy_zone_high": 506.0,
                        "invalid_condition": "若跳空高开过多则作废。",
                    }
                ],
            },
        )

        result = self.service.execute_slack_command("今日计划")

        self.assertTrue(result.ok)
        self.assertIn("次日交易计划", result.message)
        self.assertIn("VOO | ACCUMULATE", result.message)
        self.assertIn("买入区间", result.message)

    def test_risk_command_reads_discipline_snapshot_and_monthly_review(self):
        self._write_json(
            self.discipline_path,
            {
                "regime": "LIGHT",
                "risk_regime": "CAUTION",
                "allocation_regime": "LIGHT",
                "summary": "当前以轻仓与防守为主。",
                "can_open_new_core_positions": True,
                "can_open_new_satellite_positions": False,
                "deployable_cash": 1200.0,
                "exposure_pct": 42.5,
                "warnings": ["波动抬升。"],
            },
        )
        self._append_journal(
            {
                "monthly_discipline_review": {
                    "status": "CAUTION",
                    "follow_days": 8,
                    "ignore_days": 3,
                }
            }
        )

        result = self.service.execute_slack_command("风险状态")

        self.assertTrue(result.ok)
        self.assertIn("纪律与风险状态", result.message)
        self.assertIn("纪律状态: LIGHT", result.message)
        self.assertIn("月度纪律: CAUTION", result.message)

    def test_data_health_command_reads_health_snapshot(self):
        self._write_json(
            self.data_health_path,
            {
                "status": "DEGRADED",
                "summary": {
                    "status": "DEGRADED",
                    "tracked_symbol_count": 3,
                    "missing_price_count": 1,
                    "invalid_price_count": 1,
                    "stale_price_count": 0,
                    "primary_symbol_count": 1,
                    "fallback_symbol_count": 1,
                },
                "missing_symbols": ["VOO"],
                "invalid_symbols": ["MU"],
            },
        )

        result = self.service.execute_slack_command("数据状态")

        self.assertTrue(result.ok)
        self.assertIn("数据状态", result.message)
        self.assertIn("状态: DEGRADED", result.message)
        self.assertIn("缺失价格: VOO", result.message)
        self.assertIn("无效价格: MU", result.message)

    def test_plan_quality_command_reads_quality_snapshot(self):
        self._write_json(
            self.plan_quality_path,
            {
                "status": "DEGRADED",
                "summary": {
                    "status": "DEGRADED",
                    "review_count": 2,
                    "executed_count": 1,
                    "missed_count": 1,
                    "missed_reachable_count": 1,
                    "unplanned_trade_count": 1,
                    "invalidated_count": 0,
                    "unreachable_count": 0,
                    "execution_rate": 0.5,
                },
                "groups": {
                    "core": {"planned_count": 1, "executed_count": 1, "missed_reachable_count": 0},
                    "satellite": {"planned_count": 1, "executed_count": 0, "missed_reachable_count": 1},
                    "tactical": {"planned_count": 0, "executed_count": 0, "missed_reachable_count": 0},
                },
            },
        )

        result = self.service.execute_slack_command("计划质量")

        self.assertTrue(result.ok)
        self.assertIn("计划质量", result.message)
        self.assertIn("状态: DEGRADED", result.message)
        self.assertIn("执行率: 50.0%", result.message)
        self.assertIn("satellite", result.message)

    def test_core_command_reads_core_etf_snapshot(self):
        self._write_json(
            self.core_etf_path,
            {
                "risk_regime": "NORMAL",
                "allocation_regime": "LIGHT",
                "summary": {
                    "total_symbols": 3,
                    "accumulate_count": 1,
                    "trim_count": 1,
                },
                "symbols": [
                    {
                        "symbol": "VOO",
                        "action": "ACCUMULATE",
                        "current_weight_pct": 40.0,
                        "target_weight_pct": 45.0,
                        "rotation_score": 77.0,
                        "recommended_buy_zone_low": 500.0,
                        "recommended_buy_zone_high": 505.0,
                        "trim_zone_low": None,
                        "trim_zone_high": None,
                        "risk_break_level": 490.0,
                    }
                ],
            },
        )

        result = self.service.execute_slack_command("核心ETF")

        self.assertTrue(result.ok)
        self.assertIn("核心 ETF 引擎", result.message)
        self.assertIn("VOO | ACCUMULATE", result.message)
        self.assertIn("目标 45.0%", result.message)

    def test_validation_command_reads_strategy_validation_snapshot(self):
        self._write_json(
            self.validation_path,
            {
                "summary": {
                    "status": "REVIEW",
                    "symbol_count": 3,
                    "validated_count": 1,
                    "review_count": 1,
                    "caution_count": 1,
                    "low_sample_count": 0,
                    "warning_symbols": ["QQQ", "MU"],
                    "message": "默认策略在核心标的上未能保持领先。",
                },
                "symbols": [
                    {
                        "symbol": "QQQ",
                        "focus_role": "core",
                        "status": "REVIEW",
                        "default_rank": 2,
                        "best_strategy_name": "MACD",
                    }
                ],
            },
        )

        result = self.service.execute_slack_command("策略验证")

        self.assertTrue(result.ok)
        self.assertIn("策略验证", result.message)
        self.assertIn("状态: REVIEW", result.message)
        self.assertIn("重点复核: QQQ, MU", result.message)
        self.assertIn("QQQ | core | REVIEW", result.message)

    def test_satellite_command_reads_satellite_snapshot(self):
        self._write_json(
            self.satellite_path,
            {
                "summary": {
                    "candidate_count": 12,
                    "deep_analysis_count": 6,
                    "top_recommendation_count": 2,
                    "confirmed_count": 1,
                    "probe_count": 1,
                    "watch_count": 4,
                },
                "top_recommendations": [
                    {
                        "symbol": "MU",
                        "recommendation_status": "CONFIRMED",
                        "plan_action": "ACCUMULATE",
                        "suggested_weight_pct": 4.0,
                        "satellite_score": 81.0,
                        "recommendation_reason": "趋势与模型共振。",
                    }
                ],
            },
        )

        result = self.service.execute_slack_command("卫星雷达")

        self.assertTrue(result.ok)
        self.assertIn("卫星仓雷达", result.message)
        self.assertIn("MU | CONFIRMED / ACCUMULATE", result.message)
        self.assertIn("趋势与模型共振", result.message)

    def test_overview_command_combines_plan_risk_core_and_satellite(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 2500.0,
                    "min_cash_buffer_pct": 0.10,
                },
                "holdings": [{"symbol": "VOO", "shares": 2.0, "cost": 400.0, "current_price": 500.0}],
                "watchlist": [{"symbol": "MU", "last_price": 120.0, "notes": "radar"}],
            }
        )
        self._write_json(
            self.plan_path,
            {
                "decision": "ACTION",
                "summary_reason": "明日有 1 条可执行计划。",
            },
        )
        self._write_json(
            self.discipline_path,
            {
                "regime": "LIGHT",
                "risk_regime": "NORMAL",
            },
        )
        self._write_json(
            self.core_etf_path,
            {
                "summary": {"accumulate_count": 1, "trim_count": 0},
            },
        )
        self._write_json(
            self.satellite_path,
            {
                "summary": {"top_symbols": ["MU", "NVDA"]},
            },
        )
        self._write_json(
            self.validation_path,
            {
                "summary": {
                    "status": "CAUTION",
                    "symbol_count": 2,
                    "warning_symbols": ["QQQ"],
                }
            },
        )
        self._write_json(
            self.data_health_path,
            {"summary": {"status": "OK", "missing_price_count": 0, "invalid_price_count": 0}},
        )
        self._write_json(
            self.plan_quality_path,
            {"summary": {"status": "OK", "executed_count": 1, "missed_reachable_count": 0}},
        )
        self._append_journal(
            {
                "monthly_discipline_review": {
                    "status": "ALIGNED",
                    "follow_days": 5,
                    "ignore_days": 0,
                }
            }
        )

        result = self.service.execute_slack_command("系统概览")

        self.assertTrue(result.ok)
        self.assertIn("系统概览", result.message)
        self.assertIn("计划: ACTION", result.message)
        self.assertIn("卫星雷达 Top: MU, NVDA", result.message)
        self.assertIn("策略验证: CAUTION", result.message)
        self.assertIn("数据健康: OK", result.message)
        self.assertIn("计划质量: OK", result.message)
        self.assertIn("月度纪律: ALIGNED", result.message)

    def test_buy_command_moves_watchlist_to_holdings_and_writes_audit_log(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 3000.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [],
                "watchlist": [
                    {"symbol": "MSFT", "notes": "watch", "last_price": 310.0}
                ],
            }
        )

        result = self.service.execute_slack_command("买入 MSFT 1.5")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("已买入 MSFT 1.500 股", result.message)
        self.assertEqual(data["watchlist"], [])
        self.assertEqual(data["holdings"][0]["symbol"], "MSFT")
        self.assertEqual(data["account"]["cash_available"], 2535.0)
        audit_rows = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(audit_rows[-1]["command_name"], "BUY")
        self.assertTrue(audit_rows[-1]["ok"])

    def test_sell_all_command_moves_position_back_to_watchlist(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 1000.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 2.0, "cost": 150.0, "current_price": 200.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("全部卖出 AAPL")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("并转入关注列表", result.message)
        self.assertEqual(data["holdings"], [])
        self.assertEqual(data["watchlist"][0]["symbol"], "AAPL")

    def test_status_command_reports_watchlist_details(self):
        self.data_utils.save_data(
            {
                "account": {},
                "holdings": [],
                "watchlist": [
                    {"symbol": "NVDA", "notes": "pullback", "last_price": 820.0}
                ],
            }
        )

        result = self.service.execute_slack_command("状态 NVDA")

        self.assertTrue(result.ok)
        self.assertIn("NVDA 当前在关注列表中", result.message)
        self.assertIn("pullback", result.message)
        self.assertIn("$820.00", result.message)

    def test_refresh_all_command_forces_source_refresh(self):
        calls = []
        self.service.pactions.refresh_all_market_data = lambda force_source_refresh=False: (
            calls.append(force_source_refresh)
            or {"prices_last_updated": "2026-05-20T09:30:00"}
        )

        result = self.service.execute_slack_command("刷新 全部")

        self.assertTrue(result.ok)
        self.assertEqual(calls, [True])
        self.assertIn("已强制刷新行情数据", result.message)

    def test_current_holdings_command_hides_nan_price(self):
        self.data_utils.save_data(
            {
                "account": {"cash_available": 1000.0},
                "holdings": [
                    {"symbol": "AAPL", "shares": 1.0, "cost": 100.0, "current_price": float("nan"), "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("当前持仓")

        self.assertTrue(result.ok)
        self.assertNotIn("nan", result.message.lower())
        self.assertIn("现价 —", result.message)

    def test_core_command_hides_nan_price_ranges(self):
        self._write_json(
            self.core_etf_path,
            {
                "risk_regime": "NORMAL",
                "allocation_regime": "LIGHT",
                "summary": {"total_symbols": 1, "accumulate_count": 1, "trim_count": 0},
                "symbols": [
                    {
                        "symbol": "VOO",
                        "action": "ACCUMULATE",
                        "current_weight_pct": 40.0,
                        "target_weight_pct": 45.0,
                        "rotation_score": 77.0,
                        "recommended_buy_zone_low": float("nan"),
                        "recommended_buy_zone_high": float("nan"),
                        "trim_zone_low": float("nan"),
                        "trim_zone_high": float("nan"),
                        "risk_break_level": float("nan"),
                    }
                ],
            },
        )

        result = self.service.execute_slack_command("核心ETF")

        self.assertTrue(result.ok)
        self.assertNotIn("nan", result.message.lower())
        self.assertIn("买 — | 减 — | 破位 —", result.message)

    def test_add_watch_command_appends_symbol_to_watchlist(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 2000.0,
                },
                "holdings": [],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("关注 QQQ")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("已关注 QQQ", result.message)
        self.assertEqual(len(data["watchlist"]), 1)
        self.assertEqual(data["watchlist"][0]["symbol"], "QQQ")
        audit_rows = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(audit_rows[-1]["command_name"], "ADD_WATCH")

    def test_remove_watch_command_deletes_symbol_from_watchlist(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 2000.0,
                },
                "holdings": [],
                "watchlist": [
                    {"symbol": "TSLA", "notes": "watch", "last_price": 180.0}
                ],
            }
        )

        result = self.service.execute_slack_command("取消关注 TSLA")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("已取消关注 TSLA", result.message)
        self.assertEqual(data["watchlist"], [])
        audit_rows = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(audit_rows[-1]["command_name"], "REMOVE_WATCH")

    def test_move_to_holding_command_requires_watchlist_entry(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 2000.0,
                },
                "holdings": [],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("转到持仓 MSFT 1")

        self.assertFalse(result.ok)
        self.assertIn("MSFT 不在关注列表中", result.message)
        self.assertIn("买入 MSFT <股数>", result.message)

    def test_invalid_fractional_share_returns_error(self):
        result = self.service.execute_slack_command("买入 AAPL 0.0005")

        self.assertFalse(result.ok)
        self.assertIn("至少为", result.message)


if __name__ == "__main__":
    unittest.main()
