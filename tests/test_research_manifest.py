import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_core.research.manifest import ResearchManifest


class ResearchManifestTests(unittest.TestCase):
    def test_manifest_persists_step_progress_and_failure(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "manifest.json")
            manifest = ResearchManifest(path=path, run_id="test-run")
            manifest.start()
            manifest.step("market", 15, "市场数据完成")
            manifest.fail(RuntimeError("boom"))
            payload = manifest.load()
        self.assertEqual(payload["state"], "failed")
        self.assertEqual(payload["steps"]["market"]["state"], "completed")
        self.assertIn("boom", payload["error"])


if __name__ == "__main__":
    unittest.main()
