import unittest
from unittest.mock import patch

from quant_core.data.data_health import build_data_health_snapshot


def _opportunities(*, scanned=30, analyzed=20, deep=20, errors=None):
    return {
        "summary": {
            "universe_count": 40,
            "scanned_count": scanned,
            "deep_analysis_count": deep,
            "analyzed_count": analyzed,
        },
        "opportunities": [{"symbol": f"S{index}"} for index in range(analyzed)],
        "errors": list(errors or []),
    }


class DataHealthTests(unittest.TestCase):
    @patch("quant_core.data.data_health.cache_status", return_value={"status": "MISSING", "symbol_count": 0})
    def test_completed_research_is_not_degraded_by_optional_latest_price_cache(self, _cache):
        snapshot = build_data_health_snapshot(
            opportunities=_opportunities(),
            valuations={"valuations": [{"route_source": "rules"} for _ in range(20)]},
            market_risk={"status": "READY"},
        )

        self.assertEqual(snapshot["status"], "OK")
        self.assertIn("最新价缓存", snapshot["summary"]["warnings"])

    @patch("quant_core.data.data_health.cache_status", return_value={"status": "OK", "symbol_count": 40})
    def test_small_number_of_symbol_failures_is_reported_without_global_degradation(self, _cache):
        errors = [{"symbol": "BAD", "stage": "scan", "error": "missing"}] * 2
        snapshot = build_data_health_snapshot(
            opportunities=_opportunities(errors=errors),
            valuations={"valuations": [{"route_source": "llm"} for _ in range(20)]},
            market_risk={"status": "READY"},
            require_llm_route=True,
        )

        self.assertEqual(snapshot["status"], "OK")
        self.assertEqual(snapshot["summary"]["error_count"], 2)

    @patch("quant_core.data.data_health.cache_status", return_value={"status": "OK", "symbol_count": 40})
    def test_material_failure_ratio_degrades_health(self, _cache):
        errors = [{"symbol": f"BAD{index}", "stage": "scan", "error": "missing"} for index in range(8)]
        snapshot = build_data_health_snapshot(
            opportunities=_opportunities(scanned=22, analyzed=14, deep=20, errors=errors),
            valuations={"valuations": [{"route_source": "llm"} for _ in range(14)]},
            market_risk={"status": "READY"},
            require_llm_route=True,
        )

        self.assertEqual(snapshot["status"], "DEGRADED")
        self.assertIn("失败比例", snapshot["summary"]["reason"])

    @patch("quant_core.data.data_health.cache_status", return_value={"status": "OK", "symbol_count": 40})
    def test_llm_coverage_only_matters_when_policy_requires_it(self, _cache):
        valuations = {"valuations": [{"route_source": "rules"} for _ in range(20)]}

        optional = build_data_health_snapshot(
            opportunities=_opportunities(), valuations=valuations, market_risk={"status": "READY"}
        )
        required = build_data_health_snapshot(
            opportunities=_opportunities(),
            valuations=valuations,
            market_risk={"status": "READY"},
            require_llm_route=True,
        )

        self.assertEqual(optional["status"], "OK")
        self.assertEqual(required["status"], "DEGRADED")

    @patch("quant_core.data.data_health.cache_status", return_value={"status": "OK", "symbol_count": 40})
    def test_market_refresh_without_research_payload_does_not_invent_coverage_failure(self, _cache):
        snapshot = build_data_health_snapshot(market_risk={"status": "READY"})

        self.assertEqual(snapshot["status"], "OK")
        self.assertNotIn("完成率", snapshot["summary"]["reason"])


if __name__ == "__main__":
    unittest.main()
