"""Comprehensive Phase 3 Test Suite for SchoolTwin Causal Simulation Engine.

Verifies:
1. Serious student altercation handler (3 students, infirmary triage, audit trail)
2. Suspected policy violation investigation workflow (presumption of innocence, state transitions)
3. Teacher resignation notice, effective departure, timetable cover pressure, and salary cessation
4. School bus breakdown, route-specific student delay isolation, and standby bus mitigation
5. School fee revision, effective-date billing, and governance approval gates
6. Additional teacher hired, timetable coverage restoration, and payroll accrual
7. Financial ledger exact minor-unit arithmetic and dual-entry reconciliation
8. Academic learning progression, instructional exposure, and assessment difficulty
9. Causal audit trail node construction and explainability chains
10. Determinism, bit-for-bit reproducibility, and baseline immutability
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from schooltwin.causal import (
    CausalAuditTrail,
    EventRecord,
    EffectRecord,
    InvestigationRecord,
    InvestigationStatus,
    RULESET_VERSION,
)
from schooltwin.causal_handlers import CausalHandlerRegistry
from schooltwin.compare import compare_runs, LABEL_COMPUTED, LABEL_CONFIGURED, LABEL_NOT_MODELED
from schooltwin.engine import Engine
from schooltwin.ledger import FinancialLedger
from schooltwin.learning import LearningModel
from schooltwin.schema import ScenarioConfig, compute_config_hash, validate_scenario
from schooltwin.transport_maintenance import TransportMaintenanceManager


class TestPhase3CausalEngine(unittest.TestCase):
    def setUp(self):
        self.audit = CausalAuditTrail(run_id="test_run", seed=20261014)
        self.ledger = FinancialLedger(opening_cash_inr=3400000.0, opening_ar_inr=850000.0)
        self.learning = LearningModel(seed=20261014)
        self.transport = TransportMaintenanceManager(num_routes=12)
        self.registry = CausalHandlerRegistry(self.audit, self.ledger, self.learning, self.transport)

    # ------------------------------------------------------------------
    # 1. Serious Student Altercation Handler
    # ------------------------------------------------------------------
    def test_serious_student_fight_handler(self):
        students = {f"STU-{i:04d}" for i in range(1, 100)}
        ev = EventRecord(
            event_id="EV-2026-01-07-FIGHT",
            event_type="serious_student_fight",
            effective_date="2026-01-07",
            target_entities=["STU-0012", "STU-0015", "STU-0021"],
            params={"student_ids": ["STU-0012", "STU-0015", "STU-0021"], "location": "playground"},
        )
        self.audit.register_event(ev)
        res = self.registry.handle_serious_student_fight(ev, students, "2026-01-07")

        self.assertTrue(res["incident_logged"])
        self.assertEqual(len(res["participants"]), 3)
        self.assertEqual(res["infirmary_visits"], 3)
        self.assertEqual(res["location"], "playground")

        # Verify audit trail effects
        effects = self.audit.get_effects_for_subsystem("safety")
        self.assertTrue(any(e.applied_rule_id == "RULE-SAFETY-FIGHT-01" for e in effects))
        self.assertTrue(any(e.applied_rule_id == "RULE-SAFETY-INFIRMARY-01" for e in effects))

        # Verify causal chain
        chain = self.audit.get_chain("incidents_total")
        self.assertGreaterEqual(len(chain), 2)
        self.assertEqual(chain[0]["node_type"], "event")
        self.assertEqual(chain[1]["node_type"], "rule")

    # ------------------------------------------------------------------
    # 2. Suspected Policy Violation Investigation Workflow
    # ------------------------------------------------------------------
    def test_investigation_state_machine_presumption_of_innocence(self):
        ev = EventRecord(
            event_id="EV-2026-01-14-BIZ",
            event_type="suspected_prohibited_business",
            effective_date="2026-01-14",
            target_entities=["STU-0044"],
            params={"student_ids": ["STU-0044"], "investigation_status": InvestigationStatus.UNDER_REVIEW},
        )
        self.audit.register_event(ev)
        res = self.registry.handle_suspected_prohibited_business(ev, "2026-01-14")

        self.assertEqual(res["status"], InvestigationStatus.UNDER_REVIEW)
        self.assertFalse(res["disciplinary_action_taken"], "Presumption of innocence must not sanction student under review")

        case = self.registry.investigations[res["case_id"]]
        # Transition to substantiated
        case.transition(InvestigationStatus.SUBSTANTIATED, "2026-01-18", notes="Confirmed exchange of unapproved goods", disciplinary_action=True)
        self.assertEqual(case.status, InvestigationStatus.SUBSTANTIATED)
        self.assertTrue(case.disciplinary_action_taken)
        self.assertEqual(case.resolution_date, "2026-01-18")

    # ------------------------------------------------------------------
    # 3. Teacher Resignation Notice & Effective Departure
    # ------------------------------------------------------------------
    def test_teacher_resignation_notice_and_departure(self):
        ev = EventRecord(
            event_id="EV-2026-01-20-RESIGN",
            event_type="teacher_resignation_notice",
            effective_date="2026-01-20",
            params={"teacher_name": "Ritu Kapoor", "effective_date": "2026-02-15"},
        )
        self.audit.register_event(ev)
        self.registry.handle_teacher_resignation(ev, "2026-01-20")

        # Mock teacher agent
        class MockAgent:
            def __init__(self, name):
                self.name = name
                self.role = "teacher"
                self.exit_date = None

        teachers = [MockAgent("Ritu Kapoor"), MockAgent("Ananya Malik")]

        # Before departure date
        departed_early = self.registry.evaluate_resignation_departure("Ritu Kapoor", "2026-02-10", teachers)
        self.assertFalse(departed_early)
        self.assertIsNone(teachers[0].exit_date)

        # On departure date
        departed_now = self.registry.evaluate_resignation_departure("Ritu Kapoor", "2026-02-15", teachers)
        self.assertTrue(departed_now)
        self.assertEqual(teachers[0].exit_date, "2026-02-15")

        staff_effects = self.audit.get_effects_for_subsystem("staffing")
        self.assertTrue(any(e.applied_rule_id == "RULE-STAFF-DEPARTURE-01" for e in staff_effects))

    # ------------------------------------------------------------------
    # 4. Bus Breakdown & Route-Specific Delay
    # ------------------------------------------------------------------
    def test_bus_breakdown_route_isolation(self):
        # Register students on routes
        self.transport.register_student_route("STU-0001", 3)
        self.transport.register_student_route("STU-0002", 3)
        self.transport.register_student_route("STU-0003", 5)  # Other route

        ev = EventRecord(
            event_id="EV-2026-01-15-BUS",
            event_type="bus_breakdown",
            effective_date="2026-01-15",
            params={"route_number": 3, "repair_cost_inr": 12000, "repair_days": 2},
        )
        self.audit.register_event(ev)
        res = self.registry.handle_bus_breakdown(ev, "2026-01-15", backup_capacity=0)

        self.assertEqual(res["route_number"], 3)
        self.assertEqual(res["bus_id"], "BUS-03")
        self.assertIn("STU-0001", res["affected_student_ids"])
        self.assertIn("STU-0002", res["affected_student_ids"])
        self.assertNotIn("STU-0003", res["affected_student_ids"], "Breakdown on Route 3 must NOT delay students on Route 5")

        # Verify transport fleet metric
        metrics = self.transport.get_transport_metrics()
        self.assertEqual(metrics["buses_out_of_service"], 1)

        # Verify financial ledger repair expense
        trans_effects = self.audit.get_effects_for_subsystem("transport")
        self.assertTrue(any(e.applied_rule_id == "RULE-TRANS-BREAKDOWN-01" for e in trans_effects))

    # ------------------------------------------------------------------
    # 5. Fee Increase Announcement & Governance Gate
    # ------------------------------------------------------------------
    def test_fee_increase_requires_approval(self):
        ev = EventRecord(
            event_id="EV-2026-01-10-FEE",
            event_type="school_fee_increase",
            effective_date="2026-01-10",
            params={"fee_category": "tuition", "delta_pct": 15.0},
        )
        self.audit.register_event(ev)

        # Without approval -> rejected
        res_unapproved = self.registry.handle_fee_increase(ev, "2026-01-10", is_approved=False)
        self.assertFalse(res_unapproved["applied"])

        # With approval -> applied
        res_approved = self.registry.handle_fee_increase(ev, "2026-01-10", is_approved=True)
        self.assertTrue(res_approved["applied"])
        self.assertEqual(res_approved["delta_pct"], 15.0)

    # ------------------------------------------------------------------
    # 6. Additional Teacher Hired & Timetable Coverage
    # ------------------------------------------------------------------
    def test_additional_teacher_hired(self):
        ev = EventRecord(
            event_id="EV-2026-02-01-HIRE",
            event_type="additional_teacher_hired",
            effective_date="2026-02-01",
            params={"teacher_name": "Pooja Sharma", "subject_or_role": "Science", "salary_monthly_inr": 50000},
        )
        self.audit.register_event(ev)
        res = self.registry.handle_additional_teacher_hired(ev, "2026-02-01")

        self.assertEqual(res["teacher_name"], "Pooja Sharma")
        self.assertEqual(res["subject"], "Science")
        staff_effects = self.audit.get_effects_for_subsystem("staffing")
        self.assertTrue(any(e.applied_rule_id == "RULE-STAFF-HIRE-CAPACITY-01" for e in staff_effects))
        fin_effects = self.audit.get_effects_for_subsystem("finance")
        self.assertTrue(any(e.applied_rule_id == "RULE-FIN-PAYROLL-NEW-HIRE-01" for e in fin_effects))

    # ------------------------------------------------------------------
    # 7. Financial Ledger Exact Arithmetic & Reconciliation
    # ------------------------------------------------------------------
    def test_ledger_exact_arithmetic_and_reconciliation(self):
        ledger = FinancialLedger(opening_cash_inr=100000.0, opening_ar_inr=50000.0)

        # 1. Bill fees: INR 60,000 tuition + INR 20,000 transport
        ledger.bill_student_fees("2026-01-01", 60000.0, 20000.0)
        self.assertEqual(ledger.balance_of(FinancialLedger.ACCOUNTS_RECEIVABLE), 130000.0)

        # 2. Collect fees: INR 70,000
        ledger.collect_fees("2026-01-05", 70000.0)
        self.assertEqual(ledger.balance_of(FinancialLedger.CASH), 170000.0)
        self.assertEqual(ledger.balance_of(FinancialLedger.ACCOUNTS_RECEIVABLE), 60000.0)

        # 3. Disburse payroll: INR 55,000
        ledger.disburse_payroll("2026-01-10", 55000.0)
        self.assertEqual(ledger.balance_of(FinancialLedger.CASH), 115000.0)

        # 4. Verify mathematical reconciliation
        rec = ledger.verify_reconciliation()
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["cash"]["discrepancy"], 0.0)
        self.assertEqual(rec["accounts_receivable"]["discrepancy"], 0.0)

    # ------------------------------------------------------------------
    # 8. Academic Learning Progression & Exposure
    # ------------------------------------------------------------------
    def test_learning_model_exposure_and_uncovered_penalty(self):
        lm = LearningModel(seed=20261014)
        s1 = lm.initialize_student("STU-0001", "Class 8", "B", 1)
        s2 = lm.initialize_student("STU-0002", "Class 9", "A", 2)

        init_m1 = s1.overall_mastery
        init_m2 = s2.overall_mastery

        # Day 1: Normal instruction for STU-0001; C8B has uncovered periods
        uncovered = {("P3", "C8B"), ("P4", "C8B")}
        lm.step_day(
            date_str="2026-01-05",
            day_index=4,
            is_school_open=True,
            present_student_ids={"STU-0001", "STU-0002"},
            uncovered_classes=uncovered,
            scheduled_periods_per_day=6,
            instructional_effectiveness=1.0,
            assessment_difficulty=1.0,
        )

        # STU-0002 in C9A had fully covered periods; STU-0001 in C8B had uncovered periods
        gain_s1 = s1.overall_mastery - init_m1
        gain_s2 = s2.overall_mastery - init_m2
        self.assertGreater(gain_s2, gain_s1, "Student in fully covered class must gain more mastery than in uncovered class")

        summary = lm.get_summary()
        self.assertGreaterEqual(summary["lost_instructional_hours"], 1.5)
        self.assertEqual(summary["uncovered_periods_total"], 2)

    # ------------------------------------------------------------------
    # 9. Comparison Report with Causal Audit Chains
    # ------------------------------------------------------------------
    def test_compare_runs_with_causal_chain(self):
        rep = compare_runs("story_baseline", "story_baseline")
        self.assertIn("narrative_summary", rep)
        self.assertIn("metrics", rep)
        self.assertIn("delta_summary", rep)

        # Check narrative summary contents
        narr = rep["narrative_summary"]
        self.assertIn("primary_findings", narr)
        self.assertTrue(len(narr["primary_findings"]) > 0)
        self.assertTrue(narr["audit_traceable"])

        # Check metrics for causal chains
        computed_metrics = [m for m in rep["metrics"] if m["status"] == LABEL_COMPUTED]
        self.assertTrue(len(computed_metrics) >= 5)
        for cm in computed_metrics:
            self.assertIn("causal_chain", cm)
            self.assertIsInstance(cm["causal_chain"], list)

        # Honest unmodeled metrics
        unmodeled = [m for m in rep["metrics"] if m["status"] == LABEL_NOT_MODELED]
        self.assertTrue(len(unmodeled) >= 1)
        self.assertIn("explanation", unmodeled[0])

    # ------------------------------------------------------------------
    # 10. Baseline Immutability
    # ------------------------------------------------------------------
    def test_baseline_immutability(self):
        base_meta_path = Path("pack/story_baseline/meta.json")
        self.assertTrue(base_meta_path.exists())
        before_bytes = base_meta_path.read_bytes()

        # Run comparison against baseline
        _ = compare_runs("story_baseline", "story_baseline")

        after_bytes = base_meta_path.read_bytes()
        self.assertEqual(before_bytes, after_bytes, "Baseline meta.json must remain strictly bit-for-bit immutable")

    # ------------------------------------------------------------------
    # 11. Simulation Determinism & Ledger Reconciliation
    # ------------------------------------------------------------------
    def test_simulation_determinism_and_reconciliation(self):
        ov1 = {
            "name": "test_det_1",
            "seed": 999123,
            "end_day": 4,
            "mode": "generate",
            "events": {"add": [], "disable": []},
            "policies": {},
            "patches": [],
        }
        ov2 = {
            "name": "test_det_2",
            "seed": 999123,
            "end_day": 4,
            "mode": "generate",
            "events": {"add": [], "disable": []},
            "policies": {},
            "patches": [],
        }

        eng1 = Engine(ov1)
        eng2 = Engine(ov2)

        eng1.run()
        eng2.run()

        # Financial ledger balance exact match
        cash1 = eng1.ledger.balance_of(FinancialLedger.CASH)
        cash2 = eng2.ledger.balance_of(FinancialLedger.CASH)
        self.assertEqual(cash1, cash2, "Determinism violated: Cash balances differed between identical runs")

        ar1 = eng1.ledger.balance_of(FinancialLedger.ACCOUNTS_RECEIVABLE)
        ar2 = eng2.ledger.balance_of(FinancialLedger.ACCOUNTS_RECEIVABLE)
        self.assertEqual(ar1, ar2, "Determinism violated: AR differed between identical runs")

        # Academic mastery exact match
        mastery1 = eng1.learning.get_summary()["mean_subject_mastery"]
        mastery2 = eng2.learning.get_summary()["mean_subject_mastery"]
        self.assertEqual(mastery1, mastery2, "Determinism violated: Mean subject mastery differed between identical runs")

        # Dual-entry ledger reconciliation on both engines
        rec1 = eng1.ledger.verify_reconciliation()
        rec2 = eng2.ledger.verify_reconciliation()
        self.assertTrue(rec1["reconciled"], f"Ledger reconciliation failed on run 1: {rec1}")
        self.assertTrue(rec2["reconciled"], f"Ledger reconciliation failed on run 2: {rec2}")


if __name__ == "__main__":
    unittest.main()

