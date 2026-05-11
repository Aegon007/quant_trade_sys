import tempfile
import unittest
from pathlib import Path


class PathsTests(unittest.TestCase):
    def test_storage_paths_are_grouped_under_storage_directory(self):
        from quant_core import paths as qpaths

        self.assertIn("/storage/state/", qpaths.PORTFOLIO_DATA_FILE)
        self.assertIn("/storage/state/", qpaths.PORTFOLIO_INPUT_FILE)
        self.assertIn("/storage/state/", qpaths.PRICE_CACHE_FILE)
        self.assertIn("/storage/config/", qpaths.MARKET_EVENTS_EXAMPLE_FILE)
        self.assertIn("/storage/config/", qpaths.NOTIFICATION_CONFIG_EXAMPLE_FILE)
        self.assertIn("/storage/config/", qpaths.PORTFOLIO_INPUT_EXAMPLE_FILE)

    def test_migrate_legacy_files_moves_file_when_target_missing(self):
        from quant_core import paths as qpaths

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "legacy.json"
            dst = root / "nested" / "new.json"
            src.write_text('{"a": 1}', encoding="utf-8")

            qpaths.migrate_legacy_files([(str(src), str(dst))])

            self.assertFalse(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"a": 1}')

    def test_migrate_legacy_files_does_not_overwrite_existing_target(self):
        from quant_core import paths as qpaths

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "legacy.json"
            dst = root / "nested" / "new.json"
            src.write_text('{"a": 1}', encoding="utf-8")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text('{"a": 2}', encoding="utf-8")

            qpaths.migrate_legacy_files([(str(src), str(dst))])

            self.assertTrue(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"a": 2}')


if __name__ == "__main__":
    unittest.main()
