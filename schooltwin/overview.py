"""The overview: what a user hands the engine. Everything optional; unspecified values use these defaults."""
import copy
import json
from pathlib import Path

DEFAULT = {
    "name": "story_baseline",
    "mode": "anchor",               # anchor: the story's attendance and finances drive each day | generate: the engine produces them
    "seed": 20261014,
    "start_day": 0,
    "end_day": 150,
    "randomness": {"intensity": 1.0},          # scales day-to-day wobble and rare behaviour (generate mode and micro behaviour)
    "events": {
        "use_story_events": True,
        "disable": [],                          # story event ids to leave out, e.g. ["GT-004"]
        "add": [],                              # {"date": "2026-03-10", "type": "transport_lateness_spike", "severity": "high", "params": {...}}
        "random": {"per_month": 0, "types": ["weather_attendance_dip", "transport_lateness_spike",
                                              "teacher_absence_and_cover_pressure", "classroom_fan_failure",
                                              "first_aid_visit", "annual_day_crowd_buildup"]},
    },
    "levers": {"additional_teachers": 0, "attendance_support_budget_inr_per_month": 0, "bus_backup_capacity": 0,
               "tuition_fee_delta_pct": 0, "fee_change_approved": False, "transport_fee_delta_pct": 0,
               "summer_maintenance_budget_inr": 0, "autonomy_level": "low_risk_auto"},
    "approvals": {},                            # decision_id -> true | false
    "patches": [],                              # [{"from_day": 60, "levers": {...}}]: change settings part-way (forking)
}


def merge(base, patch):
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path_or_dict=None):
    if path_or_dict is None:
        return copy.deepcopy(DEFAULT)
    if isinstance(path_or_dict, (str, Path)):
        path_or_dict = json.loads(Path(path_or_dict).read_text(encoding="utf-8"))
    ov = merge(DEFAULT, path_or_dict)
    assert ov["mode"] in ("anchor", "generate"), "mode must be anchor or generate"
    return ov


def lever(ov, i, name):
    """A lever's value on day i, honouring patches that start part-way through the run."""
    val = ov["levers"].get(name)
    for p in sorted(ov["patches"], key=lambda p: p["from_day"]):
        if p["from_day"] <= i and name in p.get("levers", {}):
            val = p["levers"][name]
    return val


def mode_at(ov, i):
    """anchor or generate on day i. A patch may switch a run from anchor to generate from some day on."""
    if i >= 151:
        return "generate"
    m = ov.get("mode", "anchor")
    for p in sorted(ov.get("patches", []), key=lambda p: p.get("from_day", 0)):
        if p.get("from_day", 0) <= i and "mode" in p:
            m = p["mode"]
    return m
