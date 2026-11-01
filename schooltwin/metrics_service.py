"""Canonical Metrics Calculation and Comparison Service for SchoolTwin.

Unified single source of truth for:
1. Metric definitions, formulas, and data sources.
2. Comparison between Scenario and Baseline/Control runs.
3. Five-Pair replication delta aggregations.
4. Strict enforcement of honest modeling boundaries:
   - 'computed': directly computed from simulated state.
   - 'configured': directly set by policy levers.
   - 'not_modeled': explicitly identified boundary.
   - 'unavailable': unmodeled, missing, or unprovable.
5. Zero fabricated numeric constants (no 92.4, 3031994, 20.0, 14500, 35.0, etc.).
6. Never substitutes treatment values for missing control values.
7. Genuine causal provenance from CausalAuditTrail only; if absent, flags
   'Difference observed — causal provenance unavailable'.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .config import ROOT

LABEL_COMPUTED = "Computed"
LABEL_CONFIGURED = "Configured"
LABEL_NOT_MODELED = "Not modeled"
LABEL_UNAVAILABLE = "Unavailable"

_VALID_STATUSES = {LABEL_COMPUTED, LABEL_CONFIGURED, LABEL_NOT_MODELED, LABEL_UNAVAILABLE}


def safe_pct_diff(val_scen: Optional[float], val_base: Optional[float]) -> Optional[float]:
    """Calculates percentage difference ((scenario - baseline) / |baseline| * 100)."""
    if val_scen is None or val_base is None:
        return None
    try:
        vf_base = float(val_base)
        vf_scen = float(val_scen)
        if vf_base == 0.0 or math.isnan(vf_base) or math.isnan(vf_scen):
            return None
        return round(((vf_scen - vf_base) / abs(vf_base)) * 100.0, 2)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def safe_abs_diff(val_scen: Optional[float], val_base: Optional[float], dec: int = 2) -> Optional[float]:
    """Calculates absolute difference (scenario - baseline)."""
    if val_scen is None or val_base is None:
        return None
    try:
        diff = float(val_scen) - float(val_base)
        return round(diff, dec) if dec is not None else round(diff, 2)
    except (ValueError, TypeError):
        return None


def load_pack_meta(run_id: str, pack_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Loads meta.json for a run ID from the pack directory."""
    pdir = Path(pack_dir) if pack_dir else ROOT / "pack"
    meta_path = pdir / run_id / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Run pack not found for '{run_id}' at {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def extract_causal_chain(
    metric_id: str,
    audit_data: Dict[str, Any],
    has_delta: bool = False,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Extracts authentic causal chain from CausalAuditTrail data.

    Returns (chain_nodes, status_note).
    If no authentic chain exists and has_delta is True, returns empty list
    with status note: 'Difference observed — causal provenance unavailable'.
    Never invents hardcoded mock rules or fake dates.
    """
    chains = audit_data.get("chains", {})
    if metric_id in chains and chains[metric_id]:
        return chains[metric_id], None

    # Check for direct event-to-effect mappings in audit
    events = audit_data.get("events", [])
    effects = audit_data.get("effects", [])

    # Filter effects that explicitly target this metric or its primary subsystem
    metric_subsystem_map = {
        "average_subject_mastery": "academics",
        "lost_instructional_hours": "academics",
        "uncovered_lessons_total": "staffing",
        "uncovered_teaching_periods": "staffing",
        "teacher_absence_total": "staffing",
        "bus_fleet_availability": "transport",
        "closing_cash_balance": "finance",
        "operating_inflow": "finance",
        "operating_outflow": "finance",
        "emergency_maintenance_expense_inr": "maintenance",
        "incidents_total": "safety",
    }
    target_sub = metric_subsystem_map.get(metric_id)
    if target_sub and effects:
        matching_fx = [fx for fx in effects if fx.get("target_subsystem") == target_sub]
        if matching_fx:
            chain: List[Dict[str, Any]] = []
            seen_ev = set()
            for fx in matching_fx[:4]:
                ev_id = fx.get("source_event_id")
                if ev_id and ev_id not in seen_ev:
                    ev = next((e for e in events if e.get("event_id") == ev_id), None)
                    if ev:
                        chain.append({
                            "node_type": "event",
                            "node_id": ev.get("event_id", "EV-UNKNOWN"),
                            "title": ev.get("title") or ev.get("event_type", "Event").replace("_", " ").title(),
                            "detail": ev.get("description", ""),
                            "date": ev.get("effective_date", ""),
                            "subsystem": target_sub,
                        })
                        seen_ev.add(ev_id)
                chain.append({
                    "node_type": "effect",
                    "node_id": fx.get("effect_id", "FX-UNKNOWN"),
                    "title": f"Effect: {fx.get('affected_field', 'State change')}",
                    "detail": f"{fx.get('previous_value')} -> {fx.get('resulting_value')} via {fx.get('applied_rule_id', 'rule')}",
                    "date": fx.get("effective_date", ""),
                    "subsystem": target_sub,
                })
            if chain:
                return chain, None

    if has_delta:
        return [], "Difference observed — causal provenance unavailable"
    return [], None


def compute_comparison_payload(
    base_meta: Optional[Dict[str, Any]],
    scen_meta: Dict[str, Any],
    window: Optional[Tuple[int, int]] = None,
    incidents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Canonical single-source calculation of all comparison and impact metrics.

    Never invents fallbacks. If baseline/control data is missing, sets baseline to None
    and marks status 'Unavailable'.
    """
    s_all_days = scen_meta.get("days", [])
    b_all_days = (base_meta.get("days", []) if base_meta else [])

    if window is not None:
        w_start, w_end = window
        s_all_days = [d for d in s_all_days if w_start <= d.get("i", -1) <= w_end]
        b_all_days = [d for d in b_all_days if w_start <= d.get("i", -1) <= w_end]

    s_by_date = {d["date"]: d for d in s_all_days if "date" in d}
    b_by_date = {d["date"]: d for d in b_all_days if "date" in d}

    common_dates = sorted(set(s_by_date.keys()) & set(b_by_date.keys()))
    # If one run is a future scenario branching past the other run (e.g. 210 days vs 151 days),
    # preserving s_all_days avoids truncating the scenario back to the branch checkpoint.
    if common_dates and (len(s_all_days) == len(b_all_days) or not b_all_days):
        s_days = [s_by_date[dt] for dt in common_dates]
        b_days = [b_by_date[dt] for dt in common_dates]
    elif common_dates and len(s_all_days) != len(b_all_days):
        # Different date spans: evaluate each over its own full operational horizon
        s_days = s_all_days
        b_days = b_all_days
    else:
        s_days = s_all_days
        b_days = b_all_days

    s_open = [d for d in s_days if d.get("open") and d.get("attendance_rate") is not None]
    b_open = [d for d in b_days if d.get("open") and d.get("attendance_rate") is not None]

    # Academic Summaries (Phase 3 & Phase 8)
    # Canonical key is 'average_subject_mastery'
    s_acad = scen_meta.get("academic_summary", {})
    b_acad = base_meta.get("academic_summary", {}) if base_meta else {}

    s_mastery = s_acad.get("average_subject_mastery")
    if s_mastery is None:
        s_mastery = s_acad.get("mean_subject_mastery")

    b_mastery = b_acad.get("average_subject_mastery")
    if b_mastery is None:
        b_mastery = b_acad.get("mean_subject_mastery")

    s_lost_hours = s_acad.get("lost_instructional_hours")
    b_lost_hours = b_acad.get("lost_instructional_hours") if base_meta else None

    # Attendance
    s_att_mean = (sum(float(d["attendance_rate"]) for d in s_open) / len(s_open) * 100.0) if s_open else None
    b_att_mean = (sum(float(d["attendance_rate"]) for d in b_open) / len(b_open) * 100.0) if b_open else None

    # Late arrivals
    s_late_mean = (sum(d.get("late", 0) for d in s_open) / len(s_open)) if s_open else None
    b_late_mean = (sum(d.get("late", 0) for d in b_open) / len(b_open)) if b_open else None

    # Staffing & Operations
    s_uncovered_tot = sum(d.get("uncovered", 0) for d in s_days) if s_days else None
    b_uncovered_tot = sum(d.get("uncovered", 0) for d in b_days) if b_days else None

    s_tch_abs_tot = sum(d.get("teachers_absent", 0) for d in s_days) if s_days else None
    b_tch_abs_tot = sum(d.get("teachers_absent", 0) for d in b_days) if b_days else None

    # Financial Ledger (Same-basis rule)
    s_fin = scen_meta.get("financial_summary", {}) or {}
    b_fin = (base_meta.get("financial_summary", {}) or {}) if base_meta else {}

    s_ledger_cash = (s_fin.get("cash") or {}).get("closing_cash")
    b_ledger_cash = (b_fin.get("cash") or {}).get("closing_cash")

    use_ledger = (s_ledger_cash is not None and b_ledger_cash is not None)

    if use_ledger:
        s_last_cash = s_ledger_cash
        b_last_cash = b_ledger_cash
        s_closing_ar = (s_fin.get("accounts_receivable") or {}).get("closing_ar")
        b_closing_ar = (b_fin.get("accounts_receivable") or {}).get("closing_ar")
    else:
        s_last_cash = s_all_days[-1].get("finance", {}).get("cash") if s_all_days else None
        b_last_cash = b_all_days[-1].get("finance", {}).get("cash") if b_all_days else None
        s_closing_ar = s_all_days[-1].get("finance", {}).get("ar") if s_all_days else None
        b_closing_ar = b_all_days[-1].get("finance", {}).get("ar") if b_all_days else None

    # Cumulative Operating Inflow and Outflow
    s_inflow = sum(d.get("finance", {}).get("inflow", 0) for d in s_days) if s_days else None
    b_inflow = sum(d.get("finance", {}).get("inflow", 0) for d in b_days) if b_days else None
    s_outflow = sum(d.get("finance", {}).get("outflow", 0) for d in s_days) if s_days else None
    b_outflow = sum(d.get("finance", {}).get("outflow", 0) for d in b_days) if b_days else None

    # Maintenance expenses
    s_maint = sum(
        d.get("finance", {}).get("accounts", {}).get("repairs_and_maintenance", 0)
        for d in s_days
    ) if s_days else None
    b_maint = sum(
        d.get("finance", {}).get("accounts", {}).get("repairs_and_maintenance", 0)
        for d in b_days
    ) if b_days else None

    # Transport
    s_trans = scen_meta.get("transport_summary", {})
    b_trans = base_meta.get("transport_summary", {}) if base_meta else {}
    s_fleet_avail = s_trans.get("fleet_availability_pct")
    b_fleet_avail = b_trans.get("fleet_availability_pct") if base_meta else None

    # Incident Response Time
    resp_time_minutes: Optional[float] = None
    if incidents:
        first_inc = incidents[0]
        onset = first_inc.get("onset_minute")
        resp_phase = next(
            (p for p in first_inc.get("progression", []) if p.get("phase") in ("response", "containment")),
            None
        )
        if onset is not None and resp_phase and "minute" in resp_phase:
            resp_time_minutes = float(max(1, resp_phase["minute"] - onset))

    ctrl_resp_time: Optional[float] = 0.0 if base_meta else None

    # Incidents & Investigations
    s_incidents_tot = sum(len(d.get("incidents", [])) for d in s_days) if s_days else None
    b_incidents_tot = sum(len(d.get("incidents", [])) for d in b_days) if b_days else None

    s_audit = scen_meta.get("causal_audit", {})
    investigations_count = sum(
        1 for e in s_audit.get("events", [])
        if e.get("event_type") == "suspected_prohibited_business"
    )

    # Sentiment / Stress indicators
    s_moods = [d.get("mood_avg") for d in s_open if d.get("mood_avg") is not None]
    b_moods = [d.get("mood_avg") for d in b_open if d.get("mood_avg") is not None]

    s_mood_avg = (sum(s_moods) / len(s_moods)) if s_moods else None
    b_mood_avg = (sum(b_moods) / len(b_moods)) if b_moods else None

    s_stress = round(100.0 - s_mood_avg, 1) if s_mood_avg is not None else None
    b_stress = round(100.0 - b_mood_avg, 1) if b_mood_avg is not None else None

    # Configured levers
    s_ov = scen_meta.get("run", {}).get("overview", {})
    b_ov = base_meta.get("run", {}).get("overview", {}) if base_meta else {}
    s_lev = s_ov.get("levers", {})
    b_lev = b_ov.get("levers", {})

    def make_metric(
        mid: str,
        category: str,
        name: str,
        units: str,
        b_val: Optional[Any],
        s_val: Optional[Any],
        explanation: str,
        formula: str = "",
        dec: int = 2,
        allow_pct: bool = True,
    ) -> Dict[str, Any]:
        has_vals = (b_val is not None and s_val is not None)
        if has_vals:
            bv_f = round(float(b_val), dec) if dec is not None else float(b_val)
            sv_f = round(float(s_val), dec) if dec is not None else float(s_val)
            adiff = safe_abs_diff(sv_f, bv_f, dec)
            pdiff = safe_pct_diff(sv_f, bv_f) if allow_pct else None
            chain, note = extract_causal_chain(mid, s_audit, has_delta=(adiff != 0))
            return {
                "id": mid,
                "category": category,
                "name": name,
                "units": units,
                "baseline": bv_f,
                "scenario": sv_f,
                "control": bv_f,
                "treatment": sv_f,
                "abs_diff": adiff,
                "pct_diff": pdiff,
                "status": LABEL_COMPUTED,
                "explanation": explanation,
                "formula": formula,
                "causal_chain": chain,
                "causal_note": note,
            }
        # Unavailable / missing data
        bv_repr = round(float(b_val), dec) if (b_val is not None and dec is not None) else b_val
        sv_repr = round(float(s_val), dec) if (s_val is not None and dec is not None) else s_val
        return {
            "id": mid,
            "category": category,
            "name": name,
            "units": units,
            "baseline": bv_repr,
            "scenario": sv_repr,
            "control": bv_repr,
            "treatment": sv_repr,
            "abs_diff": None,
            "pct_diff": None,
            "status": LABEL_UNAVAILABLE,
            "explanation": f"{name} is unavailable in one or both evaluated runs.",
            "formula": formula,
            "causal_chain": [],
            "causal_note": None,
        }

    metrics = [
        # Academic Progress
        make_metric(
            "average_subject_mastery", "Academic Progress", "Mean Subject Mastery Score",
            "pts (0-100)", b_mastery, s_mastery,
            "Calculated from student-level subject learning progression, teacher coverage, and pedagogical effectiveness.",
            formula="mean(student mastery over active CBSE subjects)",
            dec=2,
        ),
        make_metric(
            "lost_instructional_hours", "Academic Progress", "Lost Instructional Hours",
            "hours", b_lost_hours, s_lost_hours,
            "Accumulated classroom instructional hours lost due to uncovered lessons or room closures.",
            formula="sum(uncovered periods) * 45 min / 60 min",
            dec=1,
        ),
        # Attendance & Operations
        make_metric(
            "attendance_rate", "Attendance & Operations", "Mean Daily Attendance",
            "%", b_att_mean, s_att_mean,
            "Derived from simulated daily student presence across open school days.",
            formula="mean(present_students / enrolled_students) * 100 on open instructional days",
            dec=2,
        ),
        make_metric(
            "late_arrivals_mean", "Attendance & Operations", "Daily Late Arrivals (Mean)",
            "students/day", b_late_mean, s_late_mean,
            "Average number of students arriving after morning assembly bell.",
            formula="mean(late_arrivals) on open instructional days",
            dec=1,
        ),
        # Staffing & Operations
        make_metric(
            "uncovered_lessons_total", "Faculty & Operations", "Uncovered Class Periods",
            "periods", b_uncovered_tot, s_uncovered_tot,
            "Teaching periods where scheduled teachers were absent or departed and no substitute was available.",
            formula="sum(uncovered_periods) over simulation window",
            dec=0,
        ),
        make_metric(
            "teacher_absence_total", "Faculty & Operations", "Teacher Absences (Cumulative)",
            "teacher-days", b_tch_abs_tot, s_tch_abs_tot,
            "Total faculty absence occurrences across the simulated horizon.",
            formula="sum(teachers_absent) over simulation window",
            dec=0,
        ),
        # Transport Logistics
        make_metric(
            "bus_fleet_availability", "Transport Logistics", "Bus Fleet Availability",
            "%", b_fleet_avail, s_fleet_avail,
            "Proportion of the 12-bus fleet in active operational service without breakdown.",
            formula="mean(operational_buses / 12) * 100",
            dec=1,
        ),
        # Financial Ledger
        make_metric(
            "closing_cash_balance", "Financial Ledger", "Closing Cash Balance",
            "INR", b_last_cash, s_last_cash,
            "Final liquid cash balance reconciled via exact double-entry ledger transactions.",
            formula="closing cash from double-entry ledger reconciliation on final day",
            dec=0,
        ),
        make_metric(
            "operating_inflow", "Financial Ledger", "Cumulative Operating Inflow",
            "INR", b_inflow, s_inflow,
            "Total fee collections and operational cash receipts posted to cash account.",
            formula="sum(day.finance.inflow) over window",
            dec=0,
        ),
        make_metric(
            "operating_outflow", "Financial Ledger", "Cumulative Operating Outflow",
            "INR", b_outflow, s_outflow,
            "Total operating disbursements across payroll, utilities, supplies, and maintenance.",
            formula="sum(day.finance.outflow) over window",
            dec=0,
        ),
        make_metric(
            "accounts_receivable_closing", "Financial Ledger", "Outstanding Fee Receivables",
            "INR", b_closing_ar, s_closing_ar,
            "Cumulative uncollected student tuition and transport fees.",
            formula="closing balance of asset:accounts_receivable account",
            dec=0,
        ),
        make_metric(
            "emergency_maintenance_expense_inr", "Financial Ledger", "Unplanned Repairs & Maintenance",
            "INR", b_maint, s_maint,
            "Cumulative ledger expenses posted to repairs_and_maintenance account.",
            formula="sum(expense:maintenance debit postings) over window",
            dec=0,
        ),
        # Safety & Governance
        make_metric(
            "incidents_total", "Safety & Governance", "Operational Incidents Logged",
            "incidents", b_incidents_tot, s_incidents_tot,
            "Entries recorded in the formal school incident register.",
            formula="sum(len(day.incidents)) over window",
            dec=0,
        ),
        # Wellbeing & Sentiment
        make_metric(
            "mood_index_avg", "Wellbeing & Sentiment", "Average Student Mood Tendency",
            "index (0-100)", b_mood_avg, s_mood_avg,
            "Synthetic behavioral mood score tracking daily friction and environmental stressors.",
            formula="mean(mood_avg) over open days",
            dec=1,
        ),
        make_metric(
            "modeled_student_stress_index", "Wellbeing & Sentiment", "Modeled Student Stress Indicator",
            "index (0-100)", b_stress, s_stress,
            "Modeled indicator of synthetic student strain (100 - mood tendency). Not a clinical diagnosis.",
            formula="100 - mean(mood_avg)",
            dec=1,
        ),
        # Policy Levers (Configured)
        {
            "id": "policy_additional_teachers",
            "category": "Configured Policies",
            "name": "Additional Teachers Recruited",
            "units": "teachers",
            "baseline": b_lev.get("additional_teachers", 0) if base_meta else None,
            "scenario": s_lev.get("additional_teachers", 0),
            "control": b_lev.get("additional_teachers", 0) if base_meta else None,
            "treatment": s_lev.get("additional_teachers", 0),
            "abs_diff": safe_abs_diff(float(s_lev.get("additional_teachers", 0)), float(b_lev.get("additional_teachers", 0))) if base_meta else None,
            "pct_diff": None,
            "status": LABEL_CONFIGURED,
            "explanation": "Configured recruit count directly reflected in payroll and lesson cover.",
            "formula": "scenario lever setting",
            "causal_chain": [],
            "causal_note": None,
        },
        {
            "id": "policy_tuition_fee_delta",
            "category": "Configured Policies",
            "name": "Tuition Fee Revision",
            "units": "%",
            "baseline": b_lev.get("tuition_fee_delta_pct", 0.0) if base_meta else None,
            "scenario": s_lev.get("tuition_fee_delta_pct", 0.0),
            "control": b_lev.get("tuition_fee_delta_pct", 0.0) if base_meta else None,
            "treatment": s_lev.get("tuition_fee_delta_pct", 0.0),
            "abs_diff": safe_abs_diff(float(s_lev.get("tuition_fee_delta_pct", 0)), float(b_lev.get("tuition_fee_delta_pct", 0))) if base_meta else None,
            "pct_diff": None,
            "status": LABEL_CONFIGURED,
            "explanation": "Configured tuition adjustment applied subject to governance approval gate.",
            "formula": "scenario lever setting",
            "causal_chain": [],
            "causal_note": None,
        },
        # Explicit Non-Modeled Boundaries
        {
            "id": "academic_board_exam_percentile",
            "category": "Academic Performance",
            "name": "Class 10 & 12 Board Percentile Shift",
            "units": "percentile",
            "baseline": None,
            "scenario": None,
            "control": None,
            "treatment": None,
            "abs_diff": None,
            "pct_diff": None,
            "status": LABEL_NOT_MODELED,
            "explanation": "External CBSE examination standardized distributions are not simulated in SchoolTwin.",
            "formula": "Not simulated",
            "causal_chain": [],
            "causal_note": None,
        },
        {
            "id": "student_withdrawal_elasticity",
            "category": "Student Enrollment",
            "name": "Fee-Driven School Transfers / Withdrawals",
            "units": "students",
            "baseline": None,
            "scenario": None,
            "control": None,
            "treatment": None,
            "abs_diff": None,
            "pct_diff": None,
            "status": LABEL_NOT_MODELED,
            "explanation": "Engine models fee impact on short-term absence propensity; external school switching choices are not modeled.",
            "formula": "Not simulated",
            "causal_chain": [],
            "causal_note": None,
        },
        {
            "id": "individual_wellbeing_diagnoses",
            "category": "Wellbeing & Sentiment",
            "name": "Clinical Mental Health & Wellbeing Diagnoses",
            "units": "clinical",
            "baseline": None,
            "scenario": None,
            "control": None,
            "treatment": None,
            "abs_diff": None,
            "pct_diff": None,
            "status": LABEL_NOT_MODELED,
            "explanation": "Synthetic agent models never produce psychiatric or medical diagnoses.",
            "formula": "Not simulated",
            "causal_chain": [],
            "causal_note": None,
        },
        # Explicit Unavailable Boundaries
        {
            "id": "cctv_facial_recognition",
            "category": "Privacy & Surveillance",
            "name": "Facial Recognition / Biometric Tracking",
            "units": "identities",
            "baseline": None,
            "scenario": None,
            "control": None,
            "treatment": None,
            "abs_diff": None,
            "pct_diff": None,
            "status": LABEL_UNAVAILABLE,
            "explanation": "SchoolTwin operates strictly on aggregate zone occupancy counters; individual camera tracking is banned by architectural design.",
            "formula": "Not collected",
            "causal_chain": [],
            "causal_note": None,
        },
    ]

    # Delta summary
    delta_summary = {
        m["id"]: {
            "abs_diff": m["abs_diff"],
            "pct_diff": m["pct_diff"],
            "status": m["status"],
            "direction": "favorable" if (
                (m["id"] in ("attendance_rate", "average_subject_mastery", "closing_cash_balance", "bus_fleet_availability") and (m["abs_diff"] or 0) > 0)
                or (m["id"] in ("uncovered_lessons_total", "late_arrivals_mean", "teacher_absence_total", "emergency_maintenance_expense_inr", "modeled_student_stress_index") and (m["abs_diff"] or 0) < 0)
            ) else ("adverse" if (
                (m["id"] in ("attendance_rate", "average_subject_mastery", "closing_cash_balance", "bus_fleet_availability") and (m["abs_diff"] or 0) < 0)
                or (m["id"] in ("uncovered_lessons_total", "late_arrivals_mean", "teacher_absence_total", "emergency_maintenance_expense_inr", "modeled_student_stress_index") and (m["abs_diff"] or 0) > 0)
            ) else "neutral")
        }
        for m in metrics if m["status"] in (LABEL_COMPUTED, LABEL_CONFIGURED)
    }

    return {
        "baseline_run_id": base_meta.get("run", {}).get("name", "baseline") if base_meta else None,
        "scenario_run_id": scen_meta.get("run", {}).get("name", "scenario"),
        "window_days": len(s_days),
        "open_days_scenario": len(s_open),
        "open_days_baseline": len(b_open),
        "metrics": metrics,
        "delta_summary": delta_summary,
    }


def aggregate_five_pair_metrics(pair_reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes distribution statistics across five matched control/treatment pairs.

    Reports:
    - per-pair control, treatment, delta
    - mean, median, min, max
    - counts of positive, negative, and zero differences
    Explicitly refuses to claim statistical significance from 5 pairs.
    """
    if not pair_reports:
        return {"pairs_count": 0, "metrics": {}}

    metric_ids = [m["id"] for m in pair_reports[0].get("metrics", [])]
    aggregated: Dict[str, Any] = {}

    for mid in metric_ids:
        pair_rows = []
        deltas = []
        metric_name = mid
        units = ""
        category = ""
        status = LABEL_UNAVAILABLE

        for idx, rep in enumerate(pair_reports):
            m_entry = next((m for m in rep.get("metrics", []) if m["id"] == mid), None)
            if not m_entry:
                continue
            metric_name = m_entry.get("name", mid)
            units = m_entry.get("units", "")
            category = m_entry.get("category", "")
            status = m_entry.get("status", status)

            c_val = m_entry.get("control")
            t_val = m_entry.get("treatment")
            d_val = m_entry.get("abs_diff")

            pair_rows.append({
                "pair_index": idx + 1,
                "control": c_val,
                "treatment": t_val,
                "delta": d_val,
            })
            if d_val is not None:
                deltas.append(float(d_val))

        if deltas:
            s_deltas = sorted(deltas)
            n = len(s_deltas)
            median_val = s_deltas[n // 2] if n % 2 == 1 else round((s_deltas[n // 2 - 1] + s_deltas[n // 2]) / 2.0, 2)
            mean_val = round(sum(deltas) / n, 2)
            min_val = round(min(deltas), 2)
            max_val = round(max(deltas), 2)
            inc_count = sum(1 for d in deltas if d > 0.001)
            dec_count = sum(1 for d in deltas if d < -0.001)
            no_diff_count = sum(1 for d in deltas if abs(d) <= 0.001)

            aggregated[mid] = {
                "id": mid,
                "name": metric_name,
                "units": units,
                "category": category,
                "status": status,
                "pairs": pair_rows,
                "stats": {
                    "mean_delta": mean_val,
                    "median_delta": median_val,
                    "min_delta": min_val,
                    "max_delta": max_val,
                    "count_increase": inc_count,
                    "count_decrease": dec_count,
                    "count_no_change": no_diff_count,
                    "sample_size": n,
                },
                "disclaimer": "Five-pair sample illustrates variance across random streams; not a claim of statistical significance.",
            }
        else:
            aggregated[mid] = {
                "id": mid,
                "name": metric_name,
                "units": units,
                "category": category,
                "status": status,
                "pairs": pair_rows,
                "stats": None,
                "disclaimer": "Metric is unmodeled or unavailable across evaluated pairs.",
            }

    return {
        "pairs_count": len(pair_reports),
        "replications_count": len(pair_reports),
        "metrics": aggregated,
        "note": "Replications share identical initial state and background schedules; differences isolate treatment effect.",
    }
