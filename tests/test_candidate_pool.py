import tempfile
import unittest
from pathlib import Path

from quant_core.analytics import candidate_pool


class CandidatePoolStorageTests(unittest.TestCase):
    def test_normalize_satellite_universe_cleans_symbols_and_limits(self):
        config = candidate_pool.normalize_satellite_universe(
            {
                "source_indexes": ["SP500", ""],
                "manual_include": [" nvda ", "NVDA", "mu"],
                "manual_exclude": [" tsla "],
                "max_candidate_pool_size": "80",
                "max_recommendations": 0,
            }
        )

        self.assertEqual(config["source_indexes"], ["sp500"])
        self.assertEqual(config["manual_include"], ["MU", "NVDA"])
        self.assertEqual(config["manual_exclude"], ["TSLA"])
        self.assertEqual(config["max_candidate_pool_size"], 80)
        self.assertEqual(config["max_recommendations"], 1)

    def test_snapshot_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "satellite_candidate_pool.json")
            snapshot = {"status": "READY", "top_recommendations": [{"symbol": "MU"}]}

            saved_path = candidate_pool.save_satellite_candidate_pool_snapshot(snapshot, path=path)

            self.assertEqual(saved_path, path)
            self.assertEqual(candidate_pool.load_satellite_candidate_pool_snapshot(path=path), snapshot)


if __name__ == "__main__":
    unittest.main()
