"""Serve the player and let it run scenarios.   python scripts/serve.py   ->  http://localhost:8765

Standard library only. Static files come from player/ and pack/.
API calls:
  GET  /api/status          is a run in progress, and where is it
  POST /api/run             {"overview": {...}}  start a run and write a new pack
  GET/POST /api/flags       read / save the flags you add in the player
  GET  /api/checkpoints     list pre-configured baseline checkpoints
  GET  /api/catalog         supported events and policies metadata
  GET  /api/scenarios       list saved user scenarios
  GET  /api/scenarios/<id>  retrieve specific scenario
  POST /api/scenarios       save and validate a scenario
  POST /api/scenarios/duplicate duplicate a scenario
  POST /api/scenarios/delete    delete a scenario (protects baseline)
  POST /api/parse_prompt    parse natural language prompt (Ollama + fallback)
  GET  /api/compare         compare baseline and scenario run outputs
  POST /api/export          export scenario JSON
  POST /api/import          import scenario JSON
"""
import argparse
import gzip
import json
import mimetypes
import re
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATE = {"running": False, "day": 0, "total": 0, "error": None, "name": None}
LOCK = threading.Lock()
GZ = {}


def run_job(ov, redact):
    from schooltwin.baseline_manifest import assert_baseline_intact, check_write_allowed
    from schooltwin.engine import Engine
    from schooltwin.evaluate import evaluate
    from schooltwin.pack import Packer
    try:
        assert_baseline_intact()
        out = ROOT / "pack" / ov["name"]
        check_write_allowed(out)
        eng = Engine(ov)
        pk = Packer(eng, out, redact=redact)
        STATE.update(total=ov["end_day"] + 1, day=0)
        eng.run(on_day=pk.on_day, progress=lambda i, n: STATE.update(day=i + 1))
        pk.finalize(evaluate(eng))
    except Exception as e:
        traceback.print_exc()
        STATE["error"] = str(e)
    finally:
        STATE["running"] = False


PAIR_STATE = {
    "running": False,
    "pair_id": None,
    "branch": "idle",
    "day": 0,
    "total": 0,
    "error": None,
    "result": None,
}


