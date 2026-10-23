"""tests/test_ai_assistant_writer.py
Tests for the improved AI Assistant Writer and post-baseline simulation from Day 151.
Verifies natural date extraction, term reopening references, seamless resumption from
CKPT-DAY-150-TERM-CLOSE, and dual legacy + altered history preservation.
"""

import unittest
from schooltwin.nlp import parse_scenario_prompt
from schooltwin.engine import Engine
from schooltwin.baseline_manifest import verify_baseline_manifest, BASELINE_DIR


class TestAiAssistantWriter(unittest.TestCase):
    """Test NLP parsing and Day 151 post-baseline scenario integration."""

    def test_parse_prompt_natural_dates_post_baseline(self):
        """NLP parser resolves calendar dates and term milestones starting from Day 151."""
        prompt = (
            "Starting on June 5, reduce outdoor sports budget by 20% and trigger "
            "a classroom fan failure in Class 9-A on school reopening day."
        )
        res = parse_scenario_prompt(prompt, start_day=151, duration_days=30, reopening_date="2026-06-01")
        
        self.assertEqual(res["start_day"], 151)
        self.assertEqual(res["duration_days"], 30)
        self.assertEqual(res["end_day"], 180)
        
        # Check event extraction
        events = res.get("events", [])
        self.assertTrue(len(events) >= 1)
        
        # Check that events have dates within post-baseline range
        from schooltwin.extension_calendar import ExtensionCalendar
        cal = ExtensionCalendar(reopening_date="2026-06-01")
        for ev in events:
            d_idx = cal.day_for_date(ev["date"])
            self.assertGreaterEqual(d_idx, 151)
            self.assertLessEqual(d_idx, 180)

    def test_parse_prompt_policy_overrides(self):
        """NLP parser extracts maintenance budget and bus capacity policy changes."""
        prompt = (
            "Allocate 50000 INR for summer maintenance budget and set bus backup capacity to 15. "
            "Also simulate high heatwave on July 10."
        )
        res = parse_scenario_prompt(prompt, start_day=151, duration_days=60, reopening_date="2026-06-01")
        
        policies = res.get("policy_overrides", {})
        self.assertIn("summer_maintenance_budget_inr", policies)
        self.assertEqual(policies["summer_maintenance_budget_inr"], 50000.0)
        # 15 backup buses is clamped to the max campus fleet standby of 4
        self.assertEqual(policies.get("bus_backup_capacity"), 4)

    def test_engine_post_baseline_continuity(self):
        """Engine automatically restores CKPT-DAY-150-TERM-CLOSE for start_day=151, preserving Days 0-150."""
        # Initializing Engine with start_day=151 should preload the 151 legacy days (0..150)
        engine = Engine(overview={"seed": 42, "start_day": 151, "end_day": 151})
        self.assertEqual(len(engine.days), 151)
        self.assertEqual(engine.days[0]["i"], 0)
        self.assertEqual(engine.days[150]["i"], 150)
        self.assertEqual(len(engine.agents), 1309)

        # Run 1 altered day (Day 151)
        engine.run()
        self.assertEqual(len(engine.days), 152)
        self.assertEqual(engine.days[151]["i"], 151)

    def test_baseline_immutability(self):
        """Verify story_baseline files remain frozen and match the original manifest."""
        valid, msg = verify_baseline_manifest(BASELINE_DIR)
        self.assertTrue(valid, f"Baseline integrity violated: {msg}")


if __name__ == "__main__":
    unittest.main()
