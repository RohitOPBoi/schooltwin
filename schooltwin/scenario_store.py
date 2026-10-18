"""Scenario Storage and Persistence for SchoolTwin.

Stores user scenarios in the 'scenarios/' directory as versioned JSON files.
Provides operations to list, load, save, duplicate, delete, export, and import scenarios.
Guarantees baseline immutability: protected baseline runs can never be overwritten or deleted.
"""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .checkpoints import BASELINE_RUN_ID
from .config import ROOT
from .schema import ScenarioConfig, validate_scenario

SCENARIO_DIR = ROOT / "scenarios"


def ensure_store() -> Path:
    """Ensures the scenarios directory exists."""
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    return SCENARIO_DIR


def list_scenarios() -> List[Dict[str, Any]]:
    """Lists all saved scenario configurations."""
    ensure_store()
    scenarios = []
    for f in sorted(SCENARIO_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            scenarios.append({
                "scenario_id": data.get("scenario_id", f.stem),
                "name": data.get("name", f.stem),
                "description": data.get("description", ""),
                "checkpoint_id": data.get("checkpoint_id"),
                "seed": data.get("seed", 20261014),
                "fork_day": data.get("fork_day"),
                "created_at": data.get("created_at"),
                "status": data.get("status", "draft"),
                "config_hash": data.get("config_hash", ""),
            })
        except Exception:
            continue
    return scenarios


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    """Loads a scenario by ID."""
    ensure_store()
    clean_id = re.sub(r"[^A-Za-z0-9_-]", "", scenario_id)
    f = SCENARIO_DIR / f"{clean_id}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def save_scenario(data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], List[str]]:
    """Validates and saves a scenario. Returns (success, saved_data, errors)."""
    ensure_store()

    # Protection rule
    name = str(data.get("name", "")).strip()
    if name == BASELINE_RUN_ID:
        return False, {}, ["Protected run 'story_baseline' cannot be overwritten"]

    is_valid, errors = validate_scenario(data)
    if not is_valid:
        return False, {}, errors

    scen_id = data.get("scenario_id")
    if not scen_id:
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:30] or "scenario"
        scen_id = f"SCEN-{slug}"
    else:
        scen_id = re.sub(r"[^A-Za-z0-9_-]", "", scen_id)

    cfg = ScenarioConfig(
        scenario_id=scen_id,
        name=name,
        description=str(data.get("description", "")),
        parent_run_id=str(data.get("parent_run_id", BASELINE_RUN_ID)),
        checkpoint_id=data.get("checkpoint_id"),
        start_day=int(data.get("start_day", 0)),
        end_day=int(data.get("end_day", 150)),
        fork_day=data.get("fork_day"),
        seed=int(data.get("seed", 20261014)),
        mode=str(data.get("mode", "generate")),
        randomness_intensity=float(data.get("randomness_intensity", 1.0)),
        use_story_events=bool(data.get("use_story_events", True)),
        disabled_story_events=list(data.get("disabled_story_events", [])),
        events=copy.deepcopy(data.get("events", [])),
        policy_overrides=copy.deepcopy(data.get("policy_overrides", {})),
        created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        status="validated",
    )

    out_dict = cfg.to_dict()
    f = SCENARIO_DIR / f"{scen_id}.json"
    f.write_text(json.dumps(out_dict, indent=2), encoding="utf-8")
    return True, out_dict, []


def duplicate_scenario(scenario_id: str, new_name: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """Duplicates an existing scenario with a new seed and identifier."""
    orig = get_scenario(scenario_id)
    if not orig:
        return False, None, [f"Scenario '{scenario_id}' not found"]

    dup = copy.deepcopy(orig)
    name = new_name or f"{orig.get('name', 'scenario')}_copy"
    dup["name"] = name
    dup["scenario_id"] = f"{orig.get('scenario_id', 'SCEN')}-copy"
    dup["seed"] = int(dup.get("seed", 20261014)) + 1
    dup["created_at"] = datetime.now(timezone.utc).isoformat()
    dup["status"] = "draft"

    return save_scenario(dup)


def delete_scenario(scenario_id: str) -> Tuple[bool, Optional[str]]:
    """Deletes a saved scenario. Protects baseline."""
    clean_id = re.sub(r"[^A-Za-z0-9_-]", "", scenario_id)
    if clean_id == BASELINE_RUN_ID or clean_id == "story_baseline":
        return False, "Cannot delete protected baseline run"

    f = SCENARIO_DIR / f"{clean_id}.json"
    if not f.exists():
        return False, "Scenario not found"
    f.unlink()
    return True, None


def export_scenario_json(scenario_id: str) -> Optional[str]:
    """Returns scenario JSON string for downloading."""
    scen = get_scenario(scenario_id)
    if not scen:
        return None
    return json.dumps(scen, indent=2)


def import_scenario_json(json_text: str) -> Tuple[bool, Dict[str, Any], List[str]]:
    """Parses and imports a scenario JSON string."""
    try:
        data = json.loads(json_text)
    except Exception as e:
        return False, {}, [f"Invalid JSON: {str(e)}"]

    return save_scenario(data)
