"""tests/test_report.py
Comprehensive test suite for Evidence-Based Impact Report,
Data-Traceability, Grounded Narrative Validation, and Counterfactual Interventions.
"""

import json
import tempfile
import unittest
from pathlib import Path

from schooltwin.report import generate_impact_report
from schooltwin.report_narrative import (
    build_deterministic_narrative,
    validate_narrative_grounding,
)


class TestReportAndNarrative(unittest.TestCase):
    """Test suite for WP3 impact report and narrative validator."""

    def test_narrative_validator_rejects_injected_fake_numbers(self):
        """Invariant 3: Any hallucinated or invented number in narrative is strictly caught and rejected."""
        facts = {
            "metrics": [
                {"id": "attendance_rate_mean", "scenario": 90.4, "control": 92.1},
                {"id": "closing_cash_delta_inr", "scenario": -25000, "control": 0},
            ],
            "incidents": [
                {"type": "water_cooler_breakdown", "onset_minute": 600, "end_minute": 780}
            ],
        }

        # 1. Grounded narrative with cited metrics passes
        valid_text = (
            "During the incident, average attendance was [ref:attendance_rate_mean] 90.4% "
            "compared to 92.1% in the control run. Total cash impact was [ref:closing_cash_delta_inr] -25000 INR."
        )
        is_grounded, errs = validate_narrative_grounding(valid_text, facts)
        self.assertTrue(is_grounded, f"Grounded text should pass, but failed: {errs}")

        # 2. Injected hallucinated number (e.g. 99.9% or ₹5,000,000) fails validation
        fake_text = (
            "During the incident, average attendance dropped to 99.9% and "
            "caused an unexpected loss of 5000000 INR."
        )
        is_fake_grounded, fake_errs = validate_narrative_grounding(fake_text, facts)
        self.assertFalse(is_fake_grounded, "Hallucinated numbers must be rejected")
        self.assertTrue(any("not present in facts JSON" in e for e in fake_errs))

    def test_deterministic_narrative_always_available_offline(self):
        """Principle 6: Deterministic template generates fully grounded narrative when Ollama is offline."""
        facts = {
            "metrics": [
                {"id": "attendance_rate_mean", "scenario": 88.5, "control": 93.0},
                {"id": "closing_cash_delta_inr", "scenario": -12500, "control": 0},
                {"id": "response_time_minutes", "scenario": 8, "control": 0},
            ],
            "incidents": [
                {
                    "type": "serious_student_fight",
                    "origin": {"zone_id": "playground", "status": "known"},
                    "onset_minute": 600,
                    "end_minute": 680,
                }
            ],
        }

        from schooltwin.report_narrative import generate_report_narrative

        narrative = generate_report_narrative(facts)
        self.assertEqual(narrative["origin"], "template")
        self.assertIn("blocks", narrative)
        self.assertTrue(len(narrative["blocks"]) >= 2)

        # Confirm template text passes strict grounding check
        full_text = " ".join(b["text"] for b in narrative["blocks"])
        is_grounded, errs = validate_narrative_grounding(full_text, facts)
        self.assertTrue(is_grounded, f"Deterministic template must be 100% grounded, got: {errs}")

    def test_impact_report_generation_and_source_traceability(self):
        """Every metric in report.json must trace to a verified source file and path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "scen_test"
            pack_dir.mkdir(parents=True)
            (pack_dir / "days").mkdir()

            # Mock meta.json
            meta_payload = {
                "scenario_id": "scen_test",
                "days": [
                    {
                        "i": 182,
                        "date": "2026-07-02",
                        "open": True,
                        "enrolled": 1000,
                        "present": 910,
                        "attendance_rate": 91.0,
                        "finance": {"cash": 3000000},
                        "uncovered": 2,
                    }
                ],
                "incidents": [
                    {
                        "incident_id": "INC-0001",
                        "type": "water_cooler_breakdown",
                        "onset_minute": 600,
                        "origin": {"zone_id": "corridor_1", "status": "known"},
                    }
                ],
            }
            (pack_dir / "meta.json").write_text(json.dumps(meta_payload), encoding="utf-8")
            (pack_dir / "incidents.json").write_text(json.dumps(meta_payload["incidents"]), encoding="utf-8")

            report = generate_impact_report(
                scenario_pack_dir=pack_dir,
                control_pack_dir=None,
            )

            self.assertIn("report_id", report)
            self.assertIn("metrics", report)
            self.assertTrue(len(report["metrics"]) > 0)

            # Ensure every single metric has documented sources, formula, and explicit status
            for m in report["metrics"]:
                self.assertIn("id", m)
                self.assertIn("status", m)
                self.assertIn(m["status"], ("computed", "configured", "assumed", "not_modeled", "unavailable"))
                self.assertIn("formula", m)
                self.assertIn("sources", m)
                if m["status"] == "computed":
                    self.assertTrue(len(m["sources"]) > 0, f"Computed metric {m['id']} must declare source references")


if __name__ == "__main__":
    unittest.main()
