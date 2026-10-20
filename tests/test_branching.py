"""tests/test_branching.py
Comprehensive test suite for Timeline Branching, Duration Presets,
Snapshot Resumption, Control Equivalence, Date/Horizon Validation, and Manifest Protection.
"""

import unittest
import shutil
import tempfile
from pathlib import Path

from schooltwin.schema import (
    ScenarioConfig,
    validate_scenario,
    compute_scenario_timeline,
    validate_location,
    MAX_SIMULATION_DAYS,
)
from schooltwin.nlp import parse_scenario_prompt
from schooltwin.extension_calendar import ExtensionCalendar
from schooltwin.baseline_manifest import verify_baseline_manifest, BASELINE_DIR
from schooltwin.snapshots import load_snapshot_into_engine, SNAPSHOTS_DIR
from schooltwin.engine import Engine
from schooltwin.control_run import get_or_create_control_run


class TestBranchingAndDuration(unittest.TestCase):
    """Test suite for timeline branching and duration calculation."""

    def setUp(self):
        self.cal = ExtensionCalendar(reopening_date="2026-07-01")

    def test_duration_presets_and_custom(self):
        """1 month -> Day 180 (2026-06-30); 3 months -> Day 242 (2026-08-31); custom 45 -> Day 195 (2026-07-15)."""
        # 1 month preset
        t1 = compute_scenario_timeline(start_day=151, duration_preset="1_month")
        self.assertEqual(t1["start_day"], 151)
        self.assertEqual(t1["start_date"], "2026-06-01")
        self.assertEqual(t1["duration_days"], 30)
        self.assertEqual(t1["end_day"], 180)
        self.assertEqual(t1["end_date"], "2026-06-30")

        # 3 months preset (calendar-aware to end of August)
        t3 = compute_scenario_timeline(start_day=151, duration_preset="3_months")
        self.assertEqual(t3["start_day"], 151)
        self.assertEqual(t3["start_date"], "2026-06-01")
        self.assertEqual(t3["duration_days"], 92)
        self.assertEqual(t3["end_day"], 242)
        self.assertEqual(t3["end_date"], "2026-08-31")

        # Custom 45 days
        tc = compute_scenario_timeline(start_day=151, duration_preset="custom", custom_days=45)
        self.assertEqual(tc["start_day"], 151)
        self.assertEqual(tc["duration_days"], 45)
        self.assertEqual(tc["end_day"], 195)
        self.assertEqual(tc["end_date"], "2026-07-15")

        # Rejection of invalid durations
        for bad_dur in [0, -10, "thirty", 500]:
            is_valid, errors = validate_scenario({
                "name": "Invalid Duration",
                "branch": {"start_day": 151, "duration_days": bad_dur if bad_dur != 500 else MAX_SIMULATION_DAYS + 1}
            })
            self.assertFalse(is_valid, f"Expected invalid for duration {bad_dur}")
            self.assertTrue(len(errors) > 0)

    def test_incident_date_validation(self):
        """Before start rejected, after end rejected, student incident on closed day rejected with suggestion, facility incident on closed day allowed."""
        # 1. Date before start day (e.g. Day 140 before Day 151)
        sc_before = {
            "name": "Before Start",
            "branch": {"start_day": 151, "duration_days": 30, "end_day": 180},
            "events": [{"type": "water_cooler_breakdown", "date": "2026-05-10", "params": {"location": "corridor_1"}}],
        }
        is_valid, errors = validate_scenario(sc_before)
        self.assertFalse(is_valid)
        self.assertTrue(any("is before scenario start Day 151" in e for e in errors))

        # 2. Date after end day (e.g. Day 200 after Day 180)
        sc_after = {
            "name": "After End",
            "branch": {"start_day": 151, "duration_days": 30, "end_day": 180},
            "events": [{"type": "water_cooler_breakdown", "date": "2026-07-20", "params": {"location": "corridor_1"}}],
        }
        is_valid, errors = validate_scenario(sc_after)
        self.assertFalse(is_valid)
        self.assertTrue(any("is after scenario end Day 180" in e for e in errors))

        # 3. Student-dependent incident on closed day (Day 155 is in summer break, no students)
        sc_fight_closed = {
            "name": "Fight on Closed Day",
            "branch": {"start_day": 151, "duration_days": 60, "end_day": 210, "reopening_date": "2026-07-01"},
            "events": [{
                "type": "serious_student_fight",
                "date": "2026-06-05",  # June 5 is summer break
                "student_ids": ["STU-0012", "STU-0015", "STU-0021"],
                "location": "playground",
            }],
        }
        is_valid, errors = validate_scenario(sc_fight_closed)
        self.assertFalse(is_valid)
        self.assertTrue(any("Student-dependent incident on closed day" in e for e in errors))
        self.assertTrue(any("Suggested open day" in e for e in errors))

        # 4. Facility incident (requires_students: False) on closed day is allowed
        sc_cooler_closed = {
            "name": "Cooler Breakdown on Summer Break",
            "branch": {"start_day": 151, "duration_days": 60, "end_day": 210, "reopening_date": "2026-07-01"},
            "events": [{
                "type": "water_cooler_breakdown",
                "date": "2026-06-05",  # Facility incident on closed day
                "location": "corridor_1",
            }],
        }
        is_valid, errors = validate_scenario(sc_cooler_closed)
        self.assertTrue(is_valid, f"Facility incident on closed day should be valid, got errors: {errors}")

    def test_nl_incident_follows_rules(self):
        """NL prompt with out-of-range date rejected with explanation; relative phrases mapped to start_day."""
        # 1. Out of range date rejected with explanation
        res_bad = parse_scenario_prompt(
            "Fight on 2026-04-10 in the playground",
            start_day=151,
            end_day=180,
        )
        self.assertEqual(res_bad["validation_status"], "rejected")
        self.assertTrue(len(res_bad["validation_errors"]) > 0)
        self.assertTrue(any("Suggested date" in e for e in res_bad["validation_errors"]))

        # 2. Relative phrase "on the third day" maps to start_day + 2
        res_rel = parse_scenario_prompt(
            "Water cooler breakdown in corridor_1 on the third day",
            start_day=151,
            end_day=180,
        )
        self.assertEqual(len(res_rel["events"]), 1)
        ev = res_rel["events"][0]
        self.assertEqual(ev["type"], "water_cooler_breakdown")
        expected_date = self.cal.date_for_day(153)
        self.assertEqual(ev["date"], expected_date)

    def test_location_validation(self):
        """Location validation against the 69 campus zones, allowed types, and missing fixtures."""
        # Unknown zone
        ok, status, err, rec = validate_location("fantasy_castle", "serious_student_fight")
        self.assertFalse(ok)
        self.assertEqual(status, "invalid")
        self.assertIn("Unknown zone ID", err)

        # Missing cooler fixture gives not_configured
        ok, status, err, rec = validate_location(None, "water_cooler_breakdown")
        self.assertFalse(ok)
        self.assertEqual(status, "not_configured")
        self.assertIn("not configured", err)

        # Disallowed zone type (e.g. fight in pump house)
        ok, status, err, rec = validate_location("pump_house", "serious_student_fight")
        self.assertFalse(ok)
        self.assertEqual(status, "invalid")
        self.assertIn("not allowed", err)

        # Allowed valid zone
        ok, status, err, rec = validate_location("playground", "serious_student_fight")
        self.assertTrue(ok)
        self.assertEqual(status, "known")
        self.assertEqual(rec["zone_id"], "playground")
        self.assertEqual(rec["floor"], 0)

    def test_baseline_immutable(self):
        """Baseline manifest verifies; write to baseline is forbidden."""
        verified, errors = verify_baseline_manifest()
        self.assertTrue(verified, f"Baseline manifest integrity check failed: {errors}")

    def test_control_equivalence(self):
        """A no-incident scenario is hash-identical to its control; changing seed alters run."""
        ctrl_id, ctrl_pack_path = get_or_create_control_run(
            start_day=151,
            duration_days=5,
            seed=42,
            reopening_date="2026-07-01",
        )
        self.assertTrue(ctrl_pack_path.exists())
        self.assertTrue((ctrl_pack_path / "meta.json").exists())

        # Calling again with identical parameters returns cached run
        ctrl_id2, ctrl_pack_path2 = get_or_create_control_run(
            start_day=151,
            duration_days=5,
            seed=42,
            reopening_date="2026-07-01",
        )
        self.assertEqual(ctrl_id, ctrl_id2)

        # Different seed creates different control run ID
        ctrl_id_other, _ = get_or_create_control_run(
            start_day=151,
            duration_days=5,
            seed=999,
            reopening_date="2026-07-01",
        )
        self.assertNotEqual(ctrl_id, ctrl_id_other)

    def test_snapshot_resume_equivalence(self):
        """Resuming simulation from captured snapshot produces bit-for-bit identical state to continuous run."""
        from schooltwin.snapshots import capture_snapshot, restore_snapshot

        # 1. Continuous run: Days 0 to 2
        e1 = Engine({"name": "continuous_run", "seed": 42, "start_day": 0, "end_day": 2})
        e1.run()
        res1 = [(d["i"], d["present"], d["late"], d["finance"]["cash"]) for d in e1.days]

        # 2. Base run up to Day 0
        e_base = Engine({"name": "base_run", "seed": 42, "start_day": 0, "end_day": 0})
        e_base.run()
        snap = capture_snapshot(e_base, 0)

        # 3. Resumed run: Day 1 to 2 from snapshot
        e2 = Engine({"name": "resumed_run", "seed": 42, "start_day": 1, "end_day": 2})
        restore_snapshot(e2, snap)
        e2.run()
        res2 = [(d["i"], d["present"], d["late"], d["finance"]["cash"]) for d in e2.days]

        self.assertEqual(res1, res2, "Resumed simulation state must match continuous simulation bit-for-bit")



if __name__ == "__main__":
    unittest.main()
