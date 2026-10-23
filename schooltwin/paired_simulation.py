"""Paired Simulation Orchestrator for SchoolTwin (Part B, C, F, H, I).

When a user adds a custom event, this orchestrator runs two matched future simulations:
- Simulation A (Control): Continues from baseline endpoint with pre-generated background events, WITHOUT the custom event.
- Simulation B (Treatment): Continues from baseline endpoint with the exact same pre-generated background events, WITH the custom event.

Core Invariants:
1. Baseline Immutability: 'story_baseline' is never modified, deleted, or overwritten.
2. Fair Comparison: Both branches share the identical background random-event schedule.
3. Isolated RNG: Random seeds are isolated so branches do not drift unpredictably.
4. Independent Mutable State: Engines, ledgers, cognitive states, and incident registers are isolated.
5. Honest Modeling: Statuses are labeled Computed, Shared event, Custom event, Branch consequence, Configured, Not modeled, or Unavailable.
"""
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
from .story import Story


def make_pair_id(custom_event: Dict[str, Any], profile_name: str, seed: int) -> str:
    """Creates a deterministic, URL-safe identifier for a comparison pair."""
    ev_type = str(custom_event.get("type", "custom"))[:12]
    ev_date = str(custom_event.get("date", "2026-06-01")).replace("-", "")
    h = hashlib.sha256(f"{ev_type}:{ev_date}:{profile_name}:{seed}".encode("utf-8")).hexdigest()[:6]
    clean_type = re.sub(r"[^a-zA-Z0-9_]", "_", ev_type).lower()
    return f"{clean_type}_{ev_date}_{h}"


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

    # 1. Pre-generate canonical background schedule shared by both branches
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

    # 2. Configure Simulation A: Control
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

    # 3. Configure Simulation B: Treatment
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

    # 4. Execute Simulation A (Control)
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

    # 5. Execute Simulation B (Treatment)
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

    # 6. Compute Paired Delta Report
    comp_report = compare_runs(ctrl_run_name, trt_run_name)

    # Classify comparison metrics honestly
    classified_metrics = []
    for m in comp_report.get("metrics", []):
        m_entry = dict(m)
        m_id = m.get("id")
        if m.get("label") == "Computed":
            m_entry["status_tag"] = "Computed"
        elif m.get("label") == "Configured":
            m_entry["status_tag"] = "Configured"
        elif m.get("label") == "Not modeled":
            m_entry["status_tag"] = "Not modeled"
        else:
            m_entry["status_tag"] = m.get("label", "Unavailable")
        classified_metrics.append(m_entry)

    comp_report["metrics"] = classified_metrics

    # 7. Package Paired Manifest
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
