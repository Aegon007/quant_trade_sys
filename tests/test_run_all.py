import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import json

from tests.support import clear_modules, install_fake_yfinance, reload_module


class RunAllTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules("jobs.run_all")
        self.module = reload_module("jobs.run_all")

    def test_build_service_specs_defaults_to_api_react_and_slack(self):
        specs = self.module.build_service_specs(
            with_ui=True,
            with_slack=True,
            python_executable="/opt/python",
            project_root=Path("/repo"),
        )

        self.assertEqual([spec.name for spec in specs], ["api-server", "react-frontend", "slack-bot"])
        self.assertEqual(
            specs[0].command,
            ["/opt/python", "-m", "jobs.api_server", "--host", "127.0.0.1", "--port", "8710"],
        )
        self.assertEqual(
            specs[1].command,
            ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        )
        self.assertEqual(specs[1].cwd, "/repo/frontend")
        self.assertEqual(
            specs[1].env,
            {
                "VITE_API_BASE_URL": "",
                "VITE_API_PROXY_TARGET": "http://127.0.0.1:8710",
            },
        )
        self.assertEqual(specs[2].command, ["/opt/python", "-m", "integrations.slack.bot"])

    def test_build_service_specs_can_disable_everything(self):
        specs = self.module.build_service_specs(with_ui=False, with_slack=False)

        self.assertEqual(specs, [])

    def test_build_service_specs_supports_lan_frontend_with_local_api_proxy(self):
        specs = self.module.build_service_specs(
            with_ui=True,
            with_slack=False,
            frontend_host="0.0.0.0",
            api_host="127.0.0.1",
            api_port=9010,
        )

        self.assertIn("0.0.0.0", specs[1].command)
        self.assertEqual(specs[1].env["VITE_API_PROXY_TARGET"], "http://127.0.0.1:9010")

    def test_node_version_check_rejects_old_node(self):
        def fake_runner(*args, **kwargs):
            return SimpleNamespace(stdout="v12.22.9\n", stderr="")

        ok, message = self.module._check_node_version(runner=fake_runner)

        self.assertFalse(ok)
        self.assertIn("too old", message)
        self.assertIn("Node.js 18+", message)

    def test_node_version_check_accepts_modern_node(self):
        def fake_runner(*args, **kwargs):
            return SimpleNamespace(stdout="v20.11.1\n", stderr="")

        ok, message = self.module._check_node_version(runner=fake_runner)

        self.assertTrue(ok)
        self.assertEqual(message, "")

    def test_emit_startup_summary_formats_each_service(self):
        statuses = [
            self.module.ServiceStartupStatus(
                name="slack-bot",
                state="started",
                detail="python -m integrations.slack.bot",
                pid=4321,
            ),
            self.module.ServiceStartupStatus(
                name="nightly-scheduler",
                state="started",
                detail="running in-process; poll=300s.",
            ),
            self.module.ServiceStartupStatus(
                name="react-frontend",
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
                "[OK] slack-bot pid=4321 - python -m integrations.slack.bot",
                "[OK] nightly-scheduler - running in-process; poll=300s.",
                "[SKIP] react-frontend - disabled by flag.",
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

    def test_maybe_run_nightly_alerts_skips_weekend_cycle(self):
        calls = []
        sunday_night = datetime.fromisoformat("2026-05-10T23:30:00")

        result = self.module.maybe_run_nightly_alerts(
            now=sunday_night,
            should_run=lambda **kwargs: True,
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

    def test_maybe_run_market_refresh_sends_slack_summary_when_enabled(self):
        sentinel_now = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        saved = []
        sent = []
        data_before = {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []}
        data_after = {"holdings": [{"symbol": "AAPL", "current_price": 102.0}], "watchlist": [], "prices_last_updated": "2026-05-11T00:00:00"}

        result = self.module.maybe_run_market_refresh(
            now=sentinel_now,
            loader=lambda: data_before,
            refresher=lambda payload, **kwargs: (data_after, True),
            saver=lambda payload: saved.append(payload),
            refresh_interval_seconds=3600,
            config_loader=lambda: {
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "alert_settings": {"send_hourly_market_summary": True},
            },
            summary_builder=lambda **kwargs: "hourly summary",
            slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
        )

        self.assertTrue(result)
        self.assertEqual(len(saved), 1)
        self.assertEqual(sent, [("hourly summary", "https://hooks.slack.com/services/test")])

    def test_maybe_run_market_refresh_skips_slack_summary_outside_market_hours_by_default(self):
        after_hours = datetime.fromisoformat("2026-05-11T18:30:00-04:00")
        sent = []

        result = self.module.maybe_run_market_refresh(
            now=after_hours,
            loader=lambda: {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []},
            refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-11T00:00:00"}, True),
            saver=lambda payload: None,
            refresh_interval_seconds=3600,
            config_loader=lambda: {
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "alert_settings": {
                    "send_hourly_market_summary": True,
                    "send_hourly_market_summary_market_hours_only": True,
                },
            },
            summary_builder=lambda **kwargs: "hourly summary",
            slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
        )

        self.assertTrue(result)
        self.assertEqual(sent, [])

    def test_maybe_run_market_refresh_can_send_after_hours_when_switch_disabled(self):
        after_hours = datetime.fromisoformat("2026-05-11T18:30:00-04:00")
        sent = []

        result = self.module.maybe_run_market_refresh(
            now=after_hours,
            loader=lambda: {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []},
            refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-11T00:00:00"}, True),
            saver=lambda payload: None,
            refresh_interval_seconds=3600,
            config_loader=lambda: {
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "alert_settings": {
                    "send_hourly_market_summary": True,
                    "send_hourly_market_summary_market_hours_only": False,
                },
            },
            summary_builder=lambda **kwargs: "hourly summary",
            slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
        )

        self.assertTrue(result)
        self.assertEqual(sent, [("hourly summary", "https://hooks.slack.com/services/test")])

    def test_maybe_run_market_refresh_skips_weekend_summary_even_when_after_hours_allowed(self):
        weekend = datetime.fromisoformat("2026-05-09T11:30:00-04:00")
        sent = []

        saved = []
        result = self.module.maybe_run_market_refresh(
            now=weekend,
            loader=lambda: {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []},
            refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-09T11:30:00"}, True),
            saver=lambda payload: saved.append(payload),
            refresh_interval_seconds=3600,
            config_loader=lambda: {
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "alert_settings": {
                    "send_hourly_market_summary": True,
                    "send_hourly_market_summary_market_hours_only": False,
                },
            },
            summary_builder=lambda **kwargs: "hourly summary",
            slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
        )

        self.assertFalse(result)
        self.assertEqual(sent, [])
        self.assertEqual(saved, [])

    def test_maybe_run_market_refresh_applies_env_webhook_overrides(self):
        market_hours = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        sent = []

        result = self.module.maybe_run_market_refresh(
            now=market_hours,
            loader=lambda: {"holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 100.0}], "watchlist": []},
            refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-11T00:00:00"}, True),
            saver=lambda payload: None,
            refresh_interval_seconds=3600,
            config_loader=lambda: {
                "slack": {"enabled": False, "webhook_url": ""},
                "alert_settings": {"send_hourly_market_summary": True},
            },
            environ={"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/from-env"},
            summary_builder=lambda **kwargs: "hourly summary",
            slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
        )

        self.assertTrue(result)
        self.assertEqual(sent, [("hourly summary", "https://hooks.slack.com/services/from-env")])

    def test_maybe_run_market_refresh_sends_discipline_alert_once_per_signature(self):
        market_hours = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        sent = []
        original_load_change_feed = self.module.cfeed.load_change_feed
        original_load_snapshot_journal = self.module.ss.load_snapshot_journal
        self.addCleanup(setattr, self.module.cfeed, "load_change_feed", original_load_change_feed)
        self.addCleanup(setattr, self.module.ss, "load_snapshot_journal", original_load_snapshot_journal)
        self.module.cfeed.load_change_feed = lambda path=None: {
            "generated_at": "2026-05-11T06:00:00",
            "high_items": [
                {
                    "category": "discipline_month",
                    "title": "月度纪律状态变化",
                    "message": "月度纪律状态从 MONITOR 变为 CAUTION。",
                }
            ],
        }
        self.module.ss.load_snapshot_journal = lambda limit=1: [
            {
                "monthly_discipline_review": {
                    "status": "CAUTION",
                    "summary": "本月纪律偏离天数偏多，系统建议优先减少计划外交易与防守状态下的手动加仓。",
                }
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "intraday_alert_state.json"
            kwargs = dict(
                now=market_hours,
                loader=lambda: {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []},
                refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-11T00:00:00"}, True),
                saver=lambda payload: None,
                refresh_interval_seconds=3600,
                config_loader=lambda: {
                    "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                    "alert_settings": {"send_hourly_market_summary": True},
                },
                summary_builder=lambda **kwargs: "hourly summary",
                slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
                intraday_alert_state_path=str(state_path),
            )
            self.module.maybe_run_market_refresh(**kwargs)
            self.module.maybe_run_market_refresh(**kwargs)

        self.assertEqual(len(sent), 2)
        self.assertIn("Discipline alert:", sent[0][0])
        self.assertNotIn("Discipline alert:", sent[1][0])

    def test_maybe_run_market_refresh_sends_standalone_intraday_alert_when_hourly_summary_disabled(self):
        market_hours = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        sent = []
        original_load_change_feed = self.module.cfeed.load_change_feed
        original_load_snapshot_journal = self.module.ss.load_snapshot_journal
        self.addCleanup(setattr, self.module.cfeed, "load_change_feed", original_load_change_feed)
        self.addCleanup(setattr, self.module.ss, "load_snapshot_journal", original_load_snapshot_journal)
        self.module.cfeed.load_change_feed = lambda path=None: {
            "generated_at": "2026-05-11T06:00:00",
            "high_items": [
                {
                    "category": "discipline_month",
                    "title": "月度纪律状态变化",
                    "message": "月度纪律状态从 MONITOR 变为 CAUTION。",
                }
            ],
        }
        self.module.ss.load_snapshot_journal = lambda limit=1: [
            {"monthly_discipline_review": {"status": "CAUTION", "summary": "本月纪律偏离天数偏多。"}}
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "intraday_alert_state.json"
            result = self.module.maybe_run_market_refresh(
                now=market_hours,
                loader=lambda: {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []},
                refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-11T00:00:00"}, True),
                saver=lambda payload: None,
                refresh_interval_seconds=3600,
                config_loader=lambda: {
                    "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                    "alert_settings": {
                        "send_hourly_market_summary": False,
                        "send_intraday_alerts": True,
                    },
                },
                slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
                intraday_alert_state_path=str(state_path),
            )

        self.assertTrue(result)
        self.assertEqual(len(sent), 1)
        self.assertIn("本月纪律偏离天数偏多", sent[0][0])

    def test_maybe_run_market_refresh_skips_discipline_alert_when_intraday_alerts_disabled(self):
        market_hours = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        sent = []
        original_load_change_feed = self.module.cfeed.load_change_feed
        original_load_snapshot_journal = self.module.ss.load_snapshot_journal
        self.addCleanup(setattr, self.module.cfeed, "load_change_feed", original_load_change_feed)
        self.addCleanup(setattr, self.module.ss, "load_snapshot_journal", original_load_snapshot_journal)
        self.module.cfeed.load_change_feed = lambda path=None: {
            "generated_at": "2026-05-11T06:00:00",
            "high_items": [
                {
                    "category": "discipline_month",
                    "title": "月度纪律状态变化",
                    "message": "月度纪律状态从 MONITOR 变为 CAUTION。",
                }
            ],
        }
        self.module.ss.load_snapshot_journal = lambda limit=1: [
            {"monthly_discipline_review": {"status": "CAUTION", "summary": "本月纪律偏离天数偏多。"}}
        ]

        result = self.module.maybe_run_market_refresh(
            now=market_hours,
            loader=lambda: {"holdings": [{"symbol": "AAPL", "current_price": 100.0}], "watchlist": []},
            refresher=lambda payload, **kwargs: ({**payload, "prices_last_updated": "2026-05-11T00:00:00"}, True),
            saver=lambda payload: None,
            refresh_interval_seconds=3600,
            config_loader=lambda: {
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "alert_settings": {
                    "send_hourly_market_summary": False,
                    "send_intraday_alerts": False,
                },
            },
            slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
        )

        self.assertTrue(result)
        self.assertEqual(sent, [])

    def test_maybe_run_intraday_tactical_tick_sends_alert_and_marks_state(self):
        now = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        deliveries = []
        original_runtime_builder = self.module._build_intraday_tactical_runtime
        original_is_market_session = self.module.nr.is_us_market_session
        self.addCleanup(setattr, self.module, "_build_intraday_tactical_runtime", original_runtime_builder)
        self.addCleanup(setattr, self.module.nr, "is_us_market_session", original_is_market_session)
        self.module._build_intraday_tactical_runtime = lambda **kwargs: (
            {"state": "PANIC", "recommended_action": "TACTICAL_HEDGE"},
            [
                {
                    "event_type": "TACTICAL_HEDGE_TRIGGER",
                    "priority": "high",
                    "symbol": "SQQQ",
                    "title": "SQQQ 盘中战术对冲触发",
                    "message": "市场进入恐慌阶段，可考虑用 SQQQ 做小仓位战术对冲。",
                    "trigger_reason": "tactical_hedge",
                    "should_notify": True,
                    "plan_action": "TACTICAL_HEDGE",
                    "action_side": "BUY",
                    "payload": {"state": "PANIC"},
                    "reason_codes": ["qqq_panic"],
                    "explanation_summary": "市场进入恐慌阶段。",
                    "explanation_bullets": ["QQQ 跌幅扩大"],
                }
            ],
        )
        self.module.nr.is_us_market_session = lambda value: True

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "intraday_event_alert_state.json"
            journal_path = Path(temp_dir) / "intraday_event_journal.jsonl"
            result = self.module.maybe_run_intraday_tactical_tick(
                now=now,
                loader=lambda: {"holdings": [], "watchlist": []},
                config_loader=lambda: {
                    "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                    "alert_settings": {"send_intraday_alerts": True},
                },
                message_router=lambda *args, **kwargs: deliveries.append(kwargs["body"]) or [{"channel": "slack", "ok": True}],
                intraday_event_alert_state_path=str(state_path),
                intraday_event_journal_path=str(journal_path),
            )

            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            journal_lines = journal_path.read_text(encoding="utf-8").strip().splitlines()

        self.assertTrue(result)
        self.assertEqual(len(deliveries), 1)
        self.assertIn("Tactical alert:", deliveries[0])
        self.assertEqual(state_payload["day"], now.date().isoformat())
        self.assertEqual(len(state_payload["sent_signatures"]), 1)
        self.assertEqual(len(journal_lines), 1)
        self.assertIn("TACTICAL_HEDGE_TRIGGER", journal_lines[0])

    def test_market_refresh_loop_runs_tactical_tick_each_poll(self):
        calls = []
        original_market_refresh = self.module.maybe_run_market_refresh
        original_tactical_tick = self.module.maybe_run_intraday_tactical_tick
        self.addCleanup(setattr, self.module, "maybe_run_market_refresh", original_market_refresh)
        self.addCleanup(setattr, self.module, "maybe_run_intraday_tactical_tick", original_tactical_tick)
        self.module.maybe_run_market_refresh = lambda **kwargs: calls.append(("refresh", kwargs["now"])) or False
        self.module.maybe_run_intraday_tactical_tick = lambda **kwargs: calls.append(("tactical", kwargs["now"], kwargs["price_cache_ttl_seconds"])) or False

        class _OneShotStopEvent:
            def __init__(self):
                self._done = False

            def is_set(self):
                return self._done

            def wait(self, _seconds):
                self._done = True
                return True

        tick_now = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        self.module.market_refresh_loop(
            _OneShotStopEvent(),
            poll_seconds=123,
            now_func=lambda: tick_now,
            loader=lambda: {"holdings": [], "watchlist": []},
            refresher=lambda payload, **kwargs: (payload, False),
            saver=lambda payload: None,
        )

        self.assertEqual(
            calls,
            [
                ("refresh", tick_now),
                ("tactical", tick_now, 123),
            ],
        )

    def test_maybe_run_weekend_research_runs_when_due(self):
        now = datetime.fromisoformat("2026-06-07T11:30:00")
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "job_status.json"
            result = self.module.maybe_run_weekend_research(
                now=now,
                config_loader=lambda: {
                    "alert_settings": {
                        "enable_weekend_research": True,
                        "weekend_research_day_local": "sunday",
                        "weekend_research_hour_local": 11,
                        "weekend_research_minute_local": 0,
                    }
                },
                runner=lambda **kwargs: calls.append(kwargs) or {"ran": True, "snapshot": {"generated_at": now.isoformat()}},
                job_status_path=str(status_path),
            )
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertTrue(result)
        self.assertEqual(calls, [{"now": now, "force": False}])
        self.assertEqual(status_payload["jobs"]["weekend-research"]["state"], "completed")

    def test_maybe_run_weekend_research_records_idle_when_not_due(self):
        now = datetime.fromisoformat("2026-06-06T09:30:00")
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "job_status.json"
            result = self.module.maybe_run_weekend_research(
                now=now,
                runner=lambda **kwargs: {
                    "ran": False,
                    "reason": "not_due",
                    "schedule": {"day": "sunday", "hour": 11, "minute": 0},
                },
                job_status_path=str(status_path),
            )
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertFalse(result)
        self.assertEqual(status_payload["jobs"]["weekend-research"]["state"], "idle")
        self.assertIn("scheduled sunday 11:00", status_payload["jobs"]["weekend-research"]["detail"])


if __name__ == "__main__":
    unittest.main()
