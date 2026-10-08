"""Canonical Scenario Schema and Validation for SchoolTwin.

Defines the single source of truth for scenario configurations, checkpoints,
event definitions, policy settings, and deterministic configuration hashing.
"""
import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "3.0.0"
ENGINE_VERSION = "3.0.0"

BASELINE_FIRST_DAY = 0
BASELINE_LAST_DAY = 150
BASELINE_DAYS = 151
BASELINE_START_DATE = "2026-01-01"
BASELINE_END_DATE = "2026-05-31"

MAX_SIMULATION_DAYS = 365
# Backward-compatible aliases for story calendar bounds
MIN_DATE = BASELINE_START_DATE
MAX_DATE = "2026-12-31"
TOTAL_DAYS = MAX_SIMULATION_DAYS

# ----------------------------------------------------------------------
# Policy parameter definitions with units, bounds, defaults, and modeling status
# ----------------------------------------------------------------------
POLICY_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "additional_teachers": {
        "title": "Additional Teachers",
        "type": "integer",
        "min": 0,
        "max": 10,
        "default": 0,
        "units": "teachers",
        "description": "Recruits extra teaching staff. Adds to monthly payroll and reduces uncovered lessons.",
        "status": "computed",
        "engine_module": "finance.py & engine.py",
    },
    "tuition_fee_delta_pct": {
        "title": "Tuition Fee Delta",
        "type": "number",
        "min": -10.0,
        "max": 20.0,
        "default": 0.0,
        "units": "%",
        "description": "Adjusts tuition fee invoices. Requires governance approval flag to take effect.",
        "status": "computed",
        "engine_module": "finance.py",
    },
    "transport_fee_delta_pct": {
        "title": "Transport Fee Delta",
        "type": "number",
        "min": -10.0,
        "max": 20.0,
        "default": 0.0,
        "units": "%",
        "description": "Adjusts bus transport fee invoices after approval.",
        "status": "computed",
        "engine_module": "finance.py",
    },
    "fee_change_approved": {
        "title": "Fee Change Approved",
        "type": "boolean",
        "default": False,
        "units": "boolean",
        "description": "School board governance gate. Fee deltas apply only when approved.",
        "status": "computed",
        "engine_module": "decide.py & finance.py",
    },
    "attendance_support_budget_inr_per_month": {
        "title": "Attendance Support Budget",
        "type": "integer",
        "min": 0,
        "max": 300000,
        "default": 0,
        "units": "INR/mo",
        "description": "Dedicated funding for family follow-up, counselling, and transport outreach.",
        "status": "computed",
        "engine_module": "finance.py & engine.py",
    },
    "bus_backup_capacity": {
        "title": "Backup Buses",
        "type": "integer",
        "min": 0,
        "max": 4,
        "default": 0,
        "units": "buses",
        "description": "Standby contracted buses stationed near depot to mitigate route delays.",
        "status": "computed",
        "engine_module": "finance.py & engine.py",
    },
    "summer_maintenance_budget_inr": {
        "title": "Summer Maintenance Budget",
        "type": "integer",
        "min": 0,
        "max": 2000000,
        "default": 0,
        "units": "INR",
        "description": "Capital expenditure earmarked for summer facility repairs.",
        "status": "computed",
        "engine_module": "finance.py",
    },
    "autonomy_level": {
        "title": "AI Principal Autonomy",
        "type": "enum",
        "options": ["advisory_only", "low_risk_auto", "human_approved"],
        "default": "low_risk_auto",
        "units": "tier",
        "description": "Controls automatic execution of AI Principal operational proposals.",
        "status": "computed",
        "engine_module": "decide.py",
    },
    "instructional_effectiveness": {
        "title": "Instructional Effectiveness Index",
        "type": "number",
        "min": 0.5,
        "max": 1.5,
        "default": 1.0,
        "units": "multiplier",
        "description": "Pedagogical quality modifier driving student learning progression and mastery gains.",
        "status": "computed",
        "engine_module": "learning.py",
    },
    "assessment_difficulty": {
        "title": "Assessment Difficulty Index",
        "type": "number",
        "min": 0.5,
        "max": 1.5,
        "default": 1.0,
        "units": "multiplier",
        "description": "Examination difficulty factor calibrating periodic assessment score distributions.",
        "status": "computed",
        "engine_module": "learning.py",
    },
}

