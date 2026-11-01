"""Runs paired control and treatment simulations under matching background schedules.

Supports:
- Single matched pair (Quick Mode).
- Five matched pairs (Standard Mode) with keyed deterministic PRNG streams.
- Arbitrary baseline checkpoints (Days 0, 30, 60, 90, 120, 150).
- Dynamic duration (1 month, 5 months, 6 months, custom days/months up to Day 365).
- Zero silent date truncation (ExtensionCalendar is authoritative).
- Strict baseline immutability.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .baseline_manifest import assert_baseline_intact, check_write_allowed
from .checkpoints import get_checkpoint
from .compare import compare_runs
from .config import ROOT
from .engine import Engine
from .evaluate import evaluate
from .metrics_service import aggregate_five_pair_metrics, compute_comparison_payload
from .overview import DEFAULT, load
from .pack import Packer
from .random_scheduler import generate_paired_background_schedule, get_profile_config
from .report import generate_impact_report
from .schema import day_for_date, validate_paired_custom_event
from .snapshots import SNAPSHOTS_DIR
from .story import Story

_VALID_STATUS_TAGS = ("Computed", "Configured", "Not modeled", "Unavailable")


def make_pair_id(custom_event: Dict[str, Any], profile_name: str, seed: int, rep_idx: int = 1) -> str:
    """Creates a deterministic, URL-safe identifier for a comparison pair."""
    ev_type = str(custom_event.get("type", "custom"))[:12]
    ev_date = str(custom_event.get("date", "2026-06-01")).replace("-", "")
    content = json.dumps(
        {
            "type": custom_event.get("type"),
            "date": custom_event.get("date"),
            "severity": custom_event.get("severity", "medium"),
            "params": custom_event.get("params", {}),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    h = hashlib.sha256(f"{content}:{profile_name}:{seed}:rep{rep_idx}".encode("utf-8")).hexdigest()[:6]
    clean_type = re.sub(r"[^a-zA-Z0-9_]", "_", ev_type).lower()
    suffix = f"_r{rep_idx}" if rep_idx > 1 else ""
    return f"{clean_type}_{ev_date}_{h}{suffix}"


def build_event_day_impact(
    ctrl_days: List[Dict[str, Any]],
    trt_days: List[Dict[str, Any]],
    custom_event: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Day-level control-vs-treatment comparison for the intervention date."""
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
        "note": "Intervention date localized outcome: Control vs Treatment.",
    }


def classify_metric_status(metric: Dict[str, Any]) -> str:
    """Maps comparison metric to its honest display status tag."""
    status = metric.get("status")
    return status if status in _VALID_STATUS_TAGS else "Unavailable"


