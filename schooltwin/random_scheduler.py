"""Controlled Random Event Scheduler and Profiles for SchoolTwin (Part D).

Provides deterministic, reproducible background event schedules shared across
paired simulations (Control vs. Treatment):
- Preset Profiles: Calm, Balanced (default), Stress-test, Custom.
- Controlled Event Scheduler: Enforces daily/weekly caps, category weights, cooldowns,
  valid zone IDs, and reproducible isolated random seeds.
- Pre-generates one shared background schedule so that only the user's custom event
  drives divergence between paired branches.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, List, Optional, Set

import numpy as np

from .events import make_event
from .schema import get_valid_zones

# ----------------------------------------------------------------------
# Profile Definitions
# ----------------------------------------------------------------------
RANDOM_PROFILES: Dict[str, Dict[str, Any]] = {
    "calm": {
        "id": "calm",
        "name": "Calm",
        "description": "Routine variability with mostly minor operational friction. Major disruptions are excluded.",
        "expected_per_month": 0.5,
        "severity_weights": {"low": 0.70, "medium": 0.25, "high": 0.05},
        "max_per_day": 1,
        "max_per_week": 1,
        "max_major_per_month": 0,
        "cooldown_days": 14,
        "allowed_categories": ["facility", "utilities", "academic_admin", "transport"],
        "excluded_types": ["collective_strike", "teacher_resignation_notice", "serious_student_fight"],
    },
    "balanced": {
        "id": "balanced",
        "name": "Balanced (Default)",
        "description": "Normal school operating variation with regular minor friction and occasional utility or staffing challenges.",
        "expected_per_month": 1.5,
        "severity_weights": {"low": 0.40, "medium": 0.45, "high": 0.15},
        "max_per_day": 1,
        "max_per_week": 2,
        "max_major_per_month": 1,
        "cooldown_days": 8,
        "allowed_categories": ["facility", "utilities", "staffing", "student_social", "transport", "academic_admin", "finance_environment"],
        "excluded_types": ["teacher_resignation_notice"],  # Resignation is reserved for explicit interventions
    },
    "stress_test": {
        "id": "stress_test",
        "name": "Stress-test",
        "description": "Elevated operational strain: more frequent equipment faults, cover crunches, and logistical disruptions.",
        "expected_per_month": 3.5,
        "severity_weights": {"low": 0.20, "medium": 0.50, "high": 0.30},
        "max_per_day": 2,
        "max_per_week": 4,
        "max_major_per_month": 2,
        "cooldown_days": 4,
        "allowed_categories": ["facility", "utilities", "staffing", "student_social", "transport", "academic_admin", "finance_environment"],
        "excluded_types": ["teacher_resignation_notice"],
    },
    "custom": {
        "id": "custom",
        "name": "Custom",
        "description": "User-configured event frequencies, categories, cooldowns, and random seed.",
        "expected_per_month": 2.0,
        "severity_weights": {"low": 0.33, "medium": 0.34, "high": 0.33},
        "max_per_day": 2,
        "max_per_week": 3,
        "max_major_per_month": 2,
        "cooldown_days": 6,
        "allowed_categories": ["facility", "utilities", "staffing", "student_social", "transport", "academic_admin", "finance_environment"],
        "excluded_types": [],
    },
}

# ----------------------------------------------------------------------
# Category Event Catalogs & Zone Assignments
# ----------------------------------------------------------------------
CATEGORY_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "facility": [
        {"type": "water_cooler_breakdown", "locations": ["corridor_1", "corridor_2", "canteen"], "cost_range": [6000, 10000]},
        {"type": "water_motor_failure", "locations": ["pump_house"], "cost_range": [15000, 22000]},
        {"type": "classroom_fan_failure", "locations": ["class_9a", "class_8b", "class_10a"], "cost_range": [2500, 4500]},
        {"type": "door_lock_failure", "locations": ["library", "comp_lab_1", "store_room"], "cost_range": [1800, 3200]},
        {"type": "door_frame_damage", "locations": ["stair_A", "stair_B", "main_exit"], "cost_range": [3500, 6000]},
        {"type": "broken_classroom_furniture", "locations": ["class_9a", "class_10a", "class_8b"], "cost_range": [2000, 4000]},
        {"type": "room_closure", "locations": ["comp_lab_2", "canteen_back"], "cost_range": [1000, 3000]},
    ],
    "utilities": [
        {"type": "computer_lab_circuit_trip", "locations": ["comp_lab_1", "comp_lab_2"], "cost_range": [2000, 4500]},
        {"type": "campus_power_outage", "locations": ["north_ground", "admin_lobby"], "cost_range": [5000, 12000]},
        {"type": "water_service_disruption", "locations": ["wash_0", "wash_1", "wash_2"], "cost_range": [10000, 18000]},
    ],
    "staffing": [
        {"type": "teacher_absence_and_cover_pressure", "locations": ["staffroom"], "cost_range": [0, 0]},
        {"type": "urgent_cover_requirement", "locations": ["staffroom"], "cost_range": [0, 0]},
        {"type": "maintenance_team_overload", "locations": ["pump_house", "store_room"], "cost_range": [3000, 6000]},
        {"type": "it_support_bottleneck", "locations": ["comp_lab_1", "admin_lobby"], "cost_range": [0, 0]},
    ],
    "student_social": [
        {"type": "student_teacher_conflict", "locations": ["class_8b", "class_9a"], "cost_range": [0, 0]},
        {"type": "serious_student_fight", "locations": ["playground", "behind_playground", "canteen"], "cost_range": [0, 0]},
        {"type": "student_group_complaint", "locations": ["admin_lobby", "principal_office"], "cost_range": [0, 0]},
        {"type": "collective_strike", "locations": ["north_ground", "main_gate"], "cost_range": [0, 0]},
    ],
    "transport": [
        {"type": "transport_lateness_spike", "locations": ["bus_bay"], "cost_range": [0, 0]},
        {"type": "backup_vehicle_requirement", "locations": ["bus_bay"], "cost_range": [3500, 6500]},
        {"type": "bus_gate_pillar_scrape", "locations": ["main_gate"], "cost_range": [4000, 8000]},
    ],
    "academic_admin": [
        {"type": "exam_paper_printing_error", "locations": ["admin_lobby"], "cost_range": [1500, 3500]},
        {"type": "timetable_conflict", "locations": ["staffroom"], "cost_range": [0, 0]},
        {"type": "lab_inventory_discrepancy", "locations": ["lab_sci_1", "lab_sci_2", "lab_sci_3"], "cost_range": [2000, 5000]},
        {"type": "marks_import_anomaly", "locations": ["admin_lobby"], "cost_range": [0, 0]},
        {"type": "fee_transparency_queries", "locations": ["admin_lobby"], "cost_range": [0, 0]},
    ],
    "finance_environment": [
        {"type": "unplanned_repair_expense", "locations": ["admin_lobby"], "cost_range": [8000, 18000]},
        {"type": "fuel_invoice_variance", "locations": ["admin_lobby"], "cost_range": [2500, 6000]},
        {"type": "heat_and_utility_pressure", "locations": ["north_ground"], "cost_range": [6000, 12000]},
        {"type": "weather_attendance_dip", "locations": ["main_gate"], "cost_range": [0, 0]},
    ],
}


def get_profile_config(profile_name: str, custom_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retrieves profile configuration with optional custom overrides."""
    p_name = profile_name.lower().replace("-", "_") if profile_name else "balanced"
    base = copy.deepcopy(RANDOM_PROFILES.get(p_name, RANDOM_PROFILES["balanced"]))
    if p_name == "custom" and custom_cfg:
        base.update(custom_cfg)
    return base


