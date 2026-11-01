"""Unit tests for 5-Pair Experiment Orchestration, Aggregated Metrics, and Report Generation."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from schooltwin.baseline_manifest import assert_baseline_intact
from schooltwin.metrics_service import (
    LABEL_COMPUTED,
    LABEL_CONFIGURED,
    LABEL_NOT_MODELED,
    LABEL_UNAVAILABLE,
    aggregate_five_pair_metrics,
    compute_comparison_payload,
)
from schooltwin.paired_simulation import run_five_pair_experiment
from schooltwin.report import generate_impact_report


class TestFivePairOrchestration(unittest.TestCase):
    def setUp(self):
        assert_baseline_intact()

    def test_aggregate_five_pair_metrics_statistics(self):
        """Tests distribution statistics across replications."""
        reps_data = [
            {
                "replication_index": 1,
                "metrics": [
                    {"id": "attendance_rate", "abs_diff": -1.2, "status": LABEL_COMPUTED},
                    {"id": "closing_cash_balance", "abs_diff": -10000, "status": LABEL_COMPUTED},
                    {"id": "academic_board_exam_percentile", "abs_diff": None, "status": LABEL_NOT_MODELED},
                ],
            },
            {
                "replication_index": 2,
                "metrics": [
                    {"id": "attendance_rate", "abs_diff": -0.8, "status": LABEL_COMPUTED},
                    {"id": "closing_cash_balance", "abs_diff": -15000, "status": LABEL_COMPUTED},
                    {"id": "academic_board_exam_percentile", "abs_diff": None, "status": LABEL_NOT_MODELED},
                ],
            },
            {
                "replication_index": 3,
                "metrics": [
                    {"id": "attendance_rate", "abs_diff": -1.5, "status": LABEL_COMPUTED},
                    {"id": "closing_cash_balance", "abs_diff": -8000, "status": LABEL_COMPUTED},
                    {"id": "academic_board_exam_percentile", "abs_diff": None, "status": LABEL_NOT_MODELED},
                ],
            },
            {
                "replication_index": 4,
                "metrics": [
                    {"id": "attendance_rate", "abs_diff": -1.0, "status": LABEL_COMPUTED},
                    {"id": "closing_cash_balance", "abs_diff": -12000, "status": LABEL_COMPUTED},
                    {"id": "academic_board_exam_percentile", "abs_diff": None, "status": LABEL_NOT_MODELED},
                ],
            },
            {
                "replication_index": 5,
                "metrics": [
                    {"id": "attendance_rate", "abs_diff": -0.5, "status": LABEL_COMPUTED},
                    {"id": "closing_cash_balance", "abs_diff": -5000, "status": LABEL_COMPUTED},
                    {"id": "academic_board_exam_percentile", "abs_diff": None, "status": LABEL_NOT_MODELED},
                ],
            },
        ]

        summary = aggregate_five_pair_metrics(reps_data)
        self.assertEqual(summary["replications_count"], 5)
        self.assertIn("attendance_rate", summary["metrics"])

        att_stats = summary["metrics"]["attendance_rate"]["stats"]
        # Values: [-1.2, -0.8, -1.5, -1.0, -0.5] -> mean: -1.0
        self.assertAlmostEqual(att_stats["mean_delta"], -1.0, places=2)
        self.assertEqual(att_stats["median_delta"], -1.0)
        self.assertEqual(att_stats["min_delta"], -1.5)
        self.assertEqual(att_stats["max_delta"], -0.5)
        self.assertEqual(att_stats["count_decrease"], 5)
        self.assertEqual(att_stats["count_increase"], 0)

        # Non-modeled metric should not fabricate stats
        board_stats = summary["metrics"]["academic_board_exam_percentile"]
        self.assertIsNone(board_stats["stats"])
        self.assertEqual(board_stats["status"], LABEL_NOT_MODELED)

    def test_run_quick_mode_replication(self):
        """Runs a 1-pair quick experiment with a 2-day horizon to verify end-to-end orchestration."""
        custom_ev = {
            "title": "Water cooler breakdown",
            "type": "water_cooler_breakdown",
            "date": "2026-06-01",
            "severity": "low",
            "target": "facility",
            "params": {"duration_hours": 2, "repair_cost_inr": 2500},
        }

        exp = run_five_pair_experiment(
            custom_event=custom_ev,
            start_day=151,
            duration_days=2,
            profile_name="calm",
            base_seed=12345,
            scenario_name="test_quick_exp",
            replications_count=1,
        )

        self.assertEqual(exp["replications_count"], 1)
        self.assertIn("primary_pair", exp)
        self.assertIn("five_pair_aggregation", exp)
        trt_run = exp["primary_pair"]["treatment_run"]
        ctrl_run = exp["primary_pair"]["control_run"]

        trt_dir = Path("pack") / trt_run
        ctrl_dir = Path("pack") / ctrl_run

        self.assertTrue((trt_dir / "meta.json").is_file())
        self.assertTrue((trt_dir / "report.json").is_file())
        self.assertTrue((trt_dir / "experiment_meta.json").is_file())

        report = json.loads((trt_dir / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["sections"]), 13)
        self.assertEqual(report["replications_count"], 1)


if __name__ == "__main__":
    unittest.main()
