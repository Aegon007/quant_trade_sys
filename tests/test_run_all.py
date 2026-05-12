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
            enable_auto_quant_analysis=False,
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
            enable_auto_quant_analysis=False,
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
            enable_auto_quant_analysis=False,
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
            enable_auto_quant_analysis=False,
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
            enable_auto_quant_analysis=False,
        )

        self.assertTrue(result)
        self.assertEqual(sent, [("hourly summary", "https://hooks.slack.com/services/test")])

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
            enable_auto_quant_analysis=False,
        )

        self.assertTrue(result)
        self.assertEqual(sent, [("hourly summary", "https://hooks.slack.com/services/from-env")])

    def test_maybe_run_market_refresh_auto_runs_quant_analysis_on_price_jump(self):
        now = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        data_before = {
            "holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 100.0, "cost": 90.0}],
            "watchlist": [],
            "account": {"cash_available": 1000.0},
        }
        data_after = {
            "holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 104.5, "cost": 90.0}],
            "watchlist": [],
            "account": {"cash_available": 1000.0},
            "prices_last_updated": "2026-05-11T10:30:00",
        }
        sent = []
        saved_snapshots = []
        written_reports = []
        original_build_report = self.module.nr.build_quant_analysis_report
        original_write_reports = self.module.nr.save_quant_analysis_report_files
        original_load_default_strategy = self.module.qpa.load_default_runtime_strategy
        original_build_snapshot = self.module.qpa.build_portfolio_quant_analysis_snapshot
        original_save_snapshot = self.module.qpa.save_quant_analysis_snapshot
        original_load_events = self.module.en.load_market_events
        original_select_events = self.module.en.select_active_events
        original_eval_event_risk = self.module.en.evaluate_event_risk_switch
        original_build_account_snapshot = self.module.ss.build_account_snapshot
        self.addCleanup(setattr, self.module.nr, "build_quant_analysis_report", original_build_report)
        self.addCleanup(setattr, self.module.nr, "save_quant_analysis_report_files", original_write_reports)
        self.addCleanup(setattr, self.module.qpa, "load_default_runtime_strategy", original_load_default_strategy)
        self.addCleanup(setattr, self.module.qpa, "build_portfolio_quant_analysis_snapshot", original_build_snapshot)
        self.addCleanup(setattr, self.module.qpa, "save_quant_analysis_snapshot", original_save_snapshot)
        self.addCleanup(setattr, self.module.en, "load_market_events", original_load_events)
        self.addCleanup(setattr, self.module.en, "select_active_events", original_select_events)
        self.addCleanup(setattr, self.module.en, "evaluate_event_risk_switch", original_eval_event_risk)
        self.addCleanup(setattr, self.module.ss, "build_account_snapshot", original_build_account_snapshot)
        self.module.evaluate_current_market_risk = lambda data, history_period="2y": SimpleNamespace(
            regime="NORMAL",
            risk_score=1,
            block_new_buys=False,
            max_position_weight=0.2,
            reasons=[],
            to_dict=lambda: {"regime": "NORMAL"},
        )
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows
        self.module.ss.build_account_snapshot = lambda data: {"total_capital": 1000.0, "cash_available": 1000.0, "exposure_pct": 0.0}
        self.module.evaluate_allocation_regime = lambda *args, **kwargs: SimpleNamespace(
            regime="NORMAL",
            risk_multiplier=1.0,
            to_dict=lambda: {"regime": "NORMAL"},
        )
        self.module.qpa.load_default_runtime_strategy = lambda history_period="2y": {"id": "deep_tcn", "name": "TCN", "params": {"period": history_period}}
        self.module.qpa.build_portfolio_quant_analysis_snapshot = lambda *args, **kwargs: {
            "generated_at": "2026-05-11T10:30:00",
            "summary": {"top_buy_symbols": ["AAPL"]},
            "symbols": [{"symbol": "AAPL", "signal": "BUY", "position_advice": {"action": "ADD"}}],
            "risk": {"regime": "NORMAL"},
            "event_risk": {"regime": "NORMAL"},
        }
        self.module.qpa.save_quant_analysis_snapshot = lambda snapshot, path=None: saved_snapshots.append((snapshot, path))
        self.module.nr.build_quant_analysis_report = lambda snapshot: "quant report"
        self.module.nr.save_quant_analysis_report_files = lambda snapshot, report_text=None, reports_dir=None: written_reports.append((snapshot, reports_dir)) or {"pdf_path": "x.pdf"}
        self.module.en.load_market_events = lambda auto_bootstrap=True: []
        self.module.en.select_active_events = lambda events, symbols=None, now=None, verified_only=False: []
        self.module.en.evaluate_event_risk_switch = lambda events, verified_only=True, now=None, vix=None: SimpleNamespace(
            regime="NORMAL",
            risk_score=0,
            block_new_buys=False,
            max_position_weight=0.2,
            reasons=[],
            active_event_count=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "quant_analysis_snapshot.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-11T06:00:00",
                        "summary": {"top_buy_symbols": []},
                        "symbols": [{"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}}],
                        "risk": {"regime": "NORMAL"},
                        "event_risk": {"regime": "NORMAL"},
                    }
                ),
                encoding="utf-8",
            )

            result = self.module.maybe_run_market_refresh(
                now=now,
                loader=lambda: data_before,
                refresher=lambda payload, **kwargs: (data_after, True),
                saver=lambda payload: None,
                refresh_interval_seconds=3600,
                config_loader=lambda: {
                    "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                    "alert_settings": {
                        "send_hourly_market_summary": False,
                        "send_quant_analysis_change_summary": True,
                    },
                },
                slack_sender=lambda text, url: (sent.append((text, url)) or True, "ok"),
                quant_analysis_snapshot_path=str(snapshot_path),
                report_output_dir=temp_dir,
                auto_quant_analysis_price_jump_pct=0.03,
                auto_quant_analysis_min_interval_seconds=3600,
            )

        self.assertTrue(result)
        self.assertEqual(len(saved_snapshots), 1)
        self.assertEqual(len(written_reports), 1)
        self.assertEqual(sent[-1][1], "https://hooks.slack.com/services/test")
        self.assertIn("Price jump", sent[-1][0])

    def test_maybe_run_market_refresh_auto_runs_quant_analysis_on_risk_regime_change_despite_cooldown(self):
        now = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        data_before = {
            "holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 100.0, "cost": 90.0}],
            "watchlist": [],
            "account": {"cash_available": 1000.0},
        }
        data_after = {
            "holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 100.5, "cost": 90.0}],
            "watchlist": [],
            "account": {"cash_available": 1000.0},
            "prices_last_updated": "2026-05-11T10:30:00",
        }
        saved_snapshots = []
        original_build_report = self.module.nr.build_quant_analysis_report
        original_write_reports = self.module.nr.save_quant_analysis_report_files
        original_load_default_strategy = self.module.qpa.load_default_runtime_strategy
        original_build_snapshot = self.module.qpa.build_portfolio_quant_analysis_snapshot
        original_save_snapshot = self.module.qpa.save_quant_analysis_snapshot
        original_load_events = self.module.en.load_market_events
        original_select_events = self.module.en.select_active_events
        original_eval_event_risk = self.module.en.evaluate_event_risk_switch
        original_build_account_snapshot = self.module.ss.build_account_snapshot
        self.addCleanup(setattr, self.module.nr, "build_quant_analysis_report", original_build_report)
        self.addCleanup(setattr, self.module.nr, "save_quant_analysis_report_files", original_write_reports)
        self.addCleanup(setattr, self.module.qpa, "load_default_runtime_strategy", original_load_default_strategy)
        self.addCleanup(setattr, self.module.qpa, "build_portfolio_quant_analysis_snapshot", original_build_snapshot)
        self.addCleanup(setattr, self.module.qpa, "save_quant_analysis_snapshot", original_save_snapshot)
        self.addCleanup(setattr, self.module.en, "load_market_events", original_load_events)
        self.addCleanup(setattr, self.module.en, "select_active_events", original_select_events)
        self.addCleanup(setattr, self.module.en, "evaluate_event_risk_switch", original_eval_event_risk)
        self.addCleanup(setattr, self.module.ss, "build_account_snapshot", original_build_account_snapshot)
        self.module.evaluate_current_market_risk = lambda data, history_period="2y": SimpleNamespace(
            regime="CAUTION",
            risk_score=3,
            block_new_buys=False,
            max_position_weight=0.12,
            reasons=["vol up"],
            to_dict=lambda: {"regime": "CAUTION"},
        )
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows
        self.module.ss.build_account_snapshot = lambda data: {"total_capital": 1000.0, "cash_available": 1000.0, "exposure_pct": 0.0}
        self.module.evaluate_allocation_regime = lambda *args, **kwargs: SimpleNamespace(
            regime="LIGHT",
            risk_multiplier=0.8,
            to_dict=lambda: {"regime": "LIGHT"},
        )
        self.module.qpa.load_default_runtime_strategy = lambda history_period="2y": {"id": "deep_tcn", "name": "TCN", "params": {"period": history_period}}
        self.module.qpa.build_portfolio_quant_analysis_snapshot = lambda *args, **kwargs: {
            "generated_at": "2026-05-11T10:30:00",
            "summary": {"top_buy_symbols": []},
            "symbols": [{"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}}],
            "risk": {"regime": "CAUTION"},
            "event_risk": {"regime": "NORMAL"},
        }
        self.module.qpa.save_quant_analysis_snapshot = lambda snapshot, path=None: saved_snapshots.append((snapshot, path))
        self.module.nr.build_quant_analysis_report = lambda snapshot: "quant report"
        self.module.nr.save_quant_analysis_report_files = lambda snapshot, report_text=None, reports_dir=None: {"pdf_path": "x.pdf"}
        self.module.en.load_market_events = lambda auto_bootstrap=True: []
        self.module.en.select_active_events = lambda events, symbols=None, now=None, verified_only=False: []
        self.module.en.evaluate_event_risk_switch = lambda events, verified_only=True, now=None, vix=None: SimpleNamespace(
            regime="NORMAL",
            risk_score=0,
            block_new_buys=False,
            max_position_weight=0.2,
            reasons=[],
            active_event_count=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "quant_analysis_snapshot.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-11T10:10:00",
                        "summary": {"top_buy_symbols": []},
                        "symbols": [{"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}}],
                        "risk": {"regime": "NORMAL"},
                        "event_risk": {"regime": "NORMAL"},
                    }
                ),
                encoding="utf-8",
            )

            self.module.maybe_run_market_refresh(
                now=now,
                loader=lambda: data_before,
                refresher=lambda payload, **kwargs: (data_after, True),
                saver=lambda payload: None,
                refresh_interval_seconds=3600,
                config_loader=lambda: {
                    "slack": {"enabled": False, "webhook_url": ""},
                    "alert_settings": {
                        "send_hourly_market_summary": False,
                        "send_quant_analysis_change_summary": False,
                    },
                },
                quant_analysis_snapshot_path=str(snapshot_path),
                report_output_dir=temp_dir,
                auto_quant_analysis_price_jump_pct=0.05,
                auto_quant_analysis_min_interval_seconds=3600,
            )

        self.assertEqual(len(saved_snapshots), 1)

    def test_maybe_run_market_refresh_auto_runs_quant_analysis_on_active_high_impact_event(self):
        now = datetime.fromisoformat("2026-05-11T10:30:00-04:00")
        data_before = {
            "holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 100.0, "cost": 90.0}],
            "watchlist": [],
            "account": {"cash_available": 1000.0},
        }
        data_after = {
            "holdings": [{"symbol": "AAPL", "shares": 1.0, "current_price": 100.2, "cost": 90.0}],
            "watchlist": [],
            "account": {"cash_available": 1000.0},
            "prices_last_updated": "2026-05-11T10:30:00",
        }
        saved_snapshots = []
        original_build_report = self.module.nr.build_quant_analysis_report
        original_write_reports = self.module.nr.save_quant_analysis_report_files
        original_load_default_strategy = self.module.qpa.load_default_runtime_strategy
        original_build_snapshot = self.module.qpa.build_portfolio_quant_analysis_snapshot
        original_save_snapshot = self.module.qpa.save_quant_analysis_snapshot
        original_load_events = self.module.en.load_market_events
        original_select_events = self.module.en.select_active_events
        original_eval_event_risk = self.module.en.evaluate_event_risk_switch
        original_build_account_snapshot = self.module.ss.build_account_snapshot
        self.addCleanup(setattr, self.module.nr, "build_quant_analysis_report", original_build_report)
        self.addCleanup(setattr, self.module.nr, "save_quant_analysis_report_files", original_write_reports)
        self.addCleanup(setattr, self.module.qpa, "load_default_runtime_strategy", original_load_default_strategy)
        self.addCleanup(setattr, self.module.qpa, "build_portfolio_quant_analysis_snapshot", original_build_snapshot)
        self.addCleanup(setattr, self.module.qpa, "save_quant_analysis_snapshot", original_save_snapshot)
        self.addCleanup(setattr, self.module.en, "load_market_events", original_load_events)
        self.addCleanup(setattr, self.module.en, "select_active_events", original_select_events)
        self.addCleanup(setattr, self.module.en, "evaluate_event_risk_switch", original_eval_event_risk)
        self.addCleanup(setattr, self.module.ss, "build_account_snapshot", original_build_account_snapshot)
        self.module.evaluate_current_market_risk = lambda data, history_period="2y": SimpleNamespace(
            regime="NORMAL",
            risk_score=1,
            block_new_buys=False,
            max_position_weight=0.2,
            reasons=[],
            to_dict=lambda: {"regime": "NORMAL"},
        )
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows
        self.module.ss.build_account_snapshot = lambda data: {"total_capital": 1000.0, "cash_available": 1000.0, "exposure_pct": 0.0}
        self.module.evaluate_allocation_regime = lambda *args, **kwargs: SimpleNamespace(
            regime="NORMAL",
            risk_multiplier=1.0,
            to_dict=lambda: {"regime": "NORMAL"},
        )
        self.module.qpa.load_default_runtime_strategy = lambda history_period="2y": {"id": "deep_tcn", "name": "TCN", "params": {"period": history_period}}
        self.module.qpa.build_portfolio_quant_analysis_snapshot = lambda *args, **kwargs: {
            "generated_at": "2026-05-11T10:30:00",
            "summary": {"top_buy_symbols": []},
            "symbols": [{"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}}],
            "risk": {"regime": "NORMAL"},
            "event_risk": {"regime": "RISK_OFF"},
        }
        self.module.qpa.save_quant_analysis_snapshot = lambda snapshot, path=None: saved_snapshots.append((snapshot, path))
        self.module.nr.build_quant_analysis_report = lambda snapshot: "quant report"
        self.module.nr.save_quant_analysis_report_files = lambda snapshot, report_text=None, reports_dir=None: {"pdf_path": "x.pdf"}
        self.module.en.load_market_events = lambda auto_bootstrap=True: [SimpleNamespace(title="FOMC", severity="high", event_type="fomc", symbols=["AAPL"])]
        self.module.en.select_active_events = lambda events, symbols=None, now=None, verified_only=False: list(events)
        self.module.en.evaluate_event_risk_switch = lambda events, verified_only=True, now=None, vix=None: SimpleNamespace(
            regime="RISK_OFF",
            risk_score=5,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=["FOMC"],
            active_event_count=1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "quant_analysis_snapshot.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-11T10:10:00",
                        "summary": {"top_buy_symbols": []},
                        "symbols": [{"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}}],
                        "risk": {"regime": "NORMAL"},
                        "event_risk": {"regime": "NORMAL"},
                    }
                ),
                encoding="utf-8",
            )

            self.module.maybe_run_market_refresh(
                now=now,
                loader=lambda: data_before,
                refresher=lambda payload, **kwargs: (data_after, True),
                saver=lambda payload: None,
                refresh_interval_seconds=3600,
                config_loader=lambda: {
                    "slack": {"enabled": False, "webhook_url": ""},
                    "alert_settings": {
                        "send_hourly_market_summary": False,
                        "send_quant_analysis_change_summary": False,
                    },
                },
                quant_analysis_snapshot_path=str(snapshot_path),
                report_output_dir=temp_dir,
                auto_quant_analysis_price_jump_pct=0.05,
                auto_quant_analysis_min_interval_seconds=3600,
            )

        self.assertEqual(len(saved_snapshots), 1)


if __name__ == "__main__":
    unittest.main()
