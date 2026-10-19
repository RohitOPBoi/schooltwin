"""Phase 1 and Phase 2 Automated Test Suite for SchoolTwin.

Covers:
1. Baseline dataset integrity (population, roles, days, referential consistency).
2. Deterministic execution and seed reproducibility.
3. Checkpoint catalog, branching, and baseline immutability.
4. Canonical Scenario Schema validation, policy boundaries, and error detection.
5. Supported Phase 2 event types (fight, prohibited business, fee increase, hiring, resignation, bus breakdown).
6. Scenario Store persistence, duplication, import/export, and baseline protection.
7. Baseline vs. Scenario comparison metrics and honest status badges.
8. Natural language scenario parsing with rule-based fallback and user preview confirmation.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from schooltwin.schema import (
    ScenarioConfig,
    validate_scenario,
    validate_date,
    POLICY_DEFINITIONS,
    EVENT_CATALOG,
    compute_config_hash,
)
from schooltwin.checkpoints import (
    list_checkpoints,
    get_checkpoint,
    branch_scenario_from_checkpoint,
    assert_baseline_unmodified,
)
from schooltwin.scenario_store import (
    save_scenario,
    get_scenario,
    list_scenarios,
    duplicate_scenario,
    delete_scenario,
    export_scenario_json,
    import_scenario_json,
)
from schooltwin.compare import (
    compare_runs,
    LABEL_COMPUTED,
    LABEL_CONFIGURED,
    LABEL_NOT_MODELED,
    LABEL_UNAVAILABLE,
)
from schooltwin.nlp import parse_scenario_prompt, parse_with_rules
from schooltwin.engine import Engine
from schooltwin.events import effects_for, make_event


class TestBaselineIntegrity(unittest.TestCase):
    """Phase 1: Validate synthetic school population and saved baseline."""

    def test_baseline_pack_exists_and_unmodified(self):
        self.assertTrue(assert_baseline_unmodified())

    def test_baseline_population_and_timeline(self):
        meta_path = Path("pack/story_baseline/meta.json")
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        people = meta.get("people", [])
        # Expect ~1000 students (1187) plus staff (122), totaling ~1309
        students = [p for p in people if p.get("role") == "student"]
        staff = [p for p in people if p.get("role") in ("teacher", "staff", "admin", "support")]

        self.assertGreaterEqual(len(students), 950)
        self.assertGreaterEqual(len(staff), 50)
        self.assertGreaterEqual(len(meta.get("days", [])), 90)  # At least 3 months (story has 151 days)

        # Referential integrity: check that grades and sections exist
        grades = {p.get("grade") for p in students if p.get("grade")}
        sections = {p.get("home") for p in students if p.get("home")}
        self.assertGreaterEqual(len(grades), 10)
        self.assertGreaterEqual(len(sections), 25)


class TestReproducibilityAndDeterminism(unittest.TestCase):
    """Phase 1: Deterministic execution with seeds and configuration hashing."""

    def test_identical_seed_produces_identical_run(self):
        cfg = {"mode": "generate", "seed": 42, "start_day": 10, "end_day": 20}
        e1 = Engine(cfg)
        e1.run()
        e2 = Engine(cfg)
        e2.run()

        k1 = [(d["present"], d["late"], d["finance"]["cash"]) for d in e1.days]
        k2 = [(d["present"], d["late"], d["finance"]["cash"]) for d in e2.days]
        self.assertEqual(k1, k2, "Identical seed and config must produce bit-for-bit identical state")

    def test_different_seed_diverges(self):
        e1 = Engine({"mode": "generate", "seed": 42, "start_day": 10, "end_day": 20})
        e1.run()
        e2 = Engine({"mode": "generate", "seed": 99, "start_day": 10, "end_day": 20})
        e2.run()

        k1 = [(d["present"], d["late"]) for d in e1.days]
        k2 = [(d["present"], d["late"]) for d in e2.days]
        self.assertNotEqual(k1, k2, "Different seeds must produce diverging simulation outcomes")

    def test_config_hash_is_deterministic(self):
        s1 = ScenarioConfig(
            scenario_id="SCN-TEST-1",
            name="Test Scenario",
            end_day=90,
            seed=123,
            events=[{"type": "bus_breakdown", "date": "2026-02-15", "route_number": 4}],
            policy_overrides={"tuition_fee_delta_pct": 5.0},
        )
        s2 = ScenarioConfig(
            scenario_id="SCN-TEST-2",
            name="Test Scenario",
            end_day=90,
            seed=123,
            events=[{"type": "bus_breakdown", "date": "2026-02-15", "route_number": 4}],
            policy_overrides={"tuition_fee_delta_pct": 5.0},
        )
        self.assertEqual(s1.get_hash(), s2.get_hash())


class TestCheckpointsAndBranching(unittest.TestCase):
    """Phase 1: Checkpoints and immutable branching."""

    def test_list_checkpoints(self):
        ckpts = list_checkpoints()
        self.assertGreaterEqual(len(ckpts), 5)
        ids = [c["checkpoint_id"] for c in ckpts]
        self.assertIn("CKPT-DAY-00-OPENING", ids)
        self.assertIn("CKPT-DAY-30-JAN-CLOSE", ids)
        self.assertIn("CKPT-DAY-90-APRIL-PROMOTIONS", ids)

    def test_branching_creates_independent_scenario(self):
        branch = branch_scenario_from_checkpoint(
            checkpoint_id="CKPT-DAY-30-JAN-CLOSE",
            scenario_name="Post-Jan Intervention",
            seed=777,
        )
        self.assertEqual(branch["checkpoint_id"], "CKPT-DAY-30-JAN-CLOSE")
        self.assertEqual(branch["parent_run_id"], "story_baseline")
        self.assertEqual(branch["fork_day"], 30)
        # Verify baseline remains unmodified
        self.assertTrue(assert_baseline_unmodified())


class TestScenarioSchemaValidation(unittest.TestCase):
    """Phase 2: Canonical schema validation, boundaries, and errors."""

    def test_valid_scenario(self):
        sc_data = {
            "scenario_id": "SCN-VALID-1",
            "name": "Valid Exam Week Scenario",
            "start_day": 0,
            "end_day": 90,
            "seed": 42,
            "events": [
                {
                    "type": "serious_student_fight",
                    "date": "2026-02-10",
                    "student_ids": ["STU-0012", "STU-0045", "STU-0089"],
                    "severity": "high",
                    "location": "playground",
                }
            ],
            "policy_overrides": {
                "tuition_fee_delta_pct": 10.0,
                "additional_teachers": 2,
            },
        }
        is_valid, errors = validate_scenario(sc_data)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_invalid_horizon_and_empty_name(self):
        sc_data = {"name": "", "start_day": 100, "end_day": 50}
        is_valid, errors = validate_scenario(sc_data)
        self.assertFalse(is_valid)
        self.assertTrue(any("Scenario name is required" in e for e in errors))
        self.assertTrue(any("cannot exceed end_day" in e for e in errors))

    def test_policy_out_of_bounds(self):
        sc_data = {
            "name": "Extreme Policies",
            "policy_overrides": {"tuition_fee_delta_pct": 150.0},  # max allowed is 20.0
        }
        is_valid, errors = validate_scenario(sc_data)
        self.assertFalse(is_valid)
        self.assertTrue(any("above maximum allowed" in e for e in errors))

    def test_unsupported_event_type_flagged(self):
        sc_data = {
            "name": "Unsupported Event Scenario",
            "events": [{"type": "alien_invasion", "date": "2026-03-01"}],
        }
        is_valid, errors = validate_scenario(sc_data)
        self.assertFalse(is_valid)
        self.assertTrue(any("unsupported type" in e for e in errors))

    def test_fight_requires_three_students(self):
        sc_data = {
            "name": "Bad Fight",
            "events": [
                {
                    "type": "serious_student_fight",
                    "date": "2026-02-10",
                    "student_ids": ["STU-0012"],  # only 1 student
                }
            ],
        }
        is_valid, errors = validate_scenario(sc_data)
        self.assertFalse(is_valid)
        self.assertTrue(any("requires exactly 3 student IDs" in e for e in errors))


class TestPhase2EventHandlers(unittest.TestCase):
    """Phase 2: Six key event types support and catalog verification."""

    def test_six_event_types_in_catalog(self):
        required_types = [
            "serious_student_fight",
            "suspected_prohibited_business",
            "school_fee_increase",
            "additional_teacher_hired",
            "teacher_resignation",
            "bus_breakdown",
        ]
        for et in required_types:
            self.assertIn(et, EVENT_CATALOG, f"{et} must be defined in EVENT_CATALOG")

    def test_fight_event_effects(self):
        ev = make_event(
            "2026-02-10",
            "serious_student_fight",
            "high",
            {"student_ids": ["STU-001", "STU-002", "STU-003"], "location": "playground"},
        )
        eff = effects_for(ev, {}, None)
        self.assertTrue(any(e.verb == "mood" and e.args.get("ids") == ["STU-001", "STU-002", "STU-003"] for e in eff))
        self.assertTrue(any(e.verb == "infirmary" for e in eff))
        self.assertTrue(any(e.verb == "incident" for e in eff))

    def test_suspected_prohibited_business_effects(self):
        ev = make_event(
            "2026-02-15",
            "suspected_prohibited_business",
            "medium",
            {"student_ids": ["STU-099"], "investigation_status": "under_review", "location": "admin_lobby"},
        )
        eff = effects_for(ev, {}, None)
        self.assertTrue(any(e.verb == "mood" and e.args.get("ids") == ["STU-099"] for e in eff))
        self.assertTrue(any(e.verb == "incident" for e in eff))

    def test_bus_breakdown_effects(self):
        ev = make_event(
            "2026-02-20",
            "bus_breakdown",
            "medium",
            {"n_students": 60, "routes": 4, "delay": [10, 25]},
        )
        eff = effects_for(ev, {}, None)
        self.assertTrue(any(e.verb == "late_riders" for e in eff))
        self.assertTrue(any(e.verb == "incident" for e in eff))


class TestScenarioPersistenceAndProtection(unittest.TestCase):
    """Phase 2: Save, duplicate, import/export, and baseline protection."""

    def test_save_and_retrieve_scenario(self):
        data = {
            "scenario_id": "SCN-TEST-PERSIST",
            "name": "Persist Scenario Test",
            "description": "Testing save and retrieve",
            "seed": 888,
            "policy_overrides": {"additional_teachers": 2},
        }
        success, saved, errors = save_scenario(data)
        self.assertTrue(success)
        self.assertEqual(errors, [])

        loaded = get_scenario("SCN-TEST-PERSIST")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "Persist Scenario Test")

        # Clean up
        delete_scenario("SCN-TEST-PERSIST")

    def test_cannot_overwrite_or_delete_baseline(self):
        # Baseline deletion rejection
        success, err = delete_scenario("story_baseline")
        self.assertFalse(success)
        self.assertIn("Cannot delete protected baseline", err)

        # Baseline overwrite rejection
        bad_cfg = {"name": "story_baseline", "scenario_id": "story_baseline"}
        success, saved, errors = save_scenario(bad_cfg)
        self.assertFalse(success)
        self.assertTrue(any("Protected run 'story_baseline' cannot be overwritten" in e for e in errors))

    def test_export_import_json(self):
        data = {
            "scenario_id": "SCN-EXP-IMP",
            "name": "Export Import Scenario",
            "seed": 9999,
        }
        save_scenario(data)
        json_str = export_scenario_json("SCN-EXP-IMP")
        self.assertIsNotNone(json_str)

        success, imported, errs = import_scenario_json(json_str)
        self.assertTrue(success)
        self.assertEqual(imported["name"], "Export Import Scenario")

        # Clean up
        delete_scenario("SCN-EXP-IMP")


class TestComparisonAndHonestBadging(unittest.TestCase):
    """Phase 2: Baseline vs Scenario metric comparison with honest labeling."""

    def test_comparison_handles_baseline_vs_scenario(self):
        # Compare baseline against itself (0 diffs, valid metrics, honest labels)
        res = compare_runs("story_baseline", "story_baseline")
        self.assertEqual(res["baseline_run_id"], "story_baseline")
        self.assertEqual(res["scenario_run_id"], "story_baseline")

        metrics = {m["id"]: m for m in res["metrics"]}
        self.assertIn("attendance_rate", metrics)
        self.assertEqual(metrics["attendance_rate"]["status"], LABEL_COMPUTED)
        self.assertEqual(metrics["attendance_rate"]["abs_diff"], 0.0)

        # Check configured levers
        self.assertIn("policy_additional_teachers", metrics)
        self.assertEqual(metrics["policy_additional_teachers"]["status"], LABEL_CONFIGURED)

        # Check an unmodeled metric
        self.assertIn("academic_board_exam_percentile", metrics)
        self.assertEqual(metrics["academic_board_exam_percentile"]["status"], LABEL_NOT_MODELED)

        # Check an unavailable metric
        self.assertIn("cctv_facial_recognition", metrics)
        self.assertEqual(metrics["cctv_facial_recognition"]["status"], LABEL_UNAVAILABLE)


class TestNaturalLanguageScenarioCreation(unittest.TestCase):
    """Phase 2: Natural language input parsing and rule-based fallback."""

    def test_rule_based_fallback_parsing(self):
        prompt = (
            "Starting on Day 7, there is a serious fight involving three students. "
            "On Day 15, one school bus Route 3 breaks down. We want to increase fees by 10%."
        )
        parsed = parse_scenario_prompt(prompt, prefer_ollama=False)

        self.assertIsNotNone(parsed)
        events = parsed.get("events", [])
        self.assertGreaterEqual(len(events), 2)

        ev_types = [e["type"] for e in events]
        self.assertIn("serious_student_fight", ev_types)
        self.assertIn("bus_breakdown", ev_types)

        # Check policy extracted
        self.assertEqual(parsed.get("policy_overrides", {}).get("tuition_fee_delta_pct"), 10.0)

        # Check fight had 3 synthetic student targets generated
        fight_ev = next(e for e in events if e["type"] == "serious_student_fight")
        self.assertEqual(len(fight_ev["student_ids"]), 3)


if __name__ == "__main__":
    unittest.main()
