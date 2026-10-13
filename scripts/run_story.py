"""Run the school and write a playback pack.

  python scripts/run_story.py                                  # the story as written (anchor mode)
  python scripts/run_story.py --overview config/overview.generate.json --out pack/generated
  python scripts/run_story.py --mode generate --seed 7 --intensity 1.3 --random-events 2
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schooltwin.engine import Engine
from schooltwin.evaluate import evaluate
from schooltwin.overview import load
from schooltwin.pack import Packer

ap = argparse.ArgumentParser()
ap.add_argument("--overview", help="JSON overview file (see config/overview.example.json)")
ap.add_argument("--out", default=None, help="pack folder (default pack/<name>)")
ap.add_argument("--name", default=None)
ap.add_argument("--mode", choices=["anchor", "generate"])
ap.add_argument("--seed", type=int)
ap.add_argument("--intensity", type=float, help="scales randomness (1.0 = the story's own wobble)")
ap.add_argument("--random-events", type=float, help="extra random events per month")
ap.add_argument("--days", type=int, help="stop after this many calendar days")
ap.add_argument("--redact", action="store_true", help="operator-only pack: no hidden traits or causes")
args = ap.parse_args()

ov = load(args.overview)
if args.name: ov["name"] = args.name
if args.mode: ov["mode"] = args.mode
if args.seed is not None: ov["seed"] = args.seed
if args.intensity is not None: ov["randomness"]["intensity"] = args.intensity
if args.random_events is not None: ov["events"]["random"]["per_month"] = args.random_events
if args.days: ov["end_day"] = min(ov["end_day"], args.days - 1)
out = Path(args.out or f"pack/{ov['name']}")
if not out.is_absolute():
    out = Path(__file__).resolve().parent.parent / out

t0 = time.time()
eng = Engine(ov)
pk = Packer(eng, out, redact=args.redact)
eng.run(on_day=pk.on_day, progress=lambda i, n: print(f"\r  day {i + 1}/{n + 1}", end="", flush=True) if i % 10 == 0 or i == n else None)
ev = evaluate(eng)
pk.finalize(ev)
print(f"\nrun '{ov['name']}' ({ov['mode']}): {len(eng.days)} days in {time.time() - t0:.0f}s -> {out}")
d = ev["detection"]["engine"]
print(f"  attendance MAE vs story {ev['attendance_mae_pts']} pts | cash diff {ev['closing_cash_diff_pct']}% | detector {d['flagged']}/{d['total']} events, {d['false_alarm_days']} false-alarm days")
size = sum(p.stat().st_size for p in out.rglob("*.json")) / 1e6
print(f"  pack size {size:.1f} MB uncompressed")
