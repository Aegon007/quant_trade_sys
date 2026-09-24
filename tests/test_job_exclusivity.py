import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from quant_core.api import actions


class JobExclusivityTests(unittest.TestCase):
    def test_dead_owner_lock_is_reclaimed_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            lock_path = state_dir / ".market-refresh.lock"
            lock_path.write_text("pid=987654 started=2026-09-10T10:18:27\n", encoding="utf-8")

            with (
                patch.object(actions.qpaths, "RESEARCH_STATE_DIR", state_dir),
                patch.object(actions, "_process_alive", return_value=False),
            ):
                with actions._exclusive_job("manual-market-refresh") as acquired:
                    self.assertTrue(acquired)
                    self.assertIn("name=manual-market-refresh", lock_path.read_text(encoding="utf-8"))

            self.assertFalse(lock_path.exists())

    def test_live_owner_lock_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            lock_path = state_dir / ".market-refresh.lock"
            original = "pid=12345 started=2026-09-10T10:18:27\n"
            lock_path.write_text(original, encoding="utf-8")

            with (
                patch.object(actions.qpaths, "RESEARCH_STATE_DIR", state_dir),
                patch.object(actions, "_process_alive", return_value=True),
            ):
                with actions._exclusive_job("manual-market-refresh") as acquired:
                    self.assertFalse(acquired)

            self.assertEqual(lock_path.read_text(encoding="utf-8"), original)

    def test_concurrent_job_is_blocked_without_reporting_failure(self):
        @contextmanager
        def denied(_name):
            yield False

        with (
            patch.object(actions, "_exclusive_job", denied),
            patch.object(actions.job_registry, "load_job_status", return_value={"jobs": {}}),
            patch.object(actions.job_registry, "mark_stale_jobs", side_effect=lambda payload: payload),
            patch.object(actions.job_registry, "update_job_status") as update_status,
        ):
            actions.run_with_job_status("manual-market-refresh", lambda: {}, run_async=False)

        final_call = update_status.call_args_list[-1]
        self.assertEqual(final_call.kwargs["state"], "blocked")
        self.assertIn("未重复启动", final_call.kwargs["detail"])


if __name__ == "__main__":
    unittest.main()