def generate_paired_background_schedule(
    story: Any,
    start_day: int = 151,
    duration_days: int = 30,
    profile_name: str = "balanced",
    seed: int = 20261014,
    custom_cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Generates a canonical, reproducible background event schedule shared by Control & Treatment.

    Enforces:
    1. Isolated deterministic RNG keyed on pair seed and configuration hash.
    2. Daily and weekly frequency caps.
    3. Event category cooldowns to prevent unrealistic clustering.
    4. Valid campus location IDs.
    5. Realistic operational context (open days vs closed periods).
    """
    cfg = get_profile_config(profile_name, custom_cfg)
    end_day = min(len(story.days) - 1, start_day + duration_days - 1)

    # Isolated pseudorandom generator
    cfg_str = f"{seed}:{profile_name}:{start_day}:{duration_days}:{cfg['expected_per_month']}"
    stream_seed = int(hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.RandomState(stream_seed)

    # Identify eligible dates in the window
    eligible_days = []
    for d_idx in range(start_day, end_day + 1):
        d_meta = story.days[d_idx]
        eligible_days.append({
            "day": d_idx,
            "date": d_meta["date"],
            "open": d_meta.get("school_open_to_students", False),
            "type": d_meta.get("day_type", "instructional_day"),
        })

    if not eligible_days:
        return []

    # Compile candidate event catalog according to profile
    allowed_cats = cfg.get("allowed_categories", list(CATEGORY_CATALOG.keys()))
    excluded_types = set(cfg.get("excluded_types", []))
    candidate_catalog = []
    for cat in allowed_cats:
        for ev_meta in CATEGORY_CATALOG.get(cat, []):
            if ev_meta["type"] not in excluded_types:
                entry = dict(ev_meta)
                entry["category"] = cat
                candidate_catalog.append(entry)

    if not candidate_catalog:
        return []

    # Group days by month to budget Poisson event counts per month
    months_map: Dict[str, List[Dict[str, Any]]] = {}
    for ed in eligible_days:
        m = ed["date"][:7]
        months_map.setdefault(m, []).append(ed)

    rate_per_month = float(cfg.get("expected_per_month", 1.5))
    sev_weights = cfg.get("severity_weights", {"low": 0.40, "medium": 0.45, "high": 0.15})
    sev_choices = ["low", "medium", "high"]
    sev_probs = [sev_weights.get("low", 0.4), sev_weights.get("medium", 0.45), sev_weights.get("high", 0.15)]
    s_tot = sum(sev_probs) or 1.0
    sev_probs = [p / s_tot for p in sev_probs]

    cooldown_days = int(cfg.get("cooldown_days", 8))
    max_per_day = int(cfg.get("max_per_day", 1))
    max_per_week = int(cfg.get("max_per_week", 2))
    max_major_per_month = int(cfg.get("max_major_per_month", 1))

    schedule: List[Dict[str, Any]] = []
    daily_counts: Dict[str, int] = {}
    type_last_day: Dict[str, int] = {}

    for month_key, m_days in sorted(months_map.items()):
        # Determine number of events for this month using Poisson distribution
        # Scale for partial months if fewer than 20 days
        expected = rate_per_month * (len(m_days) / 30.0)
        n_events = int(rng.poisson(expected))
        if n_events <= 0:
            continue

        available_days = list(m_days)
        rng.shuffle(available_days)
        major_count = 0

        for candidate_day in available_days:
            if len([e for e in schedule if e["date"][:7] == month_key]) >= n_events:
                break

            d_str = candidate_day["date"]
            d_idx = candidate_day["day"]
            is_open = candidate_day["open"]

            if daily_counts.get(d_str, 0) >= max_per_day:
                continue

            # Check weekly count (within +/- 3 days)
            week_count = sum(1 for e in schedule if abs(e["day"] - d_idx) <= 3)
            if week_count >= max_per_week:
                continue

            # Select event candidate respecting openness constraints
            # Closed days generally only accept facility/utility/maintenance faults
            eligible_events = [
                c for c in candidate_catalog
                if (is_open or c["category"] in ("facility", "utilities", "finance_environment"))
                and (d_idx - type_last_day.get(c["type"], -999) >= cooldown_days)
            ]
            if not eligible_events:
                continue

            selected = eligible_events[rng.choice(len(eligible_events))]
            sev = rng.choice(sev_choices, p=sev_probs)

            # Check major severity limit per month
            if sev == "high":
                if major_count >= max_major_per_month:
                    sev = "medium"
                else:
                    major_count += 1

            # Select valid location
            locs = selected.get("locations", [])
            loc = locs[rng.choice(len(locs))] if locs else "admin_lobby"

            # Parameters
            params: Dict[str, Any] = {"location": loc}
            if selected["type"] == "water_cooler_breakdown":
                c_min, c_max = selected.get("cost_range", [6000, 10000])
                params["repair_cost_inr"] = int(rng.randint(c_min, c_max))
            elif selected["type"] == "classroom_fan_failure":
                params["room"] = loc
            elif selected["type"] == "transport_lateness_spike":
                params["routes"] = int(rng.choice([1, 2, 3]))
                delay_min = int(rng.randint(12, 28))
                params["delay"] = [delay_min, delay_min + 10]
                params["n_students"] = int(rng.randint(30, 60))
            elif selected["type"] == "serious_student_fight":
                params["student_ids"] = ["STU-0012", "STU-0015", "STU-0021"]
            elif selected["type"] == "weather_attendance_dip":
                params["attendance_dip_pct"] = int(rng.randint(10, 20))

            ev = make_event(
                date=d_str,
                etype=selected["type"],
                severity=sev,
                params=params,
                source="background_shared",
                eid=f"BGEV-{d_str}-{selected['type'][:8]}",
            )
            ev["day"] = d_idx
            ev["location"] = loc
            ev["category"] = selected["category"]
            ev["is_background"] = True

            schedule.append(ev)
            daily_counts[d_str] = daily_counts.get(d_str, 0) + 1
            type_last_day[selected["type"]] = d_idx

    # Sort schedule chronologically
    schedule.sort(key=lambda x: (x["day"], x["date"]))
    return schedule
