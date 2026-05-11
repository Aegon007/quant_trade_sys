import unittest
from pathlib import Path

from tests.support import clear_modules, install_fake_yfinance, reload_module


class RunAllTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules("jobs.run_all")
        self.module = reload_module("jobs.run_all")

    def test_build_service_specs_includes_slack_and_streamlit(self):
        specs = self.module.build_service_specs(
            with_ui=True,
            with_slack=True,
            python_executable="/opt/python",
            project_root=Path("/repo"),
        )

        self.assertEqual([spec.name for spec in specs], ["slack-bot", "streamlit-ui"])
        self.assertEqual(specs[0].command, ["/opt/python", "-m", "jobs.slack_bot"])
        self.assertEqual(specs[1].command, ["/opt/python", "-m", "streamlit", "run", "/repo/main.py"])

    def test_build_service_specs_can_disable_everything(self):
        specs = self.module.build_service_specs(with_ui=False, with_slack=False)

        self.assertEqual(specs, [])

    def test_emit_startup_summary_formats_each_service(self):
        statuses = [
            self.module.ServiceStartupStatus(
                name="slack-bot",
                state="started",
                detail="python -m jobs.slack_bot",
                pid=4321,
            ),
            self.module.ServiceStartupStatus(
                name="nightly-scheduler",
                state="started",
                detail="running in-process; poll=300s.",
            ),
            self.module.ServiceStartupStatus(
                name="streamlit-ui",
                state="skipped",
                detail="disabled by flag.",
            ),
        ]
        lines = []

        self.module.emit_startup_summary(statuses, printer=lines.append)

        self.assertEqual(
            lines,
            [
                "Startup status:",
                "[OK] slack-bot pid=4321 - python -m jobs.slack_bot",
                "[OK] nightly-scheduler - running in-process; poll=300s.",
                "[SKIP] streamlit-ui - disabled by flag.",
            ],
        )

    def test_maybe_run_nightly_alerts_runs_only_when_due(self):
        calls = []
        sentinel_now = object()

        result = self.module.maybe_run_nightly_alerts(
            now=sentinel_now,
            should_run=lambda **kwargs: True,
            runner=lambda **kwargs: calls.append(kwargs),
        )

        self.assertTrue(result)
        self.assertEqual(calls, [{"force": False, "dry_run": False, "now": sentinel_now}])

    def test_maybe_run_nightly_alerts_skips_when_not_due(self):
        calls = []
        sentinel_now = object()

        result = self.module.maybe_run_nightly_alerts(
            now=sentinel_now,
            should_run=lambda **kwargs: False,
            runner=lambda **kwargs: calls.append(kwargs),
        )

        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_maybe_run_market_refresh_updates_when_stale(self):
        calls = []
        sentinel_now = object()

        data = {"holdings": [{"symbol": "AAPL"}], "watchlist": []}

        def fake_refresher(payload, **kwargs):
            calls.append(("refresher", kwargs))
            payload = dict(payload)
            payload["prices_last_updated"] = "2026-05-11T00:00:00"
            return payload, True

        saved = []

        result = self.module.maybe_run_market_refresh(
            now=sentinel_now,
            loader=lambda: data,
            refresher=fake_refresher,
            saver=lambda payload: saved.append(payload),
            refresh_interval_seconds=3600,
        )

        self.assertTrue(result)
        self.assertEqual(calls, [("refresher", {"refresh_interval_seconds": 3600, "now": sentinel_now, "force": False})])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["prices_last_updated"], "2026-05-11T00:00:00")

    def test_maybe_run_market_refresh_skips_when_not_needed(self):
        calls = []
        sentinel_now = object()
        data = {"holdings": [{"symbol": "AAPL"}], "watchlist": []}

        def fake_refresher(payload, **kwargs):
            calls.append(("refresher", kwargs))
            return payload, False

        saved = []

        result = self.module.maybe_run_market_refresh(
            now=sentinel_now,
            loader=lambda: data,
            refresher=fake_refresher,
            saver=lambda payload: saved.append(payload),
            refresh_interval_seconds=3600,
        )

        self.assertFalse(result)
        self.assertEqual(calls, [("refresher", {"refresh_interval_seconds": 3600, "now": sentinel_now, "force": False})])
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
