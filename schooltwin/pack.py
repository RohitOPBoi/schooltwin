"""Playback pack: everything a browser needs to replay a run, with no server-side logic.

  pack/<run>/meta.json          the map, the people, the calendar, flags, alerts, decisions, evaluation
  pack/<run>/history.json       every person's mood and attendance for every day (for the inspector)
  pack/<run>/days/d0012.json    one file per school day: where everyone is at every minute, mood, counters

Paths are stored as flat [minute, zoneIndex, minute, zoneIndex, ...] lists: a person stays in a zone until
their next entry. The player rebuilds any minute from that, so scrubbing and rewinding are lookups, not
simulation. 'redact' removes the hidden causes and traits for a blind (operator-only) demo."""
import json
from pathlib import Path

import numpy as np

from .mood import CODE, DRIVERS

HIDDEN_PERSON = ("att", "disc", "acad")


def _dump(path, obj):
    Path(path).write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


class Packer:
    def __init__(self, engine, out_dir, redact=False):
        self.e, self.dir, self.redact = engine, Path(out_dir), redact
        (self.dir / "days").mkdir(parents=True, exist_ok=True)
        self.hist_mood, self.hist_att = {}, {}
        self.n_days = max(engine.ov.get("end_day", 150) + 1, len(engine.story.days))
        self.zi = engine.world.index
        if engine.ov.get("start_day", 0) >= 151:
            base_hist_path = self.dir.parent / "story_baseline" / "history.json"
            if base_hist_path.exists():
                try:
                    b_hist = json.loads(base_hist_path.read_text(encoding="utf-8"))
                    self.hist_mood = {int(k): list(v) for k, v in b_hist.get("mood", {}).items()}
                    self.hist_att = {int(k): list(v) for k, v in b_hist.get("att", {}).items()}
                except Exception:
                    pass

    def _hist(self, res, ids_in_roll):
        m = res["_micro"]["mood_end"]
        e = self.e
        i = res["i"]
        req_len = max(self.n_days, i + 1)
        for aid, mood in m.items():
            row = self.hist_mood.setdefault(aid, [-1] * req_len)
            if len(row) <= i:
                row.extend([-1] * (i + 1 - len(row)))
            row[i] = int(round(mood))
        for a in e.students:
            row = self.hist_att.setdefault(a.id, ["-"] * req_len)
            if len(row) <= i:
                row.extend(["-"] * (i + 1 - len(row)))
            if a.id in ids_in_roll and res["open"]:
                row[i] = "L" if (a.id in res.get("_late", ())) else "P" if a.present_today else "A"

    def on_day(self, i, res):
        e, m = self.e, res["_micro"]
        late = {a.id for a in e.students if a.present_today and a.late_today}
        res["_late"] = late
        roll = {a.id for a in e.students if e.story.on_roll(e.srec[a.sid], res["date"])}
        self._hist(res, roll)
        if not m["paths"] and not res["open"]:
            return
        drv = {}
        for aid, d in m["drv"].items():
            top = sorted(d.items(), key=lambda kv: -abs(kv[1]))[:3]
            top = [[CODE[k], round(v * 10)] for k, v in top if abs(v) >= 0.3]
            if top:
                drv[str(aid)] = top
        D = e.D
        day = {"i": i, "date": res["date"],
               "paths": {str(a): v for a, v in m["paths"].items() if v},
               "mood": {"t": [t for t, _ in m["snaps"]], "v": [row.tolist() for _, row in m["snaps"]]},
               "drv": drv,
               "cam": {str(self.zi[z]): v for z, v in m["cam"].items()}}
        _dump(self.dir / "days" / f"d{i:04d}.json", day)

    def finalize(self, evaluation=None):
        e = self.e
        zones = [{"id": z.id, "floor": z.floor, "type": z.type, "rect": [z.x, z.y, z.w, z.h], "cap": z.capacity,
                  "cam": z.camera_id, "measure": z.measure, "blind": z.blind_spot, "label": z.label,
                  "grade": z.grade, "section": z.section} for z in e.world.zones.values()]
        people = []
        for a in e.agents:
            p = {"id": a.id, "role": a.role, "sid": a.sid, "name": a.name, "sub": a.subrole, "grade": a.grade, "section": a.section,
                 "home": a.home_zone, "route": a.route, "grades": ([e.srec[a.sid]["grade"], e.srec[a.sid]["grade_on_2026_04_01"]] if a.role == "student" else None), "temperament": a.temperament, "traits": a.traits, "strengths": a.strengths,
                 "frictions": a.frictions, "friends": a.friends, "arc": a.arc, "char": a.character, "enroll": a.enroll, "withdraw": a.withdraw, "exit": a.exit_date}
            if not self.redact:
                p.update({"att": a.att_prop, "disc": a.disc_risk, "acad": a.acad})
            people.append(p)
        tracked = [a.id for a in e.agents if a.role != "visitor"]
        flags = [f for f in e.flags if not (self.redact and f["vis"] == "author")]
        if self.redact:
            for f in flags:
                f.pop("source", None)
        days = []
        for d in e.days:
            d = dict(d)
            d.pop("_late", None)
            if self.redact:
                d["events"] = []
            days.append(d)
        meta = {
            "run": {"id": e.ov["name"], "mode": e.ov["mode"], "seed": e.ov["seed"], "school": e.story.name, "redacted": self.redact,
                    "start_day": e.ov["start_day"], "end_day": e.ov["end_day"], "overview": e.ov},
            "clock": {"start": e.D["start"], "end": e.D["end"], "step": e.D["count_every"], "blocks": e.D["blocks"]},
            "floors": {str(k): v["name"] for k, v in e.world.floors.items()},
            "zones": zones, "people": people, "tracked": tracked, "drivers": DRIVERS,
            "mood": {"low": e.bh["mood"]["low"], "good": e.bh["mood"]["good"]},
            "days": days, "flags": flags,
            "alerts": e.alerts, "decisions": e.decisions,
            "cameras": [{"id": z.camera_id, "zone": z.id, "measure": z.measure, "label": z.label} for z in e.world.camera_zones()],
            "causal_audit": e.audit.to_summary() if hasattr(e, "audit") else {},
            "academic_summary": e.learning.get_summary() if hasattr(e, "learning") else {},
            "financial_summary": e.ledger.verify_reconciliation() if hasattr(e, "ledger") else {},
            "transport_summary": e.transport.get_transport_metrics() if hasattr(e, "transport") else {},
            "cognitive_summary": {
                "total_agents_tracked": len(e.cognitive.states) if hasattr(e, "cognitive") else 0,
                "active_goals_count": len([g for g in e.cognitive.goals.values() if g.status.value == "active"]) if hasattr(e, "cognitive") else 0,
                "agent_decisions_count": len(getattr(e, "agent_decisions", [])),
                "llm_calls_total": e.ollama.total_calls if hasattr(e, "ollama") else 0,
                "llm_fallback_calls": e.ollama.fallback_calls if hasattr(e, "ollama") else 0,
                "llm_replayed_calls": e.ollama.replayed_calls if hasattr(e, "ollama") else 0,
                "model_configured": e.ollama.model if hasattr(e, "ollama") else "none",
            },
            "agent_decisions": [d.to_dict() if hasattr(d, "to_dict") else d for d in getattr(e, "agent_decisions", [])],
        }
        if evaluation and not self.redact:
            meta["evaluation"] = evaluation

        # Generate spatial incidents (WP2)
        try:
            from .spatial_incidents import generate_spatial_incidents, write_incidents_json
            branch_info = e.ov.get("branch", {}) if isinstance(e.ov.get("branch"), dict) else {}
            ctrl_id = branch_info.get("control_run_id")
            ctrl_dir = (self.dir.parent / ctrl_id) if ctrl_id else None
            inc_records = generate_spatial_incidents(e, self.dir, ctrl_dir)
            write_incidents_json(self.dir, inc_records)
            meta["incidents"] = inc_records
        except Exception:
            pass

        _dump(self.dir / "meta.json", meta)
        hist_data = {
            "mood": {str(k): v for k, v in self.hist_mood.items()},
            "att": {str(k): "".join(v) for k, v in self.hist_att.items()},
        }
        if hasattr(e, "cognitive"):
            hist_data["cognitive"] = {str(aid): e.cognitive.get_agent_summary(aid) for aid in list(e.cognitive.states.keys())[:150]}
        _dump(self.dir / "history.json", hist_data)
        idx_path = self.dir.parent / "index.json"
        idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {"runs": []}
        idx["runs"] = [r for r in idx["runs"] if r["id"] != self.dir.name]
        idx["runs"].append({"id": self.dir.name, "name": e.ov["name"], "mode": e.ov["mode"], "days": len(e.days),
                            "school": e.story.name, "redacted": self.redact})
        _dump(idx_path, idx)
        return self.dir
