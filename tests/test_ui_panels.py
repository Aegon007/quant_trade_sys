import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace


class _FakeColumn:
    def __init__(self, state):
        self._state = state

    def metric(self, label, value):
        self._state["metrics"].append((label, value))

    def button(self, label, key=None):
        self._state.setdefault("buttons", []).append((label, key))
        return False


class _FakeExpander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.state = {
            "subheaders": [],
            "infos": [],
            "warnings": [],
            "errors": [],
            "successes": [],
            "captions": [],
            "markdowns": [],
            "metrics": [],
            "dataframes": [],
        }

    def subheader(self, text):
        self.state["subheaders"].append(text)

    def info(self, text):
        self.state["infos"].append(text)

    def warning(self, text):
        self.state["warnings"].append(text)

    def error(self, text):
        self.state["errors"].append(text)

    def success(self, text):
        self.state["successes"].append(text)

    def caption(self, text):
        self.state["captions"].append(text)

    def markdown(self, text):
        self.state["markdowns"].append(text)

    def dataframe(self, df, **kwargs):
        self.state["dataframes"].append(df)

    def columns(self, count):
        return [_FakeColumn(self.state) for _ in range(count)]

    def expander(self, label):
        return _FakeExpander()


class UIPanelsTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.ModuleType("streamlit")
        if "app.ui.panels" in sys.modules:
            del sys.modules["app.ui.panels"]
        from app.ui import panels

        self.panels = panels
        self.fake_st = _FakeStreamlit()

    def test_render_account_snapshot_panel_shows_missing_capital_info(self):
        self.panels.render_account_snapshot_panel(
            {
                "total_capital": None,
                "cash_available": None,
            },
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
        )

        self.assertTrue(self.fake_st.state["infos"])
        self.assertIn("尚未配置可用现金", self.fake_st.state["infos"][0])
        self.assertEqual(self.fake_st.state["metrics"], [])

    def test_render_market_risk_gate_banner_uses_error_for_risk_off(self):
        decision = SimpleNamespace(
            regime="RISK_OFF",
            risk_score=6,
            max_position_weight=0.08,
            reasons=["risk high"],
        )
        snapshot = SimpleNamespace(
            vix=35.0,
            benchmark_drawdown=-0.12,
            benchmark_volatility=0.42,
        )
        self.panels.render_market_risk_gate_banner(
            decision,
            snapshot,
            L=lambda key: key,
            st_module=self.fake_st,
        )

        self.assertEqual(len(self.fake_st.state["errors"]), 1)
        self.assertIn("market_risk_gate", self.fake_st.state["errors"][0])
        self.assertEqual(len(self.fake_st.state["warnings"]), 0)
        self.assertEqual(len(self.fake_st.state["successes"]), 0)

    def test_render_data_source_status_panel_warns_when_fallback_is_active(self):
        self.panels.render_data_source_status_panel(
            {
                "history": {
                    "primary_source": "yfinance",
                    "last_source": "stooq",
                    "fallback_requests": 1,
                    "last_symbol": "SPY",
                    "last_error": "dns failed",
                },
                "prices": {
                    "primary_source": "stooq",
                    "last_source": "yfinance",
                    "fallback_symbols": 2,
                    "last_symbols": ["AAPL", "MSFT"],
                    "last_error": "",
                },
            },
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
        )

        self.assertTrue(any("备用源已介入" in text for text in self.fake_st.state["warnings"]))
        self.assertTrue(any("历史主源错误" in text for text in self.fake_st.state["captions"]))
        self.assertTrue(self.fake_st.state["metrics"])
        self.assertIn(("历史数据来源", "备用源 Stooq"), self.fake_st.state["metrics"])
        self.assertIn(("现价数据来源", "备用源 Yahoo"), self.fake_st.state["metrics"])

    def test_render_active_events_panel_shows_empty_message(self):
        summary = SimpleNamespace(
            overview="overview text",
            top_headline_details=[],
            top_headlines=[],
        )
        decision = SimpleNamespace(regime="NORMAL", risk_score=0, active_event_count=0)
        self.panels.render_active_events_panel(
            [],
            decision,
            [{"source_id": "mock", "ok": True, "fetched": 2}],
            L=lambda key: key,
            lang="zh",
            st_module=self.fake_st,
            summarize_news_events=lambda events, lang, max_headlines: summary,
        )

        self.assertTrue(any("overview text" in text for text in self.fake_st.state["infos"]))
        self.assertTrue(any("event_risk_none" in text for text in self.fake_st.state["infos"]))
        self.assertTrue(any("mock" in text for text in self.fake_st.state["captions"]))

    def test_render_analysis_freshness_banner_warns_when_holdings_are_expired(self):
        self.panels.render_analysis_freshness_banner(
            {
                "expired_symbols": ["AAPL"],
                "missing_symbols": ["MSFT"],
                "needs_warning": True,
            },
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
        )

        self.assertEqual(len(self.fake_st.state["warnings"]), 1)
        self.assertIn("AAPL", self.fake_st.state["warnings"][0])
        self.assertIn("MSFT", self.fake_st.state["warnings"][0])

    def test_render_discipline_snapshot_panel_renders_summary_metrics(self):
        self.panels.render_discipline_snapshot_panel(
            {
                "regime": "LIGHT",
                "risk_regime": "CAUTION",
                "can_open_new_core_positions": True,
                "can_open_new_satellite_positions": False,
                "summary": "当前以轻仓与防守为主。",
                "warnings": ["暂停新开卫星仓"],
                "reasons": ["风险处于警戒区"],
            },
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
        )

        self.assertTrue(any(metric[0] == "纪律状态" for metric in self.fake_st.state["metrics"]))
        self.assertTrue(self.fake_st.state["warnings"])

    def test_render_change_feed_panel_shows_high_and_medium_items(self):
        self.panels.render_change_feed_panel(
            {
                "summary": {"high_count": 1, "medium_count": 1, "low_count": 0},
                "high_items": [{"title": "纪律层状态切换", "message": "从 NORMAL 到 LIGHT", "symbol": None}],
                "medium_items": [{"title": "VOO 目标权重调整", "message": "从 50% 到 55%", "symbol": "VOO"}],
            },
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
        )

        self.assertTrue(any(metric[0] == "高优先级" for metric in self.fake_st.state["metrics"]))
        self.assertTrue(any("纪律层状态切换" in text for text in self.fake_st.state["warnings"]))
        self.assertTrue(any("VOO 目标权重调整" in text for text in self.fake_st.state["captions"]))

    def test_render_change_feed_priority_banner_uses_error_for_discipline_month(self):
        self.panels.render_change_feed_priority_banner(
            {
                "high_items": [
                    {
                        "category": "discipline_month",
                        "title": "月度 IGNORE 天数上升",
                        "message": "月度 IGNORE 天数从 1 上升到 4，FOLLOW 为 3。",
                    }
                ]
            },
            st_module=self.fake_st,
        )

        self.assertEqual(len(self.fake_st.state["errors"]), 1)
        self.assertIn("IGNORE 天数", self.fake_st.state["errors"][0])

    def test_render_nightly_manifest_panel_renders_step_rows(self):
        self.panels.render_nightly_manifest_panel(
            {
                "run_id": "20260513-nightly",
                "status": "completed",
                "resumed_at": None,
                "steps": {
                    "quant_analysis_snapshot": {
                        "status": "completed",
                        "reused": True,
                        "output_file": "snapshot.json",
                        "error_message": None,
                    }
                },
            },
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
        )

        self.assertTrue(any(metric[0] == "运行 ID" for metric in self.fake_st.state["metrics"]))
        self.assertTrue(self.fake_st.state["dataframes"])

    def test_render_monthly_discipline_review_panel_shows_aligned_idle_month(self):
        scoreboard = SimpleNamespace(
            expectancy_return_pct=None,
            win_rate=None,
        )
        self.panels.render_monthly_discipline_review_panel(
            discipline_snapshot={"regime": "NORMAL"},
            scoreboard=scoreboard,
            latest_post_close_review=None,
            snapshot_journal=[
                {
                    "generated_at": "2026-05-10T23:00:00",
                    "daily_recap": {"day": "2026-05-10", "trade_count": 0, "realized_pl": 0.0, "symbols": []},
                    "trade_plan": {"has_actions": False},
                    "execution_review": {"executed_count": 0, "missed_count": 0, "unplanned_trade_count": 0},
                    "discipline_snapshot": {"regime": "NORMAL"},
                }
            ],
            ui_text=lambda zh, en: zh,
            st_module=self.fake_st,
            now=datetime(2026, 5, 14, 9, 0, 0),
        )

        self.assertTrue(any(metric[0] == "复盘月份" for metric in self.fake_st.state["metrics"]))
        self.assertTrue(self.fake_st.state["successes"])
        self.assertTrue(self.fake_st.state["dataframes"])


if __name__ == "__main__":
    unittest.main()
