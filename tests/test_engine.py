"""Run:  python tests/test_engine.py     (about 70 seconds: it simulates a full term once and a few short runs)

Checks what matters: the engine reproduces the story, every event does what it should, runs are repeatable,
forking leaves the past alone, and the operator never sees the hidden answer key.
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schooltwin.engine import Engine
from schooltwin.evaluate import evaluate
from schooltwin.pack import Packer
from schooltwin.story import Story


class TestEngineSmoke(unittest.TestCase):
    """Fast engine smoke test for standard test discovery."""

    def test_engine_smoke(self):
        e = Engine({"start_day": 11, "end_day": 11, "mode": "anchor"})
        days = e.run()
        self.assertEqual(len(days), 1)
        self.assertTrue(days[0]["open"])
        self.assertGreater(days[0]["present"], 800)


def run_full_suite():
    ok = lambda msg: print("  ok  ", msg)
    S = Story()
    idx = {d: i for i, d in enumerate(S.dates)}
    t0 = time.time()

    # ------------------------------------------------------------ 1. anchor mode reproduces the story
    E = Engine()
    E.run()
    ev = evaluate(E)
    assert ev["attendance_mae_pts"] == 0.0 and ev["late_mae"] == 0, "anchor mode must follow the story's attendance exactly"
    assert abs(ev["closing_cash_diff_pct"]) < 0.01
    ok(f"anchor mode: attendance, lateness and closing cash match the story ({len(E.days)} days)")
    d = ev["detection"]["engine"]
    assert d["flagged"] >= 17, f"detector should flag nearly all hidden events, got {d['flagged']}/18"
    assert d["false_alarm_days"] <= 14
    ok(f"detector flags {d['flagged']}/18 hidden events with {d['false_alarm_days']} false-alarm days (story's own: 7)")
    cams = {c["camera"]: c["diff_pct"] for c in ev["camera_fidelity"]}
    for cam in ("CAM-GATE-A", "CAM-GATE-B", "CAM-LIBRARY", "CAM-GROUND"):
        assert abs(cams[cam]) <= 15, (cam, cams[cam])
    ok("gate, bus bay, library and ground counters are within 15% of the story's")

    # ------------------------------------------------------------ 2. realism invariants over the whole term
    op = [x for x in E.days if x["open"]]
    assert all(0.8 < x["attendance_rate"] < 0.99 for x in op)
    assert 0.02 < np.mean([x["mood_low_share"] for x in op]) < 0.15, "some students should be low on any day, but not most"
    assert np.mean([x["caught"] for x in op]) < 8, "hidden-area activity must stay rare"
    ok("attendance realistic; low mood present but not dominant; hidden-area activity rare")

    # ------------------------------------------------------------ 3. events do what they say (one day at a time)
    def day_engine(date, **ov):
        e = Engine(dict({"start_day": idx[date], "end_day": idx[date]}, **ov))
        e.step(idx[date])
        return e

    e = day_engine("2026-02-12")                                   # late buses
    late = [a for a in e.students if a.late_today]
    top3 = {r for r, _ in __import__("collections").Counter(a.route for a in late if a.route).most_common(3)}
    assert len(late) == S.by_date["2026-02-12"]["student_enrollment"]["late_arrivals"] > 100
    assert sum(1 for a in late if a.route) / len(late) > 0.95 and sum(1 for a in late if a.route in top3) / len(late) > 0.65
    ok(f"late-bus morning: {len(late)} latecomers, almost all bus riders, mostly from three routes")

    e = day_engine("2026-04-07")                                   # fans fail in 8B
    lib = e.world.index["library"]
    moved = [a for a in e.students if a.home_zone == "C8B" and any(z == lib and t >= 778 for t, z in zip(e.paths[a.id][0::2], e.paths[a.id][1::2]))]
    assert len(moved) >= 15, f"8B should move to the library, only {len(moved)} did"
    ok(f"fan failure: {len(moved)} students of 8B move to the library mid-period")

    e = day_engine("2026-05-08")                                   # lab circuit trips
    assert "comp_lab_1" in e.closed
    assert any(r["camera_id"] == "CAM-COMP-1" and r["observed_count"] == 0 for r in e.cctv)
    ok("circuit trip: the lab closes and its counter reads zero")

    e = day_engine("2026-02-14")                                   # annual day
    assert any(a.role == "visitor" and a.id in e.paths and e.paths[a.id] for a in e.agents)
    ok("annual day: visitors appear on campus")

    e = day_engine("2026-05-25")                                   # water motor, school closed
    assert not any(e.paths[a.id] for a in e.students if a.id in e.paths) and any(a.subrole == "maintenance_gardener" and e.paths.get(a.id) for a in e.agents)
    ok("water motor failure on a closed day: only staff on campus, maintenance at work")

    e = day_engine("2026-05-20")                                   # after the resignation date
    ritu = next(a for a in e.agents if a.name == "Ritu Kapoor")
    assert not ritu.present_today
    ok("a teacher who resigned is gone after her last day")

    # ------------------------------------------------------------ 4. repeatable, and seeds matter in generate mode
    g1 = Engine({"mode": "generate", "seed": 5, "start_day": 20, "end_day": 40}); g1.run()
    g2 = Engine({"mode": "generate", "seed": 5, "start_day": 20, "end_day": 40}); g2.run()
    g3 = Engine({"mode": "generate", "seed": 6, "start_day": 20, "end_day": 40}); g3.run()
    key = lambda eng: [(x["present"], x["late"], x["teachers_absent"]) for x in eng.days]
    assert key(g1) == key(g2), "same seed and settings must give the same school"
    assert key(g1) != key(g3), "a different seed should give a different term"
    ok("same seed => identical run; different seed => different run")

    # ------------------------------------------------------------ 5. forking leaves the past alone
    base = Engine({"end_day": 70}); base.run()
    fork = Engine({"end_day": 70, "patches": [{"from_day": 60, "mode": "generate", "levers": {"tuition_fee_delta_pct": 10, "fee_change_approved": True, "additional_teachers": 3}}]})
    fork.run()
    same = [(a["present"], a["late"], a["finance"]["cash"]) for a in base.days[:60]] == [(a["present"], a["late"], a["finance"]["cash"]) for a in fork.days[:60]]
    assert same, "days before the fork must be identical to the original"
    assert fork.days[70]["finance"]["cash"] != base.days[70]["finance"]["cash"], "after the fork the future must differ"
    assert any(a.sid.startswith("STF-X") for a in fork.agents)
    ok("fork on day 61: the first 60 days are identical; the future differs; extra teachers hired")

    # ------------------------------------------------------------ 6. the operator never sees the answer key
    tmp = Path(tempfile.mkdtemp())
    short = Engine({"start_day": 30, "end_day": 40}); pk = Packer(short, tmp / "blind", redact=True)
    short.run(on_day=pk.on_day); pk.finalize(evaluate(short))
    meta = json.loads((tmp / "blind" / "meta.json").read_text(encoding="utf-8"))
    assert "evaluation" not in meta and not any(f["vis"] == "author" for f in meta["flags"])
    assert all("att" not in p and "disc" not in p and "acad" not in p for p in meta["people"])
    assert all(d["events"] == [] for d in meta["days"])
    ok("redacted pack: no hidden traits, no hidden causes, no scores")
    full = Engine({"start_day": 30, "end_day": 40}); pk2 = Packer(full, tmp / "open"); full.run(on_day=pk2.on_day); pk2.finalize(evaluate(full))
    m2 = json.loads((tmp / "open" / "meta.json").read_text(encoding="utf-8"))
    assert any(f["vis"] == "author" for f in m2["flags"]) and "att" in m2["people"][0]
    ok("full pack: author view data present")

    # ------------------------------------------------------------ 7. pack decodes: every path points at a real zone, in time order
    day = json.loads(next((tmp / "open" / "days").glob("d003*.json")).read_text(encoding="utf-8"))
    nz = len(m2["zones"])
    for aid, arr in day["paths"].items():
        ts, zs = arr[0::2], arr[1::2]
        assert ts == sorted(ts) and all(-1 <= z < nz for z in zs), aid
    ok("pack paths are time-ordered and point at real zones")
    print(f"\nall engine tests passed in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    run_full_suite()
