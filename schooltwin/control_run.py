"""Content-Addressed Control Run Generator for SchoolTwin.

Per Decision D3:
For any branch past Day 150 (or any branched scenario), the comparison partner is an
auto-generated, cached, immutable control continuation:
- Same extension calendar, seed, start day, and duration.
- Zero incidents/events added.
- Default neutral policy levers.
- Differences between scenario and control are strictly attributable to the incident/intervention.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .config import ROOT
from .engine import Engine
from .pack import Packer

DEFAULT_LEVERS = {
    "additional_teachers": 0,
    "attendance_support_budget_inr_per_month": 0,
    "bus_backup_capacity": 0,
    "tuition_fee_delta_pct": 0,
    "fee_change_approved": False,
    "transport_fee_delta_pct": 0,
    "summer_maintenance_budget_inr": 0,
    "autonomy_level": "low_risk_auto",
}


def compute_control_id(
    checkpoint_id: str,
    start_day: int,
    duration_days: int,
    seed: int,
    reopening_date: str = "2026-07-01",
) -> str:
    """Computes a deterministic content-addressed identifier for the control run."""
    key = f"{checkpoint_id}:{start_day}:{duration_days}:{seed}:{reopening_date}"
    chash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"ctrl_{chash}"


def get_or_create_control_run(
    checkpoint_id: str = "CKPT-DAY-150-TERM-CLOSE",
    start_day: int = 151,
    duration_days: int = 30,
    seed: int = 20261014,
    reopening_date: str = "2026-07-01",
    force_recreate: bool = False,
    on_progress: Optional[Any] = None,
) -> Tuple[str, Path]:
    """Returns (control_id, out_dir) of the cached or newly generated control run."""
    control_id = compute_control_id(checkpoint_id, start_day, duration_days, seed, reopening_date)
    out_dir = ROOT / "pack" / control_id
    meta_path = out_dir / "meta.json"

    if not force_recreate and meta_path.exists():
        return control_id, out_dir

    end_day = start_day + duration_days - 1

    ov = {
        "name": control_id,
        "mode": "generate",
        "seed": int(seed),
        "start_day": int(start_day),
        "end_day": int(end_day),
        "randomness": {"intensity": 1.0},
        "branch": {
            "checkpoint_id": checkpoint_id,
            "start_day": int(start_day),
            "duration_days": int(duration_days),
            "end_day": int(end_day),
            "reopening_date": reopening_date,
            "is_control": True,
        },
        "events": {
            "use_story_events": False,
            "disable": [],
            "add": [],
            "random": {"per_month": 0, "types": []},
        },
        "levers": copy.deepcopy(DEFAULT_LEVERS),
        "approvals": {},
        "patches": [],
    }

    engine = Engine(ov)
    packer = Packer(engine, out_dir, redact=False)

    def day_cb(i: int, res: Dict[str, Any]) -> None:
        packer.on_day(i, res)
        if on_progress:
            on_progress(i, end_day)

    engine.run(on_day=day_cb)
    packer.finalize()

    # Mark meta as control run
    try:
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        meta_data["is_control"] = True
        meta_data["control_for"] = {
            "checkpoint_id": checkpoint_id,
            "start_day": start_day,
            "duration_days": duration_days,
            "seed": seed,
            "reopening_date": reopening_date,
        }
        meta_path.write_text(json.dumps(meta_data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return control_id, out_dir
