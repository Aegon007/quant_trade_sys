import unittest

from quant_core import paths


class PathsTests(unittest.TestCase):
    def test_runtime_files_live_in_grouped_directories(self):
        self.assertIn("/storage/config/", paths.RESEARCH_UNIVERSE_FILE)
        self.assertIn("/storage/state/valuation_radar/", paths.OPPORTUNITY_SNAPSHOT_FILE)
        self.assertIn("/storage/journals/valuation_radar/", paths.RECOMMENDATION_JOURNAL_FILE)
        self.assertIn("/storage/cache/valuation_radar", str(paths.RESEARCH_CACHE_DIR))
        self.assertIn("/reports/", paths.VALUATION_REPORT_LATEST_MD)

    def test_paths_do_not_expose_portfolio_or_model_artifacts(self):
        names = set(vars(paths))
        self.assertFalse(any("PORTFOLIO" in name or "CHECKPOINT" in name or "TRANSACTION" in name for name in names))


if __name__ == "__main__":
    unittest.main()
