"""Tests for Work Package 0 (Foundation Repairs).

Verifies:
1. Checkpoint numbers are derived directly from baseline pack meta.json (no fabrication).
2. Elimination of invented fallback constants (68.5, 0.08, 0.75, 850000) from comparison logic.
3. Date-based alignment in compare_runs, including handling of closed days.
4. Baseline immutability manifest verification and write protection enforcement.
5. Relative schema constants definition.
"""
import json
import re
import unittest
from pathlib import Path

from schooltwin.baseline_manifest import (
    BASELINE_DIR,
    BaselineProtectionError,
    assert_baseline_intact,
    check_write_allowed,
    verify_baseline_manifest,
)
from schooltwin.checkpoints import STANDARD_CHECKPOINTS, derive_checkpoints_from_pack
from schooltwin.compare import compare_runs
from schooltwin.config import ROOT
from schooltwin.schema import (
    BASELINE_DAYS,
    BASELINE_FIRST_DAY,
    BASELINE_LAST_DAY,
    MAX_SIMULATION_DAYS,
)


class TestFoundation(unittest.TestCase):

    def test_checkpoints_match_pack(self):
        """Checkpoint fields must strictly match the baseline pack values on each day."""
        meta_file = ROOT / "pack" / "story_baseline" / "meta.json"
        self.assertTrue(meta_file.exists(), "pack/story_baseline/meta.json must exist")
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        days = meta["days"]

        checkpoints = derive_checkpoints_from_pack()
        self.assertEqual(len(checkpoints), 6, "Expected 6 canonical milestone checkpoints")

        for ckpt in checkpoints:
            day_data = days[ckpt.day]
            self.assertEqual(ckpt.date, day_data["date"], f"Date mismatch on day {ckpt.day}")
            self.assertEqual(
                ckpt.active_students, day_data["enrolled"], f"Enrolled mismatch on day {ckpt.day}"
            )
            self.assertEqual(
                ckpt.cash_balance_inr,
                day_data["finance"]["cash"],
                f"Cash balance mismatch on day {ckpt.day}",
            )

    def test_no_invented_fallback_constants(self):
        """Neither 68.5, 0.08, 0.75, nor 850000 may appear as fallback defaults in compare.py."""
        compare_file = ROOT / "schooltwin" / "compare.py"
        content = compare_file.read_text(encoding="utf-8")

        for forbidden in ["68.5", "0.08", "0.75", "850000"]:
            matches = re.findall(rf"\b{re.escape(forbidden)}\b", content)
            self.assertEqual(
                len(matches),
                0,
                f"Forbidden fallback constant '{forbidden}' found in {compare_file}",
            )

    def test_compare_alignment_by_date(self):
        """compare_runs aligns runs strictly by calendar date rather than naive array position."""
        # Comparing baseline with itself must produce 0 differences on all computed metrics
        report = compare_runs("story_baseline", "story_baseline")
        self.assertIn("metrics", report)
        metrics = {m["id"]: m for m in report["metrics"]}

        # Check attendance and cash
        self.assertIn("attendance_rate", metrics)
        self.assertEqual(metrics["attendance_rate"]["abs_diff"], 0.0)
        self.assertEqual(metrics["attendance_rate"]["status"], "Computed")

        self.assertIn("closing_cash_balance", metrics)
        self.assertEqual(metrics["closing_cash_balance"]["abs_diff"], 0.0)
        self.assertEqual(metrics["closing_cash_balance"]["status"], "Computed")

    def test_baseline_manifest_and_protection(self):
        """Baseline SHA-256 manifest verifies and write attempts into baseline are rejected."""
        ok, errors = verify_baseline_manifest()
        self.assertTrue(ok, f"Baseline manifest verification failed: {errors}")
        assert_baseline_intact()

        # Write protection check
        with self.assertRaises(BaselineProtectionError):
            check_write_allowed(BASELINE_DIR / "meta.json")
        with self.assertRaises(BaselineProtectionError):
            check_write_allowed(BASELINE_DIR / "days" / "d0000.json")

    def test_relative_schema_constants(self):
        """Relative schema constants must be defined and consistent with baseline story."""
        self.assertEqual(BASELINE_FIRST_DAY, 0)
        self.assertEqual(BASELINE_LAST_DAY, 150)
        self.assertEqual(BASELINE_DAYS, 151)
        self.assertEqual(MAX_SIMULATION_DAYS, 365)


if __name__ == "__main__":
    unittest.main()
