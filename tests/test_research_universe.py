import unittest

from quant_core.research.universe import build_research_universe


class ResearchUniverseTests(unittest.TestCase):
    def test_index_constituents_keep_sector_benchmark_metadata(self):
        result = build_research_universe(
            {
                "source_indexes": ["sp500"],
                "manual_include": [],
                "manual_exclude": [],
                "etfs": [],
                "max_universe_size": 10,
            },
            index_loader=lambda _name: [
                {
                    "symbol": "AAPL",
                    "sector": "Information Technology",
                    "industry": "Technology Hardware",
                    "sector_etf": "XLK",
                }
            ],
            watchlist_loader=lambda: [],
        )

        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertEqual(result[0]["sector"], "Information Technology")
        self.assertEqual(result[0]["sector_etf"], "XLK")


if __name__ == "__main__":
    unittest.main()
