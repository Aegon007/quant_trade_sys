import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class NightlyManifestTests(unittest.TestCase):
    def setUp(self):
        from quant_core.execution import nightly_manifest

        self.module = nightly_manifest

    def test_manifest_supports_resume_and_step_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = str(Path(temp_dir) / "nightly_run_manifest.json")
            output_path = str(Path(temp_dir) / "step.json")
            Path(output_path).write_text("{}", encoding="utf-8")
            now = datetime(2026, 5, 13, 23, 0, 0)

            manifest = self.module.initialize_nightly_run_manifest(now=now, force=False, path=manifest_path)
            manifest = self.module.mark_step_started(manifest, step_name="multi_horizon_inference", input_version="20260513-nightly", path=manifest_path, now=now)
            manifest = self.module.mark_step_completed(
                manifest,
                step_name="multi_horizon_inference",
                output_file=output_path,
                input_version="20260513-nightly",
                path=manifest_path,
                now=now,
            )

            resumed = self.module.initialize_nightly_run_manifest(now=now, force=False, path=manifest_path)
            self.assertTrue(self.module.can_resume_step(resumed, step_name="multi_horizon_inference", output_file=output_path, now=now))
            finalized = self.module.finalize_nightly_run_manifest(resumed, status="completed", path=manifest_path, now=now)
            self.assertEqual(finalized["status"], "completed")


if __name__ == "__main__":
    unittest.main()