def run_paired_job(body):
    from schooltwin.paired_simulation import run_paired_simulation
    try:
        def prog_cb(branch, d, total):
            with LOCK:
                PAIR_STATE.update(branch=branch, day=d, total=total)

        res = run_paired_simulation(
            custom_event=body.get("custom_event", {}),
            start_day=int(body.get("start_day", 151)),
            duration_days=int(body.get("duration_days", 30)),
            profile_name=str(body.get("profile", "balanced")),
            seed=int(body.get("seed", 20261014)),
            custom_cfg=body.get("custom_cfg"),
            levers=body.get("levers"),
            scenario_name=body.get("scenario_name"),
            progress_cb=prog_cb,
        )
        with LOCK:
            PAIR_STATE.update(running=False, result=res, branch="completed")
    except Exception as e:
        traceback.print_exc()
        with LOCK:
            PAIR_STATE.update(running=False, error=str(e), branch="failed")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == "/api/status":
            return self._json(200, dict(STATE))

        if u.path == "/api/flags":
            run = re.sub(r"[^A-Za-z0-9_-]", "", parse_qs(u.query).get("run", [""])[0])
            f = ROOT / "pack" / run / "user_flags.json"
            return self._json(200, json.loads(f.read_text(encoding="utf-8")) if f.exists() else [])

        if u.path == "/api/checkpoints":
            from schooltwin.checkpoints import list_checkpoints
            return self._json(200, {"ok": True, "checkpoints": list_checkpoints()})

        if u.path == "/api/catalog":
            from schooltwin.schema import EVENT_CATALOG, POLICY_DEFINITIONS
            return self._json(200, {"ok": True, "events": EVENT_CATALOG, "policies": POLICY_DEFINITIONS})

        if u.path == "/api/scenarios":
            from schooltwin.scenario_store import list_scenarios
            return self._json(200, {"ok": True, "scenarios": list_scenarios()})

        if u.path.startswith("/api/scenarios/"):
            scen_id = u.path[len("/api/scenarios/"):]
            from schooltwin.scenario_store import get_scenario
            data = get_scenario(scen_id)
            if not data:
                return self._json(404, {"ok": False, "error": "Scenario not found"})
            return self._json(200, {"ok": True, "scenario": data})

        if u.path == "/api/scenario_timing":
            params = parse_qs(u.query)
            parent = params.get("parent", ["story_baseline"])[0]
            try:
                duration = int(params.get("duration", [30])[0])
            except Exception:
                duration = 30
            from schooltwin.schema import calculate_scenario_start_from_baseline
            timing = calculate_scenario_start_from_baseline(parent, duration)
            return self._json(200, {"ok": True, "timing": timing})

        if u.path == "/api/compare":
            params = parse_qs(u.query)
            base_id = params.get("base", ["story_baseline"])[0]
            scen_id = params.get("scen", [""])[0]
            if not scen_id:
                return self._json(400, {"ok": False, "error": "Query param 'scen' is required"})
            try:
                from schooltwin.compare import compare_runs
                report = compare_runs(base_id, scen_id)
                return self._json(200, {"ok": True, "report": report})
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)})

        if u.path == "/api/pair/profiles":
            from schooltwin.random_scheduler import RANDOM_PROFILES
            return self._json(200, {"ok": True, "profiles": RANDOM_PROFILES})

        if u.path == "/api/pair/status":
            with LOCK:
                return self._json(200, {"ok": True, **PAIR_STATE})

        if u.path == "/api/pair/meta":
            params = parse_qs(u.query)
            run_id = params.get("run", [""])[0]
            if not run_id:
                return self._json(400, {"ok": False, "error": "Query param 'run' is required"})
            pair_f = ROOT / "pack" / run_id / "pair_meta.json"
            if pair_f.is_file():
                return self._json(200, {"ok": True, "pair_meta": json.loads(pair_f.read_text(encoding="utf-8"))})
            return self._json(404, {"ok": False, "error": "pair_meta.json not found for run"})

        # Static file delivery
        rel = u.path.lstrip("/") or "index.html"
        if rel == "docs" or rel.startswith("docs/"):
            base = ROOT / "docs"
            sub = rel[5:] if rel.startswith("docs/") else ""
            f = (base / (sub or "index.html")).resolve()
        elif rel.startswith("assets/"):
            base = ROOT / "assets"
            f = (base / rel[7:]).resolve()
        elif rel.startswith("pack/"):
            base = ROOT / "pack"
            if rel == "pack/story_baseline/user_flags.json" and (ROOT / "pack" / "user_flags_baseline.json").is_file():
                f = (ROOT / "pack" / "user_flags_baseline.json").resolve()
            else:
                f = (base / rel[5:]).resolve()
            if not f.is_file() and "/days/d" in rel:
                m_day = re.search(r"/days/(d\d{4}\.json)$", rel)
                if m_day:
                    cand_base = (ROOT / "pack" / "story_baseline" / "days" / m_day.group(1)).resolve()
                    if cand_base.is_file():
                        f = cand_base
        else:
            base = ROOT / "player"
            f = (base / rel).resolve()
            if f.is_dir():
                f = (f / "index.html").resolve()
        if (base.resolve() not in f.parents and ROOT / "pack" / "story_baseline" / "days" not in f.parents and f != base.resolve()) or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        data = f.read_bytes()
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        extra = {}
        if f.suffix == ".json" and "gzip" in self.headers.get("Accept-Encoding", "") and len(data) > 2000:
            key = (str(f), f.stat().st_mtime)
            GZ[key] = GZ.get(key) or gzip.compress(data, 5)
            data, extra = GZ[key], {"Content-Encoding": "gzip"}
        self._send(200, data, ctype, extra)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 2_000_000:
            return self._json(413, {"ok": False, "error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"ok": False, "error": "bad json"})

        if self.path == "/api/run":
            from schooltwin.overview import load
            ov = load(body.get("overview"))
            ov["name"] = re.sub(r"[^A-Za-z0-9_-]", "_", ov["name"])[:60] or "scenario"

            # Enforce baseline immutability: protected baseline run can NEVER be overwritten
            if ov["name"] == "story_baseline":
                return self._json(403, {"ok": False, "error": "Protected baseline 'story_baseline' cannot be overwritten"})

            with LOCK:
                if STATE["running"]:
                    return self._json(409, {"ok": False, "error": "a run is already in progress"})
                STATE.update(running=True, error=None, name=ov["name"], day=0)
            threading.Thread(target=run_job, args=(ov, bool(body.get("redact"))), daemon=True).start()
            return self._json(200, {"ok": True, "name": ov["name"]})

        if self.path == "/api/pair/run":
            custom_event = body.get("custom_event")
            if not custom_event:
                return self._json(400, {"ok": False, "error": "custom_event is required"})
            with LOCK:
                if PAIR_STATE["running"]:
                    return self._json(409, {"ok": False, "error": "a paired simulation is already running"})
                PAIR_STATE.update(running=True, error=None, result=None, branch="starting", day=0, total=int(body.get("duration_days", 30)))
            threading.Thread(target=run_paired_job, args=(body,), daemon=True).start()
            return self._json(200, {"ok": True, "message": "Paired simulation started"})

        if self.path == "/api/flags":
            run = re.sub(r"[^A-Za-z0-9_-]", "", str(body.get("run", "")))
            if not run or not (ROOT / "pack" / run).is_dir():
                return self._json(404, {"ok": False})
            if run == "story_baseline":
                f = ROOT / "pack" / "user_flags_baseline.json"
            else:
                f = ROOT / "pack" / run / "user_flags.json"
            cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
            cur = [x for x in cur if x.get("id") != body["flag"].get("id")] + [body["flag"]]
            f.write_text(json.dumps(cur), encoding="utf-8")
            return self._json(200, {"ok": True})

        if self.path == "/api/scenarios":
            from schooltwin.scenario_store import save_scenario
            ok, saved, errs = save_scenario(body.get("scenario", body))
            if not ok:
                return self._json(400, {"ok": False, "errors": errs})
            return self._json(200, {"ok": True, "scenario": saved})

        if self.path == "/api/scenarios/duplicate":
            from schooltwin.scenario_store import duplicate_scenario
            scen_id = body.get("scenario_id")
            new_name = body.get("new_name")
            ok, dup, errs = duplicate_scenario(scen_id, new_name)
            if not ok:
                return self._json(400, {"ok": False, "errors": errs})
            return self._json(200, {"ok": True, "scenario": dup})

        if self.path == "/api/scenarios/delete":
            from schooltwin.scenario_store import delete_scenario
            scen_id = body.get("scenario_id")
            ok, err = delete_scenario(scen_id)
            if not ok:
                return self._json(400, {"ok": False, "error": err})
            return self._json(200, {"ok": True})

        if self.path == "/api/parse_prompt":
            from schooltwin.nlp import parse_scenario_prompt
            prompt = body.get("prompt", "")
            if not prompt or not isinstance(prompt, str) or not prompt.strip():
                return self._json(400, {"ok": False, "error": "Prompt string is required"})
            start_day = int(body.get("start_day", 151))
            duration_days = int(body.get("duration_days", 30))
            reopening_date = str(body.get("reopening_date", "2026-07-01"))
            end_day = int(body["end_day"]) if "end_day" in body and body["end_day"] is not None else None
            parsed = parse_scenario_prompt(
                prompt.strip(),
                start_day=start_day,
                duration_days=duration_days,
                reopening_date=reopening_date,
                end_day=end_day,
            )
            return self._json(200, {"ok": True, "parsed": parsed})

        if self.path == "/api/export":
            from schooltwin.scenario_store import export_scenario_json
            scen_id = body.get("scenario_id")
            text = export_scenario_json(scen_id)
            if not text:
                return self._json(404, {"ok": False, "error": "Scenario not found"})
            return self._json(200, {"ok": True, "json_text": text})

        if self.path == "/api/import":
            from schooltwin.scenario_store import import_scenario_json
            json_text = body.get("json_text", "")
            ok, imported, errs = import_scenario_json(json_text)
            if not ok:
                return self._json(400, {"ok": False, "errors": errs})
            return self._json(200, {"ok": True, "scenario": imported})

        self._json(404, {"ok": False})


if __name__ == "__main__":
    from schooltwin.baseline_manifest import assert_baseline_intact
    assert_baseline_intact()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"SchoolTwin player: http://{a.host}:{a.port}   (Ctrl+C to stop)")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
