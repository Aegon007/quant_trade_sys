import sys
import types
import unittest
from types import SimpleNamespace


class _FakeColumn:
    def __init__(self, state):
        self._state = state

    def metric(self, label, value):
        self._state["metrics"].append((label, value))


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


if __name__ == "__main__":
    unittest.main()
