"""tests/test_spatial.py
Comprehensive test suite for Spatial Incident Visualization,
Occupancy Deviation vs Control, Progression Phases, and Data Contracts.
"""

import json
import unittest
from pathlib import Path

from schooltwin.schema import get_valid_zones, validate_location
from schooltwin.spatial_incidents import generate_spatial_incidents
from schooltwin.config import ROOT


class TestSpatialIncidents(unittest.TestCase):
    """Test suite for spatial incidents generation and schema compliance."""

    def setUp(self):
        self.valid_zones = get_valid_zones()

    def test_zone_database_has_69_zones(self):
        """Campus zone database must contain exactly the 69 valid zones."""
        self.assertEqual(len(self.valid_zones), 69, "Campus must comprise exactly 69 zones")

    def test_location_configuration_status(self):
        """Water cooler breakdown without fixture config must return not_configured status."""
        ok, status, err, rec = validate_location(None, "water_cooler_breakdown")
        self.assertFalse(ok)
        self.assertEqual(status, "not_configured")
        self.assertIn("not configured", err)
        self.assertEqual(rec["status"], "not_configured")
        self.assertIsNone(rec["zone_id"])

        # With known zone
        ok_known, status_known, err_known, rec_known = validate_location("corridor_1", "water_cooler_breakdown")
        self.assertTrue(ok_known)
        self.assertEqual(status_known, "known")
        self.assertEqual(rec_known["zone_id"], "corridor_1")
        self.assertEqual(rec_known["floor"], 1)

    def test_spatial_incidents_generation(self):
        """Spatial incidents generator creates valid incidents.json contract."""
        import tempfile
        from schooltwin.extension_calendar import ExtensionCalendar

        class MockEngine:
            def __init__(self):
                self.calendar = ExtensionCalendar(reopening_date="2026-07-01")
                self.events = [
                    {
                        "type": "serious_student_fight",
                        "date": "2026-07-02",
                        "severity": "high",
                        "location": "playground",
                        "params": {
                            "location": "playground",
                            "student_ids": ["STU-0012", "STU-0015", "STU-0021"],
                            "minute": 600,
                            "duration_minutes": 180,
                        },
                    }
                ]
                self.alerts = [{"alert_id": "ALT-001", "date": "2026-07-02"}]
                self.decisions = [{"decision_id": "DEC-001", "date": "2026-07-02"}]
                self.redacted = False

        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir)
            (pack_dir / "days").mkdir(parents=True, exist_ok=True)
            day_file = pack_dir / "days" / "d0182.json"
            day_file.write_text(json.dumps({"i": 182, "events": []}), encoding="utf-8")

            engine = MockEngine()
            incidents = generate_spatial_incidents(
                engine=engine,
                scenario_pack_dir=pack_dir,
                control_pack_dir=None,
            )

        self.assertEqual(len(incidents), 1)
        inc = incidents[0]

        # Verify Data Contract structure from Section 6
        self.assertIn("incident_id", inc)
        self.assertEqual(inc["type"], "serious_student_fight")
        self.assertEqual(inc["severity"], "high")
        self.assertEqual(inc["origin"]["status"], "known")
        self.assertEqual(inc["origin"]["zone_id"], "playground")
        self.assertEqual(inc["origin"]["floor"], 0)

        # Progression phases ordered
        prog = inc.get("progression", [])
        self.assertTrue(len(prog) >= 3, "Progression must include multiple phases")
        minutes = [p["minute"] for p in prog]
        self.assertEqual(minutes, sorted(minutes), "Progression minutes must be strictly ordered")

        # Affected zones exclusive roles
        affected = inc.get("affected", [])
        self.assertTrue(len(affected) >= 1)
        origin_entries = [a for a in affected if a["role"] == "origin"]
        self.assertEqual(len(origin_entries), 1)
        self.assertEqual(origin_entries[0]["zone_id"], "playground")

        roles = [a["role"] for a in affected]
        for r in roles:
            self.assertIn(r, ("origin", "directly_affected", "secondary"))

        # People counts
        people = inc.get("people", {})
        self.assertIn("students", people)
        self.assertIn("teachers", people)
        self.assertIn("named_ids", people)
        self.assertIn("STU-0012", people["named_ids"])


if __name__ == "__main__":
    unittest.main()
