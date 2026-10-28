"""Runs paired control and treatment simulations under matching background schedules."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .baseline_manifest import assert_baseline_intact, check_write_allowed
from .compare import compare_runs
from .config import ROOT
from .engine import Engine
from .evaluate import evaluate
from .overview import DEFAULT, load
from .pack import Packer
from .random_scheduler import generate_paired_background_schedule, get_profile_config
from .schema import validate_paired_custom_event
from .story import Story


def make_pair_id(custom_event: Dict[str, Any], profile_name: str, seed: int) -> str:
    """Creates a deterministic, URL-safe identifier for a comparison pair.

    The hash covers the event's full semantic content (type, date, severity,
    params), so two different interventions on the same date cannot collide
    into one pack directory and silently overwrite each other's results.
    Identical content, profile, and seed still reproduce the same id
    (deterministic replay).
    """
    ev_type = str(custom_event.get("type", "custom"))[:12]
    ev_date = str(custom_event.get("date", "2026-06-01")).replace("-", "")
    content = json.dumps(
        {
            "type": custom_event.get("type"),
            "date": custom_event.get("date"),
            "severity": custom_event.get("severity", "medium"),
            "params": custom_event.get("params", {}),
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    h = hashlib.sha256(f"{content}:{profile_name}:{seed}".encode("utf-8")).hexdigest()[:6]
    clean_type = re.sub(r"[^a-zA-Z0-9_]", "_", ev_type).lower()
    return f"{clean_type}_{ev_date}_{h}"


_VALID_STATUS_TAGS = ("Computed", "Configured", "Not modeled", "Unavailable")


def build_event_day_impact(
    ctrl_days: List[Dict[str, Any]],
    trt_days: List[Dict[str, Any]],
    custom_event: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Day-level control-vs-treatment comparison for the intervention date.

    Window-aggregate metrics honestly round small interventions to zero
    (three students over 1,309 agents x 60 days), which reads as "nothing
    happened"; the intervention day itself carries the visible consequences
    (infirmary visits, the incident record, parent queries, attendance).
    """
    ev_date = custom_event.get("date")
    if not ev_date:
        return None
    b = next((d for d in ctrl_days if d.get("date") == ev_date), None)
    s = next((d for d in trt_days if d.get("date") == ev_date), None)
    if b is None or s is None:
        return None

    def val(day: Dict[str, Any], key: str) -> Optional[Any]:
        v = day.get(key)
        if key == "incidents":
            return len(v) if isinstance(v, list) else v
        return v

    rows = []
    for f in ("attendance_rate", "late", "mood_avg", "queries", "infirmary", "incidents"):
        bv, sv = val(b, f), val(s, f)
        if bv is None and sv is None:
            continue
        delta = None if (bv is None or sv is None) else round(float(sv) - float(bv), 4)
        rows.append({"id": f, "control": bv, "treatment": sv, "delta": delta})
    return {
        "date": ev_date,
        "event_type": custom_event.get("type"),
        "event_title": custom_event.get("title") or custom_event.get("type"),
        "metrics": rows,
        "note": "Window aggregates dilute small interventions; this is the intervention day itself (control vs treatment).",
    }


def classify_metric_status(metric: Dict[str, Any]) -> str:
    """Maps one comparison metric to its honest display status tag.

    Metric entries carry ``status`` (e.g. "Computed"); anything unexpected is
    reported as Unavailable rather than guessed.
    """
    status = metric.get("status")
    return status if status in _VALID_STATUS_TAGS else "Unavailable"


