import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


class TrainingExportTests(unittest.TestCase):
    def test_bundle_contains_analysis_files_manifest_and_no_secrets(self):
        from quant_core.models.multi_horizon.export import build_training_analysis_bundle

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            validation = root / "validation.json"
            panel = root / "panel.parquet"
            validation.write_text(
                json.dumps(
                    {
                        "status": "REVIEW",
                        "horizons": [252],
                        "governance": {
                            "promotion_gates": {
                                "minimum_walk_forward_folds": True,
                                "positive_rank_ic": False,
                            },
                            "promotion_metrics": {
                                "candidate_rank_ic": -0.1,
                                "candidate_top_k_risk_free_excess_return": 0.05,
                            },
                        },
                        "candidate": {"horizons": {"252": {"directional_accuracy": 0.49}}},
                    }
                ),
                encoding="utf-8",
            )
            panel.write_bytes(b"PARQUET")
            payload = build_training_analysis_bundle(
                files={
                    "reports/validation.json": str(validation),
                    "data/panel.parquet": str(panel),
                    "models/missing.pt": str(root / "missing.pt"),
                }
            )

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            html_report = archive.read("analysis/training_analysis.html").decode("utf-8")
            markdown_report = archive.read("analysis/training_analysis.md").decode("utf-8")

        self.assertIn("reports/validation.json", names)
        self.assertIn("data/panel.parquet", names)
        self.assertIn("analysis/training_analysis.html", names)
        self.assertIn("analysis/training_analysis.md", names)
        self.assertIn("runtime_environment.json", names)
        self.assertFalse(manifest["privacy"]["contains_notification_secrets"])
        self.assertEqual(len(manifest["included"]), 2)
        self.assertEqual(manifest["missing"][0]["archive_name"], "models/missing.pt")
        self.assertFalse(any("notification" in name or "portfolio" in name for name in names))

        self.assertIn("Quant Training Analysis", html_report)
        self.assertIn("Promotion Readiness", html_report)
        self.assertIn("positive_rank_ic", html_report)
        self.assertIn("# Multi-Horizon Training Analysis", markdown_report)
