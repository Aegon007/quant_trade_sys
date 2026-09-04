import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from quant_core.diagnostics import build_diagnostics_bundle


class ResearchDiagnosticsTests(unittest.TestCase):
    def test_bundle_contains_research_artifacts_and_no_portfolio_data(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            recommendation = root / "recommendations.json"
            recommendation.write_text(json.dumps({"status": "READY"}), encoding="utf-8")
            artifacts = {"recommendations.json": str(recommendation)}
            with patch("quant_core.diagnostics.DIAGNOSTIC_FILES", artifacts):
                payload = build_diagnostics_bundle()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
        self.assertIn("snapshots/recommendations.json", names)
        self.assertTrue(all("portfolio" not in name.lower() for name in names))
        self.assertTrue(all("transaction" not in name.lower() for name in names))


if __name__ == "__main__":
    unittest.main()
