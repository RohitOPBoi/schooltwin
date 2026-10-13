"""Performance Benchmark Suite for SchoolTwin.

Measures baseline loading, 3-month (90-day) scenario simulation, result packing,
and persistence against the 15-30 second target.
"""
import json
import os
import platform
import tempfile
import time
from pathlib import Path

from .config import ROOT
from .engine import Engine
from .evaluate import evaluate
from .pack import Packer


def run_benchmark(days_to_run: int = 90, seed: int = 20261014) -> dict:
    """Runs a measured 3-month scenario execution benchmark."""
    print("=" * 60)
    print("  SCHOOLTWIN PERFORMANCE BENCHMARK (3-MONTH HORIZON)")
    print("=" * 60)

    # 1. Environment Info
    env_info = {
        "os": platform.system(),
        "release": platform.release(),
        "python_version": platform.python_version(),
        "processor": platform.processor() or "x86_64",
    }
    print(f"System: {env_info['os']} {env_info['release']} | Python {env_info['python_version']}")

    # 2. Baseline Loading Benchmark
    t_load_start = time.perf_counter()
    base_dir = ROOT / "pack" / "story_baseline"
    meta = json.loads((base_dir / "meta.json").read_text(encoding="utf-8"))
    hist = json.loads((base_dir / "history.json").read_text(encoding="utf-8"))
    t_load_end = time.perf_counter()
    load_time = t_load_end - t_load_start
    print(f"[1/3] Baseline loading time: {load_time * 1000:.2f} ms ({len(meta['people'])} people, {len(meta['days'])} days)")

    # 3. 3-Month Scenario Simulation Benchmark (Phase 3 Causal Engine)
    # 90 calendar days is approx 3 months (Jan 1 to Apr 1)
    ov = {
        "name": "benchmark_3month",
        "mode": "generate",
        "seed": seed,
        "start_day": 0,
        "end_day": days_to_run - 1,
        "randomness": {"intensity": 1.0},
        "events": {
            "use_story_events": True,
            "disable": [],
            "add": [
                {
                    "type": "serious_student_fight",
                    "day": 7,
                    "date": "2026-01-07",
                    "student_ids": ["STU-0012", "STU-0015", "STU-0021"],
                    "location": "playground",
                    "severity": "high",
                },
                {
                    "type": "teacher_resignation_notice",
                    "day": 20,
                    "date": "2026-01-20",
                    "teacher_name": "Ritu Kapoor",
                    "effective_date": "2026-02-15",
                },
                {
                    "type": "bus_breakdown",
                    "day": 15,
                    "date": "2026-01-15",
                    "route_number": 3,
                    "repair_cost_inr": 15000,
                    "repair_days": 2,
                },
                {
                    "type": "school_fee_increase",
                    "day": 10,
                    "date": "2026-01-10",
                    "fee_category": "tuition",
                    "delta_pct": 10.0,
                },
                {
                    "type": "additional_teacher_hired",
                    "day": 32,
                    "date": "2026-02-01",
                    "teacher_name": "Pooja Sharma",
                    "subject_or_role": "Science",
                    "salary_monthly_inr": 50000,
                },
            ],
            "random": {"per_month": 0, "types": []},
        },
        "policies": {
            "additional_teachers": 1,
            "tuition_fee_delta_pct": 10.0,
            "fee_change_approved": True,
            "attendance_support_budget_inr_per_month": 50000,
            "bus_backup_capacity": 1,
            "instructional_effectiveness": 1.05,
            "assessment_difficulty": 1.0,
        },
        "patches": [],
    }

    t_init_start = time.perf_counter()
    eng = Engine(ov)
    t_init_end = time.perf_counter()
    init_time = t_init_end - t_init_start

    tmp_dir = ROOT / "pack" / "benchmark_3month"
    packer = Packer(eng, tmp_dir)

    t_sim_start = time.perf_counter()
    eng.run(on_day=packer.on_day)
    t_sim_end = time.perf_counter()
    sim_time = t_sim_end - t_sim_start

    # 4. Finalize & Pack Persistence Benchmark
    t_pack_start = time.perf_counter()
    packer.finalize(evaluate(eng))
    t_pack_end = time.perf_counter()
    pack_time = t_pack_end - t_pack_start

    # 5. Causal Comparison Report Generation Benchmark
    from .compare import compare_runs
    t_cmp_start = time.perf_counter()
    cmp_rep = compare_runs("story_baseline", "benchmark_3month")
    t_cmp_end = time.perf_counter()
    cmp_time = t_cmp_end - t_cmp_start

    total_scenario_time = init_time + sim_time + pack_time + cmp_time

    target_min, target_max = 15.0, 30.0
    within_target = total_scenario_time <= target_max

    print(f"[2/4] Engine initialization: {init_time:.2f} s")
    print(f"[3/4] Scenario simulation ({days_to_run} days): {sim_time:.2f} s")
    print(f"      Cognitive Population: {len(eng.cognitive.states)} agents tracked ({len(eng.agent_decisions)} decisions evaluated)")
    print(f"[4/4] Packer & persistence: {pack_time:.2f} s")
    print(f"      Causal comparison & audit trail: {cmp_time * 1000:.2f} ms")
    print("-" * 60)
    print(f"TOTAL 3-MONTH SCENARIO RUNTIME: {total_scenario_time:.2f} seconds")
    print(f"Target Window: 15–30 seconds | Status: {'TARGET ACHIEVED' if within_target else 'EXCEEDED'}")
    print("=" * 60)

    return {
        "env": env_info,
        "days_simulated": days_to_run,
        "load_baseline_ms": round(load_time * 1000, 2),
        "engine_init_sec": round(init_time, 2),
        "sim_execution_sec": round(sim_time, 2),
        "packing_sec": round(pack_time, 2),
        "total_runtime_sec": round(total_scenario_time, 2),
        "target_range_sec": [target_min, target_max],
        "target_achieved": within_target,
    }


if __name__ == "__main__":
    run_benchmark()
