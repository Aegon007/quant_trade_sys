import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_core.research.valuation_pipeline import run_valuation_research


def price_history(last_price=90.0):
    values = [120.0] * 40 + [118, 114, 109, 101, 96, 92, last_price]
    return pd.DataFrame(
        {"Close": values, "Volume": [1_000_000] * len(values)},
        index=pd.date_range("2026-01-01", periods=len(values), freq="B"),
    )


class ValuationResearchPipelineTests(unittest.TestCase):
    def test_pipeline_generates_position_independent_recommendations(self):
        financial = {
            "symbol": "ACME",
            "status": "READY",
            "asset_type": "equity",
            "free_cash_flow": 8_000_000_000,
            "revenue": 80_000_000_000,
            "operating_margin": 0.22,
            "cash": 12_000_000_000,
            "total_debt": 6_000_000_000,
            "shares_outstanding": 1_000_000_000,
            "quality_score": 85,
            "damage_score": 15,
            "distress_probability": 0.03,
            "source": "test",
            "fiscal_period": "2026-Q2",
        }
        route = {
            "asset_type": "equity",
            "archetype": "mature_growth",
            "primary_model": "fcff_multistage",
            "secondary_models": ["reverse_dcf"],
            "assumptions": {
                "growth_rate": {"bear": 0.03, "base": 0.07, "bull": 0.11},
                "discount_rate": {"bear": 0.11, "base": 0.09, "bull": 0.08},
                "terminal_growth": {"bear": 0.02, "base": 0.025, "bull": 0.03},
            },
            "confidence": 0.85,
            "evidence": ["test filing"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_valuation_research(
                universe=[{"symbol": "ACME", "asset_type": "equity", "sector_etf": "XLK"}],
                history_loader=lambda symbol, period="2y": price_history(90 if symbol == "ACME" else 110),
                financial_loader=lambda symbol: financial,
                route_loader=lambda **kwargs: route,
                event_loader=lambda symbol: {"transience_probability": 0.8, "catalyst_score": 70, "summary": "temporary"},
                market_risk={"risk_score": 20, "regime": "NORMAL"},
                snapshot_path=str(Path(temp_dir) / "opportunities.json"),
                valuation_path=str(Path(temp_dir) / "valuations.json"),
                recommendation_path=str(Path(temp_dir) / "recommendations.json"),
                now=datetime.fromisoformat("2026-07-30T20:00:00"),
            )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["summary"]["analyzed_count"], 1)
        self.assertEqual(result["summary"]["price_source_counts"]["unknown"], 1)
        row = result["opportunities"][0]
        for forbidden in ("shares", "average_cost", "cash_available", "current_weight_pct"):
            self.assertNotIn(forbidden, row)
        self.assertIn("fair_value", row)
        self.assertIn("recommendation", row)

    def test_configured_etf_is_not_crowded_out_by_stock_scan_limit(self):
        universe = [
            {"symbol": "DROP1", "asset_type": "equity"},
            {"symbol": "DROP2", "asset_type": "equity"},
            {"symbol": "DROP3", "asset_type": "equity"},
            {"symbol": "VOO", "asset_type": "etf"},
        ]

        def financial(symbol):
            if symbol == "VOO":
                return {
                    "symbol": symbol, "asset_type": "etf", "status": "READY",
                    "earnings_yield": 0.045, "historical_earnings_yield": 0.04,
                    "quality_score": 80, "damage_score": 5, "distress_probability": 0.01,
                }
            return {
                "symbol": symbol, "asset_type": "equity", "status": "READY",
                "free_cash_flow": 100, "cash": 10, "total_debt": 0, "shares_outstanding": 10,
                "quality_score": 80, "damage_score": 5, "distress_probability": 0.01,
            }

        def route_loader(symbol, asset_type, **_kwargs):
            if asset_type == "etf":
                return {"asset_type": "etf", "archetype": "broad_market_etf", "primary_model": "etf_risk_premium", "confidence": 0.8}
            return {"asset_type": "equity", "archetype": "mature_growth", "primary_model": "fcff_multistage", "confidence": 0.8}

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_valuation_research(
                universe=universe,
                history_loader=lambda symbol, period="2y": price_history(119 if symbol == "VOO" else 80),
                financial_loader=financial,
                route_loader=route_loader,
                event_loader=lambda _symbol: {"transience_probability": 0.7, "catalyst_score": 40},
                market_risk={"risk_score": 20, "regime": "NORMAL"},
                snapshot_path=str(Path(temp_dir) / "opportunities.json"),
                valuation_path=str(Path(temp_dir) / "valuations.json"),
                recommendation_path=str(Path(temp_dir) / "recommendations.json"),
                policy={"max_deep_analysis": 2, "minimum_dislocation_score": 10},
            )

        self.assertIn("VOO", {row["symbol"] for row in result["opportunities"]})
        self.assertEqual(result["summary"]["deep_analysis_count"], 2)


if __name__ == "__main__":
    unittest.main()
