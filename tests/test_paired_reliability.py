"""Regression tests for paired-simulation reliability repairs.

Covers the defects found auditing generated pairs on disk:
A. status_tag classification read the wrong key ('label' instead of 'status')
   so every comparison metric displayed as Unavailable.
B. Paired runs accepted student-dependent custom events on closed days
   (summer break) and produced near-invisible divergence.
C. Engine fired student events into an empty campus instead of recording a
   skip; audit execution_status stayed 'pending' forever.
D. compare_runs diluted paired metrics with identical replayed history and
   read the macro finance series instead of the reconciled ledger.
E. comparison_tag never reached pack flags, so shared/custom events could not
   be marked robustly by id.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from schooltwin.compare import compare_runs
from schooltwin.engine import Engine
from schooltwin.schema import validate_paired_custom_event


FIGHT = {
    "type": "serious_student_fight",
    "date": "2026-07-15",           # Day 195, instructional day (open)
    "params": {"student_ids": ["STU-0102", "STU-0231", "STU-0455"], "location": "canteen"},
    "severity": "high",
}


class TestValidatePairedCustomEvent(unittest.TestCase):
    def test_student_event_on_closed_day_is_rejected_with_open_day_hint(self):
        ev = dict(FIGHT, date="2026-06-20")   # summer break
        ok, errors, warnings = validate_paired_custom_event(ev, start_day=151, end_day=240)
        self.assertFalse(ok)
        self.assertTrue(any("closed day" in e and "2026-07" in e for e in errors), errors)

    def test_facility_event_on_closed_day_is_allowed(self):
        ev = {"type": "water_cooler_breakdown", "date": "2026-06-20",
              "params": {"location": "corridor_1"}, "severity": "medium"}
        ok, errors, _ = validate_paired_custom_event(ev, start_day=151, end_day=240)
        self.assertTrue(ok, errors)

    def test_zero_open_day_window_warns(self):
        ev = {"type": "water_cooler_breakdown", "date": "2026-06-15",
              "params": {"location": "corridor_1"}, "severity": "medium"}
        ok, errors, warnings = validate_paired_custom_event(ev, start_day=151, end_day=180)
        self.assertTrue(ok, errors)
        self.assertTrue(any("no open school days" in w for w in warnings), warnings)

    def test_valid_open_day_student_event_passes(self):
        ok, errors, warnings = validate_paired_custom_event(FIGHT, start_day=151, end_day=240)
        self.assertTrue(ok, errors)
        self.assertEqual(warnings, [])

    def test_resignation_accepts_teacher_alias_keys(self):
        base = {"type": "teacher_resignation", "date": "2026-07-06", "severity": "medium"}
        ok_a, errs_a, _ = validate_paired_custom_event(
            dict(base, params={"name": "Ritu Kapoor"}), start_day=151, end_day=240)
        ok_b, errs_b, _ = validate_paired_custom_event(
            dict(base, teacher="T-MEERA-SHARMA"), start_day=151, end_day=240)
        self.assertTrue(ok_a, errs_a)
        self.assertTrue(ok_b, errs_b)
        ok_c, errs_c, _ = validate_paired_custom_event(base, start_day=151, end_day=240)
        self.assertFalse(ok_c)


class TestEngineClosedDaySkip(unittest.TestCase):
    def test_student_event_on_closed_day_is_skipped_and_recorded(self):
        ov = {
            "name": "test_skip_closed", "seed": 42, "start_day": 151, "end_day": 160,
            "mode": "generate", "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
            "events": {
                "use_story_events": True, "disable": [],
                "add": [dict(FIGHT, date="2026-06-05", comparison_tag="custom_intervention")],
                "random": {"per_month": 0, "types": []},
            },
        }
        eng = Engine(ov)
        eng.run()
        day = next(d for d in eng.days if d["date"] == "2026-06-05")
        self.assertFalse(day["open"])   # 2026-06-05 is summer break
        # The fight must not execute on a closed day
        self.assertEqual([e for e in day["events"] if e["type"] == "serious_student_fight"], [])
        skipped = day.get("skipped_events") or []
        self.assertTrue(len(skipped) == 1, "expected exactly the fight to be skipped")
        self.assertEqual(skipped[0]["reason"], "school_closed_no_students")
        self.assertEqual(skipped[0]["comparison_tag"], "custom_intervention")
        # A visible flag records the skip honestly
        skip_flags = [f for f in eng.flags if f.get("skipped") and f["date"] == "2026-06-05"]
        self.assertEqual(len(skip_flags), 1)

    def test_audit_execution_status_becomes_executed(self):
        ov = {
            "name": "test_audit_exec", "seed": 42, "start_day": 191, "end_day": 196,
            "mode": "generate", "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
            "events": {
                "use_story_events": False, "disable": [],
                "add": [dict(FIGHT, date="2026-07-15")],
                "random": {"per_month": 0, "types": []},
            },
        }
        eng = Engine(ov)
        eng.run()
        audit_events = {e["event_id"]: e for e in eng.audit.to_summary()["events"]}
        fight = next(e for e in audit_events.values() if e["event_type"] == "serious_student_fight")
        self.assertEqual(fight["execution_status"], "executed")


class TestCompareWindowAndLedger(unittest.TestCase):
    def _make_pack(self, root: Path, run_id: str, cash_ledger: float, replay_att: float,
                   window_att: float, window_days, replay_days):
        days = []
        for d in replay_days:
            days.append({"i": d, "date": f"2026-01-{d+1:02d}", "open": True,
                         "attendance_rate": replay_att, "late": 5, "mood_avg": 60.0,
                         "mood_low_share": 0.03, "teachers_absent": 2, "uncovered": 0,
                         "incidents": [], "finance": {"cash": 1000.0, "inflow": 10.0,
                                                      "outflow": 5.0, "ar": 500.0}})
        for d in window_days:
            days.append({"i": d, "date": f"2026-07-{d-180:02d}", "open": True,
                         "attendance_rate": window_att, "late": 5, "mood_avg": 60.0,
                         "mood_low_share": 0.03, "teachers_absent": 2, "uncovered": 0,
                         "incidents": [], "finance": {"cash": 1000.0, "inflow": 10.0,
                                                      "outflow": 5.0, "ar": 500.0}})
        meta = {
            "days": days,
            "financial_summary": {
                "reconciled": True,
                "cash": {"closing_cash": cash_ledger, "opening_cash": 1.0,
                         "inflows": 100.0, "outflows": 50.0, "expected": cash_ledger,
                         "discrepancy": 0.0},
                "accounts_receivable": {"closing_ar": 250.0, "opening_ar": 100.0,
                                        "billed": 200.0, "collected": 50.0,
                                        "expected": 250.0, "discrepancy": 0.0},
            },
        }
        d = root / run_id
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_window_excludes_replayed_history_and_prefers_ledger(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            # Control: 92% attendance everywhere; treatment: 92% in replay, 85% in branch window
            self._make_pack(root, "ctrl", cash_ledger=1_000_000.0, replay_att=0.92,
                            window_att=0.92, window_days=range(191, 196), replay_days=range(0, 5))
            self._make_pack(root, "trt", cash_ledger=990_000.0, replay_att=0.92,
                            window_att=0.85, window_days=range(191, 196), replay_days=range(0, 5))

            # Without window: replayed history dilutes the attendance delta
            rep_full = compare_runs("ctrl", "trt", pack_dir=root)
            att_full = next(m for m in rep_full["metrics"] if m["id"] == "attendance_rate")

            # With window: only the branch days count
            rep_win = compare_runs("ctrl", "trt", window=(191, 195), pack_dir=root)
            att_win = next(m for m in rep_win["metrics"] if m["id"] == "attendance_rate")
            # signed diff (scenario - baseline): treatment 7 points lower in the window
            self.assertAlmostEqual(att_win["abs_diff"], -7.0, places=1)
            self.assertLess(att_win["abs_diff"], att_full["abs_diff"] + 6.9)  # sanity: window shows the real gap

            # Ledger closing cash is the source of truth, not the macro daily series
            cash = next(m for m in rep_win["metrics"] if m["id"] == "closing_cash_balance")
            self.assertAlmostEqual(cash["baseline"], 1_000_000.0, places=1)
            self.assertAlmostEqual(cash["scenario"], 990_000.0, places=1)
            self.assertAlmostEqual(cash["abs_diff"], -10_000.0, places=1)

            ar = next(m for m in rep_win["metrics"] if m["id"] == "accounts_receivable_closing")
            self.assertAlmostEqual(ar["scenario"], 250.0, places=1)


class TestStatusTagClassification(unittest.TestCase):
    def test_status_tag_distribution_is_honest(self):
        """The production classifier must read metric['status'], not metric['label']."""
        from schooltwin.paired_simulation import classify_comparison_metrics
        sample = {"metrics": [
            {"id": "attendance_rate", "status": "Computed"},
            {"id": "closing_cash_balance", "status": "Computed"},
            {"id": "some_configured", "status": "Configured"},
            {"id": "some_unmodeled", "status": "Not modeled"},
            {"id": "some_unavailable", "status": "Unavailable"},
        ]}
        classified = classify_comparison_metrics(sample)
        tags = {m["id"]: m["status_tag"] for m in classified}
        self.assertEqual(tags["attendance_rate"], "Computed")
        self.assertEqual(tags["some_configured"], "Configured")
        self.assertEqual(tags["some_unmodeled"], "Not modeled")
        self.assertEqual(tags["some_unavailable"], "Unavailable")

    def test_unexpected_or_missing_status_falls_back_to_unavailable(self):
        from schooltwin.paired_simulation import classify_metric_status
        self.assertEqual(classify_metric_status({"status": "computed-lowercase"}), "Unavailable")
        self.assertEqual(classify_metric_status({"label": "Computed"}), "Unavailable")
        self.assertEqual(classify_metric_status({}), "Unavailable")


class TestEventDayImpact(unittest.TestCase):
    """Small interventions round to zero at window scale (3 students / 1,309 x 60
    days); the intervention day itself must be reported so propagation is visible."""

    def test_event_day_impact_reports_day_level_deltas(self):
        from schooltwin.paired_simulation import build_event_day_impact
        ctrl = [{"date": "2026-07-15", "attendance_rate": 0.9398, "late": 12,
                 "mood_avg": 60.2, "queries": 5, "infirmary": 1, "incidents": []}]
        trt = [{"date": "2026-07-15", "attendance_rate": 0.9398, "late": 12,
                "mood_avg": 60.2, "queries": 0, "infirmary": 4,
                "incidents": [{"kind": "serious_student_fight"}]}]
        ev = {"type": "serious_student_fight", "date": "2026-07-15", "title": "Serious Student Altercation"}
        imp = build_event_day_impact(ctrl, trt, ev)
        self.assertEqual(imp["date"], "2026-07-15")
        rows = {m["id"]: m for m in imp["metrics"]}
        self.assertEqual(rows["infirmary"], {"id": "infirmary", "control": 1, "treatment": 4, "delta": 3.0})
        self.assertEqual(rows["incidents"]["delta"], 1.0)
        self.assertEqual(rows["attendance_rate"]["delta"], 0.0)

    def test_event_day_impact_handles_missing_or_unmatched_dates(self):
        from schooltwin.paired_simulation import build_event_day_impact
        self.assertIsNone(build_event_day_impact([], [], {"date": "2026-07-15"}))
        self.assertIsNone(build_event_day_impact([{"date": "2026-07-14"}],
                                                 [{"date": "2026-07-15"}],
                                                 {"date": "2026-07-15"}))
        # fields absent on both sides are omitted, not faked
        imp = build_event_day_impact([{"date": "2026-07-15"}], [{"date": "2026-07-15"}],
                                     {"date": "2026-07-15"})
        self.assertEqual(imp["metrics"], [])


class TestPairIdContentAddressing(unittest.TestCase):
    """D-regression: distinct interventions on the same date must not collide
    into one pack directory (silent overwrite of prior results)."""

    def _ev(self, delta_pct):
        return {"type": "school_fee_increase", "date": "2026-07-07",
                "params": {"delta_pct": delta_pct, "fee_category": "tuition"},
                "severity": "medium"}

    def test_different_params_produce_different_pair_ids(self):
        from schooltwin.paired_simulation import make_pair_id
        self.assertNotEqual(make_pair_id(self._ev(5), "balanced", 20261014),
                            make_pair_id(self._ev(15), "balanced", 20261014))

    def test_identical_content_is_reproducible(self):
        from schooltwin.paired_simulation import make_pair_id
        self.assertEqual(make_pair_id(self._ev(5), "balanced", 20261014),
                         make_pair_id(self._ev(5), "balanced", 20261014))

    def test_param_key_order_does_not_change_the_id(self):
        from schooltwin.paired_simulation import make_pair_id
        a = {"type": "school_fee_increase", "date": "2026-07-07",
             "params": {"delta_pct": 5, "fee_category": "tuition"}, "severity": "medium"}
        b = {"type": "school_fee_increase", "date": "2026-07-07",
             "params": {"fee_category": "tuition", "delta_pct": 5}, "severity": "medium"}
        self.assertEqual(make_pair_id(a, "balanced", 20261014),
                         make_pair_id(b, "balanced", 20261014))


class TestClosedDayBackgroundCatalog(unittest.TestCase):
    """C1 regression: the scheduler's closed-day categories must agree with the
    schema catalog. Seven facility/utility/finance types were absent from
    EVENT_CATALOG, so the engine's applicability gate treated them as
    student-dependent and silently dropped every background event in the
    all-closed June window."""

    def test_every_scheduler_type_is_catalogued_and_modeled(self):
        from schooltwin.random_scheduler import CATEGORY_CATALOG
        from schooltwin.schema import EVENT_CATALOG
        missing = [e["type"] for evs in CATEGORY_CATALOG.values() for e in evs
                   if e["type"] not in EVENT_CATALOG
                   or not EVENT_CATALOG[e["type"]].get("modeled", False)]
        self.assertEqual(missing, [])

    def test_closed_day_categories_have_explicit_student_flags(self):
        """weather_attendance_dip is deliberately student-dependent (an attendance
        dip is meaningless on a closed day), so the invariant is not "all False"
        but "no silent defaults": every closed-day-category type must carry an
        explicit flag, and the scheduler excludes student-dependent types."""
        from schooltwin.random_scheduler import CATEGORY_CATALOG
        from schooltwin.schema import EVENT_CATALOG
        implicit = [e["type"]
                    for cat in ("facility", "utilities", "finance_environment")
                    for e in CATEGORY_CATALOG[cat]
                    if "requires_students" not in EVENT_CATALOG[e["type"]]]
        self.assertEqual(implicit, [])
        self.assertTrue(EVENT_CATALOG["weather_attendance_dip"]["requires_students"])

    def test_facility_background_event_executes_on_closed_day(self):
        ov = {
            "name": "test_facility_closed", "seed": 42, "start_day": 151, "end_day": 160,
            "mode": "generate", "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
            "events": {
                "use_story_events": False, "disable": [],
                "add": [{"type": "door_lock_failure", "date": "2026-06-05", "severity": "low",
                         "params": {"location": "library"}, "id": "EV-BG-DOOR-1",
                         "is_background": True, "comparison_tag": "shared_background"}],
                "random": {"per_month": 0, "types": []},
            },
        }
        eng = Engine(ov)
        eng.run()
        day = next(d for d in eng.days if d["date"] == "2026-06-05")
        self.assertFalse(day["open"])   # 2026-06-05 is summer break
        self.assertIn("EV-BG-DOOR-1", day["events"],
                      "facility fault must execute on a closed day")
        self.assertEqual(day.get("skipped_events") or [], [])
        self.assertTrue(any(i["kind"] == "door_lock_failure" for i in day["incidents"]))
        # The repair cost genuinely reaches the reconciled ledger (exactly once)
        txns = [t for t in eng.ledger.transactions if t.source_event_id == "EV-BG-DOOR-1"]
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].debit_account, "expense:maintenance")
        self.assertEqual(txns[0].amount_inr, 2400.0)

    def test_multi_cost_event_books_every_distinct_effect(self):
        """N1 regression: water_motor_failure emits two finance effects (repair
        parts 18,500 + emergency tanker 12,000) under one event id — both must
        reach the ledger, not just the first."""
        ov = {
            "name": "test_wmotor", "seed": 42, "start_day": 151, "end_day": 160,
            "mode": "generate", "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
            "events": {
                "use_story_events": False, "disable": [],
                "add": [{"type": "water_motor_failure", "date": "2026-06-06", "severity": "high",
                         "params": {"location": "pump_house"}, "id": "EV-BG-WM-1",
                         "is_background": True}],
                "random": {"per_month": 0, "types": []},
            },
        }
        eng = Engine(ov)
        eng.run()
        txns = [t for t in eng.ledger.transactions if t.source_event_id == "EV-BG-WM-1"]
        amounts = sorted((t.debit_account, t.amount_inr) for t in txns)
        self.assertEqual(amounts, [("expense:maintenance", 18500.0),
                                   ("expense:utilities", 12000.0)],
                         "both distinct costs must be booked exactly once each")

    def test_handler_booked_event_not_double_booked_by_generic_path(self):
        """water_cooler_breakdown has a causal handler booking the param-driven
        repair cost; the generic 8,500 effect must not add a second entry."""
        ov = {
            "name": "test_wcooler_dedupe", "seed": 42, "start_day": 151, "end_day": 160,
            "mode": "generate", "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
            "events": {
                "use_story_events": False, "disable": [],
                "add": [{"type": "water_cooler_breakdown", "date": "2026-06-07", "severity": "medium",
                         "params": {"location": "corridor_1", "repair_cost_inr": 9250},
                         "id": "EV-BG-WC-1", "is_background": True}],
                "random": {"per_month": 0, "types": []},
            },
        }
        eng = Engine(ov)
        eng.run()
        txns = [t for t in eng.ledger.transactions if t.source_event_id == "EV-BG-WC-1"]
        self.assertEqual(len(txns), 1, "handler booking must win; no generic duplicate")
        self.assertEqual(txns[0].amount_inr, 9250.0)

    def test_scheduler_emits_no_student_events_on_closed_days(self):
        from schooltwin.random_scheduler import generate_paired_background_schedule
        from schooltwin.schema import EVENT_CATALOG

        class _StubStory:
            # Full 0..180 index range (the scheduler indexes story.days[day]);
            # June window (days 151-180) is fully closed summer break.
            days = ([{"date": "2026-05-31", "school_open_to_students": False,
                      "day_type": "instructional_day"}] * 151
                    + [{"date": f"2026-06-{d - 150:02d}", "school_open_to_students": False,
                        "day_type": "summer_break"} for d in range(151, 181)])

        schedule = generate_paired_background_schedule(
            story=_StubStory(), start_day=151, duration_days=30,
            profile_name="stress_test", seed=20261014,
        )
        self.assertTrue(schedule, "stress profile should emit at least one event in June")
        student_dep = [e for e in schedule
                       if EVENT_CATALOG.get(e["type"], {}).get("requires_students", True)]
        self.assertEqual(student_dep, [],
                         "no student-dependent event may be scheduled on a closed day")


if __name__ == "__main__":
    unittest.main()