def classify_comparison_metrics(comp_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Returns a report's metrics, each annotated with an honest ``status_tag``."""
    classified = []
    for m in comp_report.get("metrics", []):
        m_entry = dict(m)
        m_entry["status_tag"] = classify_metric_status(m)
        classified.append(m_entry)
    return classified


def run_paired_simulation(
    custom_event: Dict[str, Any],
    start_day: int = 151,
    duration_days: int = 30,
    profile_name: str = "balanced",
    seed: int = 20261014,
    custom_cfg: Optional[Dict[str, Any]] = None,
    levers: Optional[Dict[str, Any]] = None,
    scenario_name: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    """Runs a paired Control vs Treatment simulation from the Day 150 baseline checkpoint.

    Returns the paired run metadata, diff summary, and pack pointers.
    """
    assert_baseline_intact()

    story = Story()

    # Honest-intervention gate: refuse to "simulate" an intervention the model
    # cannot execute as requested (e.g. a student incident during summer break)
    # instead of silently producing a near-identical pair.
    end_day_probe = min(len(story.days) - 1, start_day + duration_days - 1)
    v_ok, v_errors, v_warnings = validate_paired_custom_event(
        custom_event, start_day=start_day, end_day=end_day_probe
    )
    if not v_ok:
        raise ValueError("Custom event validation failed: " + " | ".join(v_errors))

    pair_id = make_pair_id(custom_event, profile_name, seed)
    ctrl_run_name = f"ctrl_{pair_id}"
    trt_run_name = (
        re.sub(r"[^A-Za-z0-9_-]", "_", scenario_name)[:60]
        if scenario_name and scenario_name != "story_baseline"
        else f"scen_{pair_id}"
    )

    # Enforce non-negotiable data preservation
    if ctrl_run_name == "story_baseline" or trt_run_name == "story_baseline":
        raise ValueError("Cannot overwrite protected historical baseline 'story_baseline'")

    ctrl_dir = ROOT / "pack" / ctrl_run_name
    trt_dir = ROOT / "pack" / trt_run_name
    check_write_allowed(ctrl_dir)
    check_write_allowed(trt_dir)


    bg_schedule = generate_paired_background_schedule(
        story=story,
        start_day=start_day,
        duration_days=duration_days,
        profile_name=profile_name,
        seed=seed,
        custom_cfg=custom_cfg,
    )

    # Ensure custom event has proper formatting
    clean_custom = dict(custom_event)
    clean_custom.setdefault("source", "user")
    clean_custom.setdefault("severity", "medium")
    clean_custom.setdefault("params", {})
    if "id" not in clean_custom:
        clean_custom["id"] = f"EV-CUSTOM-{clean_custom.get('date', '2026-06-01')}-{clean_custom.get('type', 'custom')[:8]}"

    # Tag events with source categories for UI categorization
    tagged_bg = []
    for ev in bg_schedule:
        tev = dict(ev)
        tev["comparison_tag"] = "shared_background"
        tagged_bg.append(tev)

    trt_custom = dict(clean_custom)
    trt_custom["comparison_tag"] = "custom_intervention"

    # Base levers
    applied_levers = copy.deepcopy(DEFAULT["levers"])
    if levers:
        applied_levers.update(levers)


    end_day = min(len(story.days) - 1, start_day + duration_days - 1)
    ctrl_ov = {
        "name": ctrl_run_name,
        "mode": "generate",
        "start_day": start_day,
        "end_day": end_day,
        "seed": seed,
        "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
        "randomness": {"intensity": 1.0},
        "events": {
            "use_story_events": True,
            "disable": [],
            "add": copy.deepcopy(tagged_bg),
            "random": {"per_month": 0, "types": []},
        },
        "levers": copy.deepcopy(applied_levers),
        "branch": {
            "branch_id": ctrl_run_name,
            "parent_id": "story_baseline",
            "branch_point_day": 150,
            "branch_type": "control",
        },
    }


    trt_events_add = copy.deepcopy(tagged_bg) + [trt_custom]
    trt_ov = {
        "name": trt_run_name,
        "mode": "generate",
        "start_day": start_day,
        "end_day": end_day,
        "seed": seed,
        "checkpoint_id": "CKPT-DAY-150-TERM-CLOSE",
        "randomness": {"intensity": 1.0},
        "events": {
            "use_story_events": True,
            "disable": [],
            "add": trt_events_add,
            "random": {"per_month": 0, "types": []},
        },
        "levers": copy.deepcopy(applied_levers),
        "branch": {
            "branch_id": trt_run_name,
            "parent_id": "story_baseline",
            "branch_point_day": 150,
            "branch_type": "treatment",
            "intervention_event_id": trt_custom["id"],
        },
    }

    total_days = end_day - start_day + 1


    if progress_cb:
        progress_cb("control", 0, total_days)

    ctrl_eng = Engine(ctrl_ov)
    ctrl_pk = Packer(ctrl_eng, ctrl_dir, redact=False)

    def on_ctrl_prog(step_idx, total):
        if progress_cb:
            progress_cb("control", step_idx - start_day + 1, total_days)

    ctrl_eng.run(on_day=ctrl_pk.on_day, progress=on_ctrl_prog)
    ctrl_eval = evaluate(ctrl_eng)
    ctrl_pk.finalize(ctrl_eval)


    if progress_cb:
        progress_cb("treatment", 0, total_days)

    trt_eng = Engine(trt_ov)
    trt_pk = Packer(trt_eng, trt_dir, redact=False)

    def on_trt_prog(step_idx, total):
        if progress_cb:
            progress_cb("treatment", step_idx - start_day + 1, total_days)

    trt_eng.run(on_day=trt_pk.on_day, progress=on_trt_prog)
    trt_eval = evaluate(trt_eng)
    trt_pk.finalize(trt_eval)


    # branches replay identical history before the branch point, so including
    # it would dilute divergence metrics)
    comp_report = compare_runs(ctrl_run_name, trt_run_name, window=(start_day, end_day))

    # Classify comparison metrics honestly (metric entries carry `status`,
    # e.g. "Computed" / "Configured" / "Not modeled" / "Unavailable")
    comp_report["metrics"] = classify_comparison_metrics(comp_report)


    pair_manifest = {
        "pair_id": pair_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_run": ctrl_run_name,
        "treatment_run": trt_run_name,
        "start_day": start_day,
        "end_day": end_day,
        "duration_days": duration_days,
        "seed": seed,
        "profile": profile_name,
        "custom_event": trt_custom,
        "shared_background_events_count": len(tagged_bg),
        "shared_background_events": tagged_bg,
        "branch_window": {"start_day": start_day, "end_day": end_day},
        "event_day_impact": build_event_day_impact(ctrl_eng.days, trt_eng.days, trt_custom),
        "warnings": v_warnings,
        "delta_summary": comp_report.get("delta_summary", {}),
        "narrative_summary": comp_report.get("narrative_summary", {}),
        "metrics": comp_report.get("metrics", []),
        "feasible_solutions": comp_report.get("feasible_solutions", []),
        "honest_notice": comp_report.get("honest_notice", ""),
    }

    # Write pair_meta.json to both run directories for standalone offline replay
    for d in (ctrl_dir, trt_dir):
        (d / "pair_meta.json").write_text(
            json.dumps(pair_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    return pair_manifest
