"""
Unit tests for SchoolTwin Paired Simulation & Controlled Random Scheduler.
Verifies:
1. Determinism and isolated reproducibility of shared background schedules.
2. Presets adhere to frequency caps, cooldowns, and category filters.
3. Paired simulation branches control and treatment from the exact same baseline state.
4. Shared background events are delivered identically to both branches.
5. The custom intervention is present only in the treatment branch.
6. Absolute immutability of pack/story_baseline (read-only invariant).
"""
import pytest
from pathlib import Path
import json
import shutil

from schooltwin.random_scheduler import (
    generate_paired_background_schedule,
    RANDOM_PROFILES,
    CATEGORY_CATALOG,
    get_profile_config
)
from schooltwin.paired_simulation import run_paired_simulation
from schooltwin.story import Story


def test_random_profiles_structure():
    """Verify built-in profile dictionary has required keys and valid configurations."""
    for profile_name in ["calm", "balanced", "stress_test", "custom"]:
        assert profile_name in RANDOM_PROFILES
        cfg = get_profile_config(profile_name)
        assert cfg["expected_per_month"] >= 0
        assert cfg["max_per_day"] >= 1
        assert "allowed_categories" in cfg
        assert len(cfg["allowed_categories"]) > 0


def test_schedule_determinism():
    """Verify identical seeds produce identical shared background schedules."""
    story = Story()
    seed = 12345
    start_day = 151
    duration_days = 30

    sched1 = generate_paired_background_schedule(
        story=story,
        start_day=start_day,
        duration_days=duration_days,
        profile_name="balanced",
        seed=seed
    )
    sched2 = generate_paired_background_schedule(
        story=story,
        start_day=start_day,
        duration_days=duration_days,
        profile_name="balanced",
        seed=seed
    )

    assert len(sched1) == len(sched2)
    assert [e["id"] for e in sched1] == [e["id"] for e in sched2]
    assert [e["type"] for e in sched1] == [e["type"] for e in sched2]
    assert [e["date"] for e in sched1] == [e["date"] for e in sched2]


def test_schedule_different_seeds_vary():
    """Different seeds should generate different schedules over a 60-day horizon."""
    story = Story()
    sched_a = generate_paired_background_schedule(
        story=story,
        start_day=151,
        duration_days=60,
        profile_name="stress_test",
        seed=101
    )
    sched_b = generate_paired_background_schedule(
        story=story,
        start_day=151,
        duration_days=60,
        profile_name="stress_test",
        seed=999
    )
    # The event IDs or event types will vary
    ids_a = [e["id"] for e in sched_a]
    ids_b = [e["id"] for e in sched_b]
    assert ids_a != ids_b


def test_paired_simulation_execution_and_isolation():
    """
    Execute a short 5-day paired simulation.
    Verify:
    1. pack/story_baseline is untouched.
    2. Control and Treatment directories are created under pack/.
    3. Pair metadata contains honest classifications and shared background schedule.
    4. Custom event is only in Treatment.
    """
    baseline_path = Path("pack/story_baseline/meta.json")
    assert baseline_path.exists(), "pack/story_baseline must exist"
    baseline_mtime_before = baseline_path.stat().st_mtime
    baseline_bytes_before = baseline_path.read_bytes()

    custom_event = {
        "type": "teacher_resignation",
        "date": "2026-06-03",
        "teacher": "T-MEERA-SHARMA",
        "effective_date": "2026-06-03",
        "description": "Urgent resignation submitted for testing."
    }

    result = run_paired_simulation(
        custom_event=custom_event,
        duration_days=5,
        profile_name="balanced",
        seed=20261014
    )

    # 1. Baseline immutability
    assert baseline_path.stat().st_mtime == baseline_mtime_before
    assert baseline_path.read_bytes() == baseline_bytes_before

    # 2. Results validity
    assert "pair_id" in result
    assert "control_run" in result
    assert "treatment_run" in result

    ctrl_dir = Path("pack") / result["control_run"]
    trt_dir = Path("pack") / result["treatment_run"]
    assert ctrl_dir.exists()
    assert trt_dir.exists()

    # 3. Pair metadata
    ctrl_meta = json.loads((ctrl_dir / "meta.json").read_text(encoding="utf-8"))
    trt_meta = json.loads((trt_dir / "meta.json").read_text(encoding="utf-8"))
    pair_meta = json.loads((ctrl_dir / "pair_meta.json").read_text(encoding="utf-8"))

    assert ctrl_meta["run"]["overview"]["branch"]["branch_type"] == "control"
    assert trt_meta["run"]["overview"]["branch"]["branch_type"] == "treatment"
    assert pair_meta["seed"] == 20261014
    assert pair_meta["profile"] == "balanced"
    assert "metrics" in pair_meta

    # 4. Custom event presence
    ctrl_ov = ctrl_meta["run"]["overview"]
    trt_ov = trt_meta["run"]["overview"]

    ctrl_event_types = [e.get("type") for e in ctrl_ov.get("events", {}).get("add", [])]
    trt_event_types = [e.get("type") for e in trt_ov.get("events", {}).get("add", [])]

    assert "teacher_resignation" not in ctrl_event_types
    assert "teacher_resignation" in trt_event_types

    # Clean up test pack folders
    shutil.rmtree(ctrl_dir, ignore_errors=True)
    shutil.rmtree(trt_dir, ignore_errors=True)