def classify_comparison_metrics(comp_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Returns a report's metrics, each annotated with an honest status tag."""
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
    checkpoint_id: Optional[str] = None,
    replication_index: int = 1,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    """Runs a single paired Control vs Treatment simulation from the selected checkpoint."""
    assert_baseline_intact()

    story = Story()

    # Resolve Checkpoint and Horizon (Part 4.8 & Part 5.1)
    ckpt = get_checkpoint(checkpoint_id) if checkpoint_id else None
    if ckpt:
        resolved_ckpt_id = ckpt.checkpoint_id
        branch_point = ckpt.day
        # If default start_day was passed but earlier checkpoint selected, branch from checkpoint
        if start_day == 151 and ckpt.day != 150:
            start_day = ckpt.day + 1
    else:
        resolved_ckpt_id = "CKPT-DAY-150-TERM-CLOSE" if start_day >= 151 else "CKPT-DAY-00-OPENING"
        branch_point = 150 if start_day >= 151 else 0

    # Ensure snapshot path exists
    snap_cand = SNAPSHOTS_DIR / f"{resolved_ckpt_id}.json.gz"
    resolved_snap_path = str(snap_cand) if snap_cand.is_file() else None

    # Ensure duration covers custom event date if specified
    ev_date = custom_event.get("date")
    if ev_date:
        ev_day = day_for_date(ev_date)
        if ev_day is not None and ev_day >= start_day:
            min_needed = (ev_day - start_day + 1) + 5
            if duration_days < min_needed:
                duration_days = min(364 - start_day + 1, min_needed)

    # Future calendar is authoritative: scenarios can run up to Day 364 without silent truncation
    end_day = min(364, start_day + duration_days - 1)

    # Validate custom event within active horizon
    v_ok, v_errors, v_warnings = validate_paired_custom_event(
        custom_event, start_day=start_day, end_day=end_day
    )
    if not v_ok:
        raise ValueError("Custom event validation failed: " + " | ".join(v_errors))

    pair_id = make_pair_id(custom_event, profile_name, seed, rep_idx=replication_index)
    ctrl_run_name = f"ctrl_{pair_id}"
    trt_run_name = (
        re.sub(r"[^A-Za-z0-9_-]", "_", scenario_name)[:60]
        if (scenario_name and scenario_name != "story_baseline" and replication_index == 1)
        else f"scen_{pair_id}"
    )

    # Protect historical baseline immutability
    if ctrl_run_name == "story_baseline" or trt_run_name == "story_baseline":
        raise ValueError("Cannot overwrite protected historical baseline 'story_baseline'")

    ctrl_dir = ROOT / "pack" / ctrl_run_name
    trt_dir = ROOT / "pack" / trt_run_name
    check_write_allowed(ctrl_dir)
    check_write_allowed(trt_dir)

    # Generate matched background schedule
    bg_schedule = generate_paired_background_schedule(
        story=story,
        start_day=start_day,
        duration_days=duration_days,
        profile_name=profile_name,
        seed=seed,
        custom_cfg=custom_cfg,
    )

    clean_custom = dict(custom_event)
    clean_custom.setdefault("source", "user")
    clean_custom.setdefault("severity", "medium")
    clean_custom.setdefault("params", {})
    if "id" not in clean_custom:
        clean_custom["id"] = f"EV-CUSTOM-{clean_custom.get('date', '2026-06-01')}-{clean_custom.get('type', 'custom')[:8]}"

    tagged_bg = []
    for ev in bg_schedule:
        tev = dict(ev)
        tev["comparison_tag"] = "shared_background"
        tagged_bg.append(tev)

    trt_custom = dict(clean_custom)
    trt_custom["comparison_tag"] = "custom_intervention"

    applied_levers = copy.deepcopy(DEFAULT["levers"])
    if levers:
        applied_levers.update(levers)

    ctrl_levers = copy.deepcopy(applied_levers)
    trt_levers = copy.deepcopy(applied_levers)

    # Treatment branch reflects custom intervention policy levers
    ev_type = clean_custom.get("type", "")
    ev_params = clean_custom.get("params", {})
    if ev_type == "school_fee_increase":
        pct = float(ev_params.get("delta_pct", clean_custom.get("delta_pct", 10.0)))
        trt_levers["fee_change_approved"] = True
        trt_levers["tuition_fee_delta_pct"] = pct
    elif ev_type == "additional_teacher_hired":
        trt_levers["additional_teachers"] = int(ev_params.get("count", clean_custom.get("count", 1)))

    ctrl_ov = {
        "name": ctrl_run_name,
        "mode": "generate",
        "start_day": start_day,
        "end_day": end_day,
        "seed": seed,
        "checkpoint_id": resolved_ckpt_id,
        "snapshot_path": resolved_snap_path,
        "randomness": {"intensity": 1.0},
        "events": {
            "use_story_events": True,
            "disable": [],
            "add": copy.deepcopy(tagged_bg),
            "random": {"per_month": 0, "types": []},
        },
        "levers": copy.deepcopy(ctrl_levers),
        "branch": {
            "branch_id": ctrl_run_name,
            "parent_id": "story_baseline",
            "branch_point_day": branch_point,
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
        "checkpoint_id": resolved_ckpt_id,
        "snapshot_path": resolved_snap_path,
        "randomness": {"intensity": 1.0},
        "events": {
            "use_story_events": True,
            "disable": [],
            "add": trt_events_add,
            "random": {"per_month": 0, "types": []},
        },
        "levers": copy.deepcopy(trt_levers),
        "branch": {
            "branch_id": trt_run_name,
            "parent_id": "story_baseline",
            "branch_point_day": branch_point,
            "branch_type": "treatment",
            "intervention_event_id": trt_custom["id"],
        },
    }

    total_days = end_day - start_day + 1

    if progress_cb:
        progress_cb(f"control_r{replication_index}", 0, total_days)

    ctrl_eng = Engine(ctrl_ov)
    ctrl_pk = Packer(ctrl_eng, ctrl_dir, redact=False)

    def on_ctrl_prog(step_idx, total):
        if progress_cb:
            progress_cb(f"control_r{replication_index}", step_idx - start_day + 1, total_days)

    try:
        ctrl_eng.run(on_day=ctrl_pk.on_day, progress=on_ctrl_prog)
        ctrl_eval = evaluate(ctrl_eng)
        ctrl_pk.finalize(ctrl_eval)

        if progress_cb:
            progress_cb(f"treatment_r{replication_index}", 0, total_days)

        trt_eng = Engine(trt_ov)
        trt_pk = Packer(trt_eng, trt_dir, redact=False)

        def on_trt_prog(step_idx, total):
            if progress_cb:
                progress_cb(f"treatment_r{replication_index}", step_idx - start_day + 1, total_days)

        trt_eng.run(on_day=trt_pk.on_day, progress=on_trt_prog)
        trt_eval = evaluate(trt_eng)
        trt_pk.finalize(trt_eval)
    except Exception:
        if ctrl_dir.is_dir() and not (ctrl_dir / "meta.json").is_file():
            shutil.rmtree(ctrl_dir, ignore_errors=True)
        if trt_dir.is_dir() and not (trt_dir / "meta.json").is_file():
            shutil.rmtree(trt_dir, ignore_errors=True)
        raise

    # Compare strictly over the active intervention window
    comp_report = compare_runs(ctrl_run_name, trt_run_name, window=(start_day, end_day))
    comp_report["metrics"] = classify_comparison_metrics(comp_report)

    pair_manifest = {
        "pair_id": pair_id,
        "replication_index": replication_index,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_run": ctrl_run_name,
        "treatment_run": trt_run_name,
        "checkpoint_id": resolved_ckpt_id,
        "branch_point_day": branch_point,
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

    # Persist pair_meta.json
    for d in (ctrl_dir, trt_dir):
        (d / "pair_meta.json").write_text(
            json.dumps(pair_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    # Generate canonical 13-section impact report for this treatment run
    generate_impact_report(trt_dir, control_pack_dir=ctrl_dir)

    return pair_manifest


def run_five_pair_experiment(
    custom_event: Dict[str, Any],
    start_day: int = 151,
    duration_days: int = 30,
    profile_name: str = "balanced",
    base_seed: int = 20261014,
    custom_cfg: Optional[Dict[str, Any]] = None,
    levers: Optional[Dict[str, Any]] = None,
    scenario_name: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
    replications_count: int = 5,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    """Runs a multi-pair matched experiment (Part 1 & Part 5: 1 pair quick, 5 pairs standard).

    Each replication uses a keyed deterministic seed derived from (base_seed, rep_idx).
    Both Control and Treatment within each replication receive the identical background schedule.
    Aggregates results into honest 5-pair distribution statistics.
    """
    assert_baseline_intact()

    reps = max(1, min(10, replications_count))
    pairs_results: List[Dict[str, Any]] = []

    for r in range(1, reps + 1):
        # Keyed deterministic seed derivation (Part 5.5)
        raw_key = f"{base_seed}:rep_{r}".encode("utf-8")
        rep_seed = int(hashlib.sha256(raw_key).hexdigest()[:8], 16)

        pair_res = run_paired_simulation(
            custom_event=custom_event,
            start_day=start_day,
            duration_days=duration_days,
            profile_name=profile_name,
            seed=rep_seed,
            custom_cfg=custom_cfg,
            levers=levers,
            scenario_name=f"{scenario_name}_r{r}" if scenario_name else None,
            checkpoint_id=checkpoint_id,
            replication_index=r,
            progress_cb=progress_cb,
        )
        pairs_results.append(pair_res)

    # Compute five-pair aggregated metrics (Part 12.2)
    agg_summary = aggregate_five_pair_metrics(pairs_results)

    # Primary representative pair is Pair 1
    primary_pair = pairs_results[0]
    trt_pack_dir = ROOT / "pack" / primary_pair["treatment_run"]
    ctrl_pack_dir = ROOT / "pack" / primary_pair["control_run"]

    # Re-generate report for primary treatment run with full 5-pair aggregation attached
    generate_impact_report(trt_pack_dir, control_pack_dir=ctrl_pack_dir, five_pair_summary=agg_summary)

    experiment_manifest = {
        "experiment_id": f"EXP-{primary_pair['pair_id']}",
        "replications_count": reps,
        "base_seed": base_seed,
        "profile": profile_name,
        "custom_event": primary_pair["custom_event"],
        "start_day": start_day,
        "end_day": primary_pair["end_day"],
        "duration_days": duration_days,
        "checkpoint_id": primary_pair["checkpoint_id"],
        "primary_pair": primary_pair,
        "pairs": pairs_results,
        "five_pair_aggregation": agg_summary,
    }

    # Save experiment_meta.json in primary run folders
    for d in (trt_pack_dir, ctrl_pack_dir):
        (d / "experiment_meta.json").write_text(
            json.dumps(experiment_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    return experiment_manifest