# ----------------------------------------------------------------------
# Supported event catalog definitions
# ----------------------------------------------------------------------
EVENT_CATALOG: Dict[str, Dict[str, Any]] = {
    # Phase 2 required events:
    "serious_student_fight": {
        "title": "Serious Student Altercation",
        "description": "A physical confrontation involving three students requiring immediate staff intervention and disciplinary inquiry.",
        "required_fields": ["date", "student_ids", "location", "severity"],
        "default_severity": "high",
        "allowed_origin_zone_types": ["corridor", "playground", "ground", "canteen", "classroom"],
        "requires_students": True,
        "modeled": True,
    },
    "suspected_prohibited_business": {
        "title": "Suspected Policy Violation / Prohibited Business",
        "description": "An allegation under administrative review regarding unauthorized peer transactions or prohibited items. Presumed innocent until factual inquiry completes.",
        "required_fields": ["date", "student_ids", "location", "investigation_status"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["canteen", "ground", "blind_spot", "washroom", "corridor", "office"],
        "requires_students": True,
        "modeled": True,
    },
    "teacher_resignation": {
        "title": "Teacher Resignation Notice",
        "description": "A faculty member submits notice of resignation, creating cover workload pressure until replacement joins.",
        "required_fields": ["date", "teacher_name"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["staffroom", "office"],
        "requires_students": False,
        "modeled": True,
    },
    "teacher_resignation_notice": {
        "title": "Teacher Resignation Notice",
        "description": "A faculty member submits notice of resignation, creating cover workload pressure until replacement joins.",
        "required_fields": ["date", "teacher_name"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["staffroom", "office"],
        "requires_students": False,
        "modeled": True,
    },
    "bus_breakdown": {
        "title": "School Bus Breakdown",
        "description": "Mechanical failure on a bus route causing arrival delay and student lateness spike.",
        "required_fields": ["date", "route_number", "delay_minutes"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["bus", "gate"],
        "requires_students": True,
        "modeled": True,
    },
    "school_fee_increase": {
        "title": "Fee Increase Announcement",
        "description": "Official communication of revised fee schedule, prompting parental queries and administrative clarifications.",
        "required_fields": ["date", "fee_category", "delta_pct"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["office", "gate"],
        "requires_students": False,
        "modeled": True,
    },
    "additional_teacher_hired": {
        "title": "Additional Teacher Hired",
        "description": "New teaching faculty appointed, reducing lesson coverage deficits and adjusting payroll accrual.",
        "required_fields": ["date", "teacher_name", "subject_or_role"],
        "default_severity": "low",
        "allowed_origin_zone_types": ["staffroom", "office"],
        "requires_students": False,
        "modeled": True,
    },
    # Extended Incident Types (WP1 & WP2 per Decision D6):
    "water_cooler_breakdown": {
        "title": "Water Cooler Breakdown",
        "description": "Drinking water cooler mechanical or refrigeration failure creating hydration deficit and corridor/canteen queue pressure.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["fixture", "corridor", "canteen", "ground"],
        "requires_students": False,  # facility incident - allowed on closed days
        "modeled": True,
    },
    "collective_strike": {
        "title": "Staff Collective Strike",
        "description": "Faculty or operational staff withholding services, causing supervision gaps and classroom evacuation to grounds.",
        "required_fields": ["date"],
        "default_severity": "high",
        "allowed_origin_zone_types": ["ground", "staffroom", "admin_lobby", "office"],
        "requires_students": True,  # student-dependent incident
        "modeled": True,
    },
    # Existing catalog templates:
    "weather_attendance_dip": {
        "title": "Weather-related Attendance Dip",
        "description": "Severe winter fog, rain, or heat wave discouraging attendance.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["ground", "gate"],
        "requires_students": True,
        "modeled": True,
    },
    "student_teacher_conflict": {
        "title": "Classroom Assessment Dispute",
        "description": "Dispute over test conditions leading to lost instructional time.",
        "required_fields": ["date", "room"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["classroom", "staffroom", "office"],
        "requires_students": True,
        "modeled": True,
    },
    "lab_inventory_discrepancy": {
        "title": "Lab Inventory Discrepancy",
        "description": "Unsigned transfer of laboratory apparatus requiring reconciliation.",
        "required_fields": ["date"],
        "default_severity": "low",
        "allowed_origin_zone_types": ["lab", "store"],
        "requires_students": False,
        "modeled": True,
    },
    "first_aid_visit": {
        "title": "Infirmary First-Aid Visit",
        "description": "Cluster of minor student visits to infirmary.",
        "required_fields": ["date"],
        "default_severity": "low",
        "allowed_origin_zone_types": ["infirmary", "corridor"],
        "requires_students": True,
        "modeled": True,
    },
    "transport_lateness_spike": {
        "title": "Transport Lateness Spike",
        "description": "Merged or delayed bus routes creating a surge of late arrivals.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["bus", "gate"],
        "requires_students": True,
        "modeled": True,
    },
    "annual_day_crowd_buildup": {
        "title": "Annual Day Crowd Build-up",
        "description": "Visitor congestion and rehearsal activities affecting corridors.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["ground", "corridor", "gate"],
        "requires_students": True,
        "modeled": True,
    },
    "duplicate_fee_reminder": {
        "title": "Duplicate Fee Reminder Sent",
        "description": "Erroneous automated batch reminder creating inbound billing inquiries.",
        "required_fields": ["date"],
        "default_severity": "low",
        "allowed_origin_zone_types": ["office"],
        "requires_students": False,
        "modeled": True,
    },
    "teacher_absence_and_cover_pressure": {
        "title": "Teacher Absence & Cover Pressure",
        "description": "Unplanned faculty leave requiring internal cover arrangements.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["staffroom", "classroom"],
        "requires_students": True,
        "modeled": True,
    },
    "exam_paper_printing_error": {
        "title": "Exam Paper Printing Discrepancy",
        "description": "Missing pages in test packets requiring emergency reprints.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["office", "store"],
        "requires_students": False,
        "modeled": True,
    },
    "marks_import_anomaly": {
        "title": "Marks Import Anomaly",
        "description": "Spreadsheet column misalignment detected prior to release.",
        "required_fields": ["date"],
        "default_severity": "low",
        "allowed_origin_zone_types": ["office", "lab"],
        "requires_students": False,
        "modeled": True,
    },
    "classroom_fan_failure": {
        "title": "Classroom Ceiling Fan Failure",
        "description": "Electrical fan fault in high heat prompting class relocation.",
        "required_fields": ["date", "room"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["classroom"],
        "requires_students": False,
        "modeled": True,
    },
    "bus_gate_pillar_scrape": {
        "title": "Bus Gate Pillar Scrape",
        "description": "Slow-speed bus contact with gate masonry with no student injuries.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["gate", "bus"],
        "requires_students": False,
        "modeled": True,
    },
    "fee_transparency_queries": {
        "title": "Fee Transparency Queries",
        "description": "Delegation of parents requesting itemized fee schedules.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["office", "gate"],
        "requires_students": False,
        "modeled": True,
    },
    "heat_and_utility_pressure": {
        "title": "Heat Wave & Utility Pressure",
        "description": "High ambient temperature stressing power grid and campus chillers.",
        "required_fields": ["date"],
        "default_severity": "high",
        "allowed_origin_zone_types": ["ground", "utility", "pump_house"],
        "requires_students": False,
        "modeled": True,
    },
    "computer_lab_circuit_trip": {
        "title": "Computer Lab Circuit Breaker Trip",
        "description": "Overload trip forcing temporary closure of IT lab.",
        "required_fields": ["date"],
        "default_severity": "medium",
        "allowed_origin_zone_types": ["lab"],
        "requires_students": False,
        "modeled": True,
    },
    "fuel_invoice_variance": {
        "title": "Fuel Vendor Invoice Variance",
        "description": "Billing variance between transport contractor fuel quotes and invoice.",
        "required_fields": ["date"],
        "default_severity": "low",
        "allowed_origin_zone_types": ["office"],
        "requires_students": False,
        "modeled": True,
    },
    "water_motor_failure": {
        "title": "Water Pump Motor Failure",
        "description": "Submersible pump failure requiring emergency water tanker dispatch.",
        "required_fields": ["date"],
        "default_severity": "high",
        "allowed_origin_zone_types": ["blind_spot", "pump_house", "utility", "ground"],
        "requires_students": False,
        "modeled": True,
    },
}

# ----------------------------------------------------------------------
# Helper functions for normalization and hashing
# ----------------------------------------------------------------------
def compute_config_hash(data: Any) -> str:
    """Computes a deterministic SHA-256 hash for a normalized configuration dictionary."""
    normalized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def validate_date(date_str: str) -> Tuple[bool, Optional[str]]:
    """Validates that a date string is in YYYY-MM-DD format and falls within the school calendar."""
    if not isinstance(date_str, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False, f"Date '{date_str}' must be in YYYY-MM-DD format"
    if date_str < MIN_DATE or date_str > MAX_DATE:
        return False, f"Date '{date_str}' is outside the school calendar ({MIN_DATE} to {MAX_DATE})"
    return True, None


_VALID_ZONES_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def get_valid_zones() -> Dict[str, Dict[str, Any]]:
    """Loads and caches the 69 canonical campus zones with floor and type."""
    global _VALID_ZONES_CACHE
    if _VALID_ZONES_CACHE is not None:
        return _VALID_ZONES_CACHE
    import yaml
    from .config import ROOT
    from .story import Story
    from .world import World

    map_path = ROOT / "config" / "map.yaml"
    map_cfg = yaml.safe_load(map_path.read_text(encoding="utf-8")) if map_path.exists() else {}
    story = Story()
    world = World(map_cfg, story.rooms())
    zones = {}
    for zid, z in world.zones.items():
        zones[zid] = {
            "id": z.id,
            "floor": z.floor,
            "type": z.type,
            "label": z.label,
        }
    _VALID_ZONES_CACHE = zones
    return zones


def validate_location(location: Any, event_type: str) -> Tuple[bool, str, Optional[str], Optional[Dict[str, Any]]]:
    """Validates location for an incident against the 69 campus zones and allowed types.

    Returns (is_valid, status, error_message, origin_record).
    status: 'known' | 'unknown' | 'not_configured' | 'invalid'
    """
    valid_zones = get_valid_zones()
    ec = EVENT_CATALOG.get(event_type, {})
    allowed_types = ec.get("allowed_origin_zone_types", [])

    if not location or str(location).strip() in ("", "none", "null"):
        # Location was not provided
        if event_type in ("water_cooler_breakdown", "water_motor_failure", "classroom_fan_failure"):
            return False, "not_configured", f"Origin location not configured for '{event_type}'. Please select a campus zone or fixture.", {
                "status": "not_configured", "zone_id": None, "fixture_id": None, "floor": None, "source": "unconfigured"
            }
        return True, "unknown", None, {
            "status": "unknown", "zone_id": None, "fixture_id": None, "floor": None, "source": "default_unknown"
        }

    loc_str = str(location).strip()
    if loc_str == "unknown":
        if event_type in ("water_cooler_breakdown", "classroom_fan_failure"):
            return False, "not_configured", f"Location cannot be 'unknown' for '{event_type}'. Must be a configured zone.", {
                "status": "not_configured", "zone_id": None, "fixture_id": None, "floor": None, "source": "unconfigured"
            }
        return True, "unknown", None, {
            "status": "unknown", "zone_id": None, "fixture_id": None, "floor": None, "source": "user_unknown"
        }

    if loc_str not in valid_zones:
        return False, "invalid", f"Unknown zone ID '{loc_str}'. Must be one of the 69 valid campus zones.", None

    zinfo = valid_zones[loc_str]
    ztype = zinfo["type"]
    if allowed_types and ztype not in allowed_types:
        return False, "invalid", f"Zone '{loc_str}' of type '{ztype}' is not allowed for incident '{event_type}'. Allowed types: {allowed_types}", None

    return True, "known", None, {
        "status": "known",
        "zone_id": loc_str,
        "fixture_id": None,
        "floor": zinfo["floor"],
        "source": "user_selected",
    }


def compute_scenario_timeline(
    start_day: int = 151,
    duration: Any = 30,
    duration_preset: Optional[str] = None,
    custom_days: Optional[int] = None,
    reopening_date: str = "2026-07-01",
) -> Dict[str, Any]:
    """Computes exact scenario timeline, start/end day, start/end dates, and school day counts."""
    from .extension_calendar import ExtensionCalendar
    cal = ExtensionCalendar(reopening_date=reopening_date)

    if duration_preset is not None:
        if duration_preset == "custom" and custom_days is not None:
            duration = custom_days
        else:
            duration = duration_preset

    if isinstance(duration, bool):
        raise ValueError("Duration must be an integer, got bool")

    start_day = int(start_day)
    # Check presets
    if duration == "1_month":
        # June: 30 days
        dur_days = 30
    elif duration == "3_months":
        # June (30) + July (31) + August (31) = 92 days
        dur_days = 92
    else:
        try:
            dur_days = int(duration)
        except Exception:
            raise ValueError(f"Duration must be an integer, got {type(duration).__name__}")

    if dur_days <= 0:
        raise ValueError(f"Duration must be a positive integer, got {dur_days}")
    if dur_days > MAX_SIMULATION_DAYS:
        raise ValueError(f"Duration ({dur_days} days) exceeds maximum allowed cap of {MAX_SIMULATION_DAYS} days")

    return cal.compute_timeline(start_day=start_day, duration_days=dur_days)


# ----------------------------------------------------------------------
# Scenario Schema Class
# ----------------------------------------------------------------------
@dataclass
class ScenarioConfig:
    scenario_id: str
    name: str
    description: str = ""
    parent_run_id: str = "story_baseline"
    checkpoint_id: Optional[str] = "CKPT-DAY-150-TERM-CLOSE"
    start_day: int = 151
    end_day: int = 180
    fork_day: Optional[int] = None
    seed: int = 20261014
    mode: str = "generate"
    randomness_intensity: float = 1.0
    use_story_events: bool = False
    disabled_story_events: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    policy_overrides: Dict[str, Any] = field(default_factory=dict)
    branch: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    created_at: str = ""
    status: str = "draft"
    config_hash: str = ""

    def __post_init__(self):
        if not self.branch:
            from .extension_calendar import ExtensionCalendar
            cal = ExtensionCalendar()
            dur = max(1, self.end_day - self.start_day + 1)
            self.branch = {
                "parent_run_id": self.parent_run_id,
                "checkpoint_id": self.checkpoint_id,
                "start_day": self.start_day,
                "start_date": cal.date_for_day(self.start_day),
                "duration_days": dur,
                "end_day": self.end_day,
                "end_date": cal.date_for_day(self.end_day),
                "extension_calendar": {
                    "source": "assumed",
                    "reopening_date": "2026-07-01",
                    "environment": "neutral_assumed",
                },
                "control_run_id": None,
            }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["config_hash"] = self.get_hash()
        return d

    def get_hash(self) -> str:
        payload = {
            "name": self.name,
            "parent_run_id": self.parent_run_id,
            "checkpoint_id": self.checkpoint_id,
            "start_day": self.start_day,
            "end_day": self.end_day,
            "fork_day": self.fork_day,
            "seed": self.seed,
            "mode": self.mode,
            "randomness_intensity": self.randomness_intensity,
            "use_story_events": self.use_story_events,
            "disabled_story_events": sorted(self.disabled_story_events),
            "events": self.events,
            "policy_overrides": self.policy_overrides,
            "branch": self.branch,
        }
        return compute_config_hash(payload)

    def to_engine_overview(self) -> Dict[str, Any]:
        """Converts canonical scenario config to the overview dict consumed by Engine."""
        name = re.sub(r"[^A-Za-z0-9_-]", "_", self.name)[:60] or "scenario"
        ov: Dict[str, Any] = {
            "name": name,
            "scenario_id": self.scenario_id,
            "mode": self.mode,
            "seed": int(self.seed),
            "start_day": int(self.start_day),
            "end_day": int(self.end_day),
            "checkpoint_id": self.checkpoint_id,
            "branch": copy.deepcopy(self.branch),
            "randomness": {"intensity": float(self.randomness_intensity)},
            "events": {
                "use_story_events": bool(self.use_story_events),
                "disable": list(self.disabled_story_events),
                "add": copy.deepcopy(self.events),
                "random": {"per_month": 0, "types": []},
            },
            "levers": {
                "additional_teachers": int(self.policy_overrides.get("additional_teachers", 0)),
                "attendance_support_budget_inr_per_month": int(
                    self.policy_overrides.get("attendance_support_budget_inr_per_month", 0)
                ),
                "bus_backup_capacity": int(self.policy_overrides.get("bus_backup_capacity", 0)),
                "tuition_fee_delta_pct": float(self.policy_overrides.get("tuition_fee_delta_pct", 0.0)),
                "fee_change_approved": bool(self.policy_overrides.get("fee_change_approved", False)),
                "transport_fee_delta_pct": float(self.policy_overrides.get("transport_fee_delta_pct", 0.0)),
                "summer_maintenance_budget_inr": int(
                    self.policy_overrides.get("summer_maintenance_budget_inr", 0)
                ),
                "autonomy_level": str(self.policy_overrides.get("autonomy_level", "low_risk_auto")),
            },
            "approvals": {},
            "patches": [],
            "config_hash": self.get_hash(),
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
        }
        return ov


# ----------------------------------------------------------------------
# Canonical Validation Suite
# ----------------------------------------------------------------------
def validate_scenario(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Strictly validates a scenario configuration dict against the canonical schema.

    Returns (is_valid, list_of_error_messages).
    """
    from .extension_calendar import ExtensionCalendar
    errors: List[str] = []

    # Basic identity
    name = data.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        errors.append("Scenario name is required")
    elif len(name.strip()) > 80:
        errors.append("Scenario name must be 80 characters or fewer")

    # Protected baseline check
    if isinstance(name, str) and name.strip() == "story_baseline":
        errors.append("Cannot create or overwrite protected baseline run 'story_baseline'")

    branch = data.get("branch") if isinstance(data.get("branch"), dict) else None
    reopening_date = (branch.get("reopening_date") if branch else None) or data.get("reopening_date", "2026-07-01")
    cal = ExtensionCalendar(reopening_date=reopening_date)

    if branch is not None:
        start_day = branch.get("start_day", 151)
        duration_days = branch.get("duration_days")
        end_day = branch.get("end_day")
    elif "start_day" in data:
        start_day = data["start_day"]
        duration_days = data.get("duration_days")
        end_day = data.get("end_day")
    else:
        has_baseline_events = any(
            isinstance(ev, dict) and ev.get("date") and cal.day_for_date(ev["date"]) < 151
            for ev in data.get("events", [])
            if isinstance(ev, dict) and ev.get("date")
        )
        start_day = 0 if has_baseline_events else 151
        duration_days = data.get("duration_days")
        end_day = data.get("end_day")
    if duration_days is not None:
        if isinstance(duration_days, bool) or not isinstance(duration_days, int):
            errors.append(f"Duration must be an integer, got {type(duration_days).__name__}")
        elif duration_days <= 0:
            errors.append(f"Duration must be a positive integer, got {duration_days}")
        elif duration_days > MAX_SIMULATION_DAYS:
            errors.append(f"Duration ({duration_days} days) exceeds maximum allowed cap of {MAX_SIMULATION_DAYS} days")

    # Horizon validation
    if not isinstance(start_day, int) or start_day < 0 or start_day >= MAX_SIMULATION_DAYS:
        errors.append(f"start_day must be an integer between 0 and {MAX_SIMULATION_DAYS - 1}")
    if end_day is not None:
        if not isinstance(end_day, int) or end_day < 0 or end_day >= MAX_SIMULATION_DAYS:
            errors.append(f"end_day must be an integer between 0 and {MAX_SIMULATION_DAYS - 1}")
        elif isinstance(start_day, int) and start_day > end_day:
            errors.append(f"start_day ({start_day}) cannot exceed end_day ({end_day})")

    fork_day = data.get("fork_day")
    if fork_day is not None:
        if not isinstance(fork_day, int) or fork_day < 0 or fork_day >= MAX_SIMULATION_DAYS:
            errors.append(f"fork_day must be an integer between 0 and {MAX_SIMULATION_DAYS - 1}")

    # Seed
    seed = data.get("seed", 20261014)
    if not isinstance(seed, (int, float)):
        errors.append("Random seed must be a valid number")

    # Mode
    mode = data.get("mode", "generate")
    if mode not in ("anchor", "generate"):
        errors.append("Mode must be either 'anchor' or 'generate'")

    # Policy overrides
    policies = data.get("policy_overrides", {})
    if not isinstance(policies, dict):
        errors.append("policy_overrides must be an object")
    else:
        for k, v in policies.items():
            if k not in POLICY_DEFINITIONS:
                # Unsupported policy warning/error
                errors.append(f"Unsupported policy parameter '{k}'")
                continue
            pdef = POLICY_DEFINITIONS[k]
            ptype = pdef["type"]
            if ptype == "integer":
                if not isinstance(v, int) or isinstance(v, bool):
                    errors.append(f"Policy '{k}' must be an integer")
                else:
                    if "min" in pdef and v < pdef["min"]:
                        errors.append(f"Policy '{k}' ({v}) is below minimum allowed ({pdef['min']})")
                    if "max" in pdef and v > pdef["max"]:
                        errors.append(f"Policy '{k}' ({v}) is above maximum allowed ({pdef['max']})")
            elif ptype == "number":
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"Policy '{k}' must be a number")
                else:
                    if "min" in pdef and v < pdef["min"]:
                        errors.append(f"Policy '{k}' ({v}) is below minimum allowed ({pdef['min']})")
                    if "max" in pdef and v > pdef["max"]:
                        errors.append(f"Policy '{k}' ({v}) is above maximum allowed ({pdef['max']})")
            elif ptype == "boolean":
                if not isinstance(v, bool):
                    errors.append(f"Policy '{k}' must be a boolean (true/false)")
            elif ptype == "enum":
                if v not in pdef["options"]:
                    errors.append(f"Policy '{k}' ({v}) must be one of: {pdef['options']}")

    # Events validation
    events = data.get("events", [])
    if not isinstance(events, list):
        errors.append("events must be a list of event objects")
    else:
        start_date = cal.date_for_day(start_day) if isinstance(start_day, int) and start_day >= 0 else BASELINE_START_DATE
        end_date = cal.date_for_day(end_day) if isinstance(end_day, int) and end_day >= 0 else MAX_DATE

        for idx, ev in enumerate(events):
            if not isinstance(ev, dict):
                errors.append(f"Event at index {idx} must be an object")
                continue
            etype = ev.get("type")
            if not etype or etype not in EVENT_CATALOG:
                errors.append(f"Event #{idx + 1} has unsupported type '{etype}'")
                continue

            edate = ev.get("date")
            is_valid_dt, dt_err = validate_date(edate)
            if not is_valid_dt:
                errors.append(f"Event #{idx + 1} ({etype}): {dt_err}")
                continue

            eday = cal.day_for_date(edate)
            if isinstance(start_day, int) and eday < start_day:
                errors.append(
                    f"Event #{idx + 1} ({etype}): Date '{edate}' (Day {eday}) is before scenario start Day {start_day} ({start_date}). Suggested date: {start_date}"
                )
            elif isinstance(end_day, int) and eday > end_day:
                errors.append(
                    f"Event #{idx + 1} ({etype}): Date '{edate}' (Day {eday}) is after scenario end Day {end_day} ({end_date}). Suggested date: {end_date}"
                )
            else:
                cat_info = EVENT_CATALOG.get(etype, {})
                req_students = cat_info.get("requires_students", True)
                day_inf = cal.info(eday)
                if req_students and not day_inf["open"]:
                    # Student incident on closed day: search for nearest open day
                    nearest = None
                    min_diff = 9999
                    search_end = end_day if isinstance(end_day, int) else min(eday + 30, MAX_SIMULATION_DAYS - 1)
                    search_start = start_day if isinstance(start_day, int) else 0
                    for cand_d in range(search_start, search_end + 1):
                        if cal.info(cand_d)["open"]:
                            diff = abs(cand_d - eday)
                            if diff < min_diff:
                                min_diff = diff
                                nearest = cand_d
                    sug_iso = cal.date_for_day(nearest) if nearest is not None else start_date
                    errors.append(
                        f"Event #{idx + 1} ({etype}): Student-dependent incident on closed day '{edate}' (Day {eday}, {day_inf['type']}). Suggested open day: '{sug_iso}' (Day {nearest})"
                    )

            sev = ev.get("severity", "medium")
            if sev not in ("low", "medium", "high"):
                errors.append(f"Event #{idx + 1} ({etype}): severity must be 'low', 'medium', or 'high'")

            params = ev.get("params", {})
            if not isinstance(params, dict):
                errors.append(f"Event #{idx + 1} ({etype}): params must be an object")
                params = {}

            # Location validation
            loc = ev.get("location") or params.get("location") or ev.get("room") or params.get("room")
            is_loc_valid, loc_status, loc_err, origin_rec = validate_location(loc, etype)
            if not is_loc_valid and loc_status != "not_configured":
                errors.append(f"Event #{idx + 1} ({etype}): {loc_err}")

            # Specific validations for the 6 Phase 2 event types
            if etype == "serious_student_fight":
                # Check three students involved
                sids = ev.get("student_ids") or params.get("student_ids") or []
                if not isinstance(sids, list) or len(sids) != 3:
                    errors.append(f"Event #{idx + 1} (serious_student_fight) requires exactly 3 student IDs (got {len(sids)})")
                else:
                    for sid in sids:
                        if not isinstance(sid, (str, int)) or not str(sid).strip():
                            errors.append(f"Event #{idx + 1}: invalid student ID '{sid}'")

            elif etype == "suspected_prohibited_business":
                sids = ev.get("student_ids") or params.get("student_ids") or []
                if not isinstance(sids, list) or len(sids) < 1:
                    errors.append(f"Event #{idx + 1} (suspected_prohibited_business) requires at least one student ID")
                status = ev.get("investigation_status") or params.get("investigation_status", "under_review")
                if status not in ("under_review", "cleared", "confirmed"):
                    errors.append(f"Event #{idx + 1} (suspected_prohibited_business): investigation_status must be 'under_review', 'cleared', or 'confirmed'")

            elif etype in ("teacher_resignation", "teacher_resignation_notice"):
                tname = ev.get("teacher_name") or params.get("name") or params.get("teacher_name")
                if not tname or not isinstance(tname, str) or not tname.strip():
                    errors.append(f"Event #{idx + 1} ({etype}) requires 'teacher_name'")

            elif etype == "bus_breakdown":
                route = ev.get("route_number") or params.get("route") or params.get("routes")
                if route is None:
                    errors.append(f"Event #{idx + 1} (bus_breakdown) requires 'route_number' (1 to 12)")

            elif etype == "school_fee_increase":
                pct = ev.get("delta_pct") or params.get("delta_pct") or params.get("tuition_fee_delta_pct")
                if pct is None or not isinstance(pct, (int, float)):
                    errors.append(f"Event #{idx + 1} (school_fee_increase) requires a numeric 'delta_pct'")

            elif etype == "additional_teacher_hired":
                tname = ev.get("teacher_name") or params.get("teacher_name") or params.get("name")
                if not tname or not isinstance(tname, str) or not tname.strip():
                    errors.append(f"Event #{idx + 1} (additional_teacher_hired) requires 'teacher_name'")

    return len(errors) == 0, errors


def calculate_scenario_start_from_baseline(
    parent_run_id: str = "story_baseline",
    duration_days: int = 30,
    pack_dir: Optional[Any] = None,
) -> Dict[str, Any]:
    """Calculates canonical scenario start, duration, and projected end date from saved baseline endpoint."""
    from pathlib import Path
    parent_end_day = 150
    if pack_dir is None:
        from .config import ROOT
        pack_dir = ROOT / "pack"
    else:
        pack_dir = Path(pack_dir)

    meta_path = pack_dir / parent_run_id / "meta.json"
    if meta_path.exists():
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
            parent_end_day = int(m.get("run", {}).get("end_day", 150))
        except Exception:
            parent_end_day = 150

    start_day = parent_end_day + 1
    safe_duration = max(1, min(int(duration_days), TOTAL_DAYS - start_day))
    end_day = min(TOTAL_DAYS - 1, start_day + safe_duration - 1)

    base_date = date(2026, 1, 1)
    start_date = (base_date + timedelta(days=start_day)).isoformat()
    end_date = (base_date + timedelta(days=end_day)).isoformat()

    return {
        "parent_run_id": parent_run_id,
        "parent_end_day": parent_end_day,
        "start_day": start_day,
        "end_day": end_day,
        "duration_days": (end_day - start_day + 1),
        "start_date": start_date,
        "end_date": end_date,
        "total_calendar_days": TOTAL_DAYS,
        "calendar_max_date": MAX_DATE,
        "is_continuation": True,
    }
