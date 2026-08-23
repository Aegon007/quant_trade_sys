import unittest

from quant_core.research import weekend_universe as wu


class WeekendUniverseTests(unittest.TestCase):
    def test_build_weekend_research_universe_merges_sources_and_excludes(self):
        snapshot = wu.build_weekend_research_universe(
            data={
                "holdings": [{"symbol": "MSFT"}, {"symbol": "GELYY"}],
                "watchlist": [{"symbol": "QQQM"}],
            },
            core_rotation_snapshot={"symbols": [{"symbol": "VOO"}]},
            satellite_snapshot={"candidate_pool": [{"symbol": "MU"}, {"symbol": "MSFT"}]},
            satellite_universe={"manual_include": ["AAPL", "MU"]},
            config={"manual_include": ["GLD", "IAU"], "manual_exclude": {"GELYY"}, "max_symbols": 5},
        )

        self.assertEqual(snapshot["symbols"], ["MSFT", "QQQM", "VOO", "MU", "AAPL"])
        self.assertTrue(snapshot["truncated"])
        self.assertNotIn("GELYY", snapshot["symbols"])
        self.assertEqual(snapshot["source_counts"]["holding"], 1)
        msft = next(row for row in snapshot["symbol_sources"] if row["symbol"] == "MSFT")
        self.assertEqual(msft["sources"], ["holding", "satellite_candidate_pool"])


if __name__ == "__main__":
    unittest.main()
