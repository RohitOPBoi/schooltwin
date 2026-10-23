"""The engine. One calendar day at a time: plan the day, play it out minute by minute, then close it.

PLAN   who is in, who is late, which teachers are out, what the events do        (macro: the day's numbers)
PLAY   minute-by-minute movement across the 2D campus, counters, behaviour       (micro: where everyone is)
CLOSE  mood, feedback, signals, detector, AI principal, finance                  (what the operator sees)

Anchor mode takes the day's numbers from the story; generate mode produces them from each student's hidden
traits, the weather, the events and the randomness you set. The PLAY step is identical in both.
Every day has its own random stream, so a change of settings on day D alters only days from D onwards.
"""
import bisect
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from . import overview as ovmod
from . import schedule
from .schedule import weekly_timetable as schedule_weekly
from .agents import Agent, create_population
from .cameras import observe
from .config import ROOT
from .decide import Principal
from .detect import Detector
from .events import SEVERITY, effects_for, make_event, random_events, signature_library, story_events
from .finance import Finance
from .mood import CODE, Mood, clamp
from .story import Story, room_id
from .world import World
from .causal import CausalAuditTrail, EventRecord, EffectRecord, CausalChainNode, InvestigationRecord, InvestigationStatus, RULESET_VERSION
from .ledger import FinancialLedger
from .learning import LearningModel
from .transport_maintenance import TransportMaintenanceManager
from .causal_handlers import CausalHandlerRegistry
from .cognitive import AgentDecision, AgentGoal, AgentMemory, ApprovalTier, CognitiveState, EpistemicStatus, GoalStatus
from .cognitive_manager import CognitivePopulationManager
from .extension_calendar import ExtensionCalendar
from .ollama_reasoner import OllamaReasoner

OUTSIDE = "outside"
ROLE_IDX = {"student": 0, "teacher": 1, "principal": 2, "staff": 3, "visitor": 4}
CLOSED_STAFF = {   # who is on campus when students are not
    "weekly_closure": {"security": 2}, "winter_break": {"security": 2, "maintenance_gardener": 1, "admin_accounts": 1},
    "planned_closure": {"security": 2}, "summer_break_staff_only": {"security": 3, "maintenance_gardener": 3, "admin_accounts": 3,
                                                                    "housekeeping": 4, "IT": 1, "librarian": 1, "teacher": 12},
}
THEMES = ["canteen queues", "assessment clarity", "teacher availability", "library time", "room comfort", "homework load",
          "bus reliability", "playground time", "sports period", "lab access"]
LAB_ZONES = ["lab_sci_1", "lab_sci_2", "comp_lab_1", "comp_lab_2"]


def read_yaml(name):
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8"))


class Engine:
    def __init__(self, overview=None, story=None):
        self.ov = ovmod.load(overview)
        self.story = story or Story()
        self.bh, self.sch, self.map = read_yaml("behavior"), read_yaml("school"), read_yaml("map")
        self.D = self.sch["day"]
        self.world = World(self.map, self.story.rooms())
        self.rng0 = np.random.default_rng(self.ov["seed"])
        self.agents = create_population(self.story, self.world, self.bh, self.rng0)
        self.srec = {s["student_id"]: s for s in self.story.students}
        self.students = [a for a in self.agents if a.role == "student"]
        self.visitors = [a for a in self.agents if a.role == "visitor"]
        self.tracked = [a.id for a in self.agents if a.role != "visitor"]       # who gets a mood timeline
        self.mood = Mood(self.bh)
        for a in self.agents:
            a.shift = float(self.rng0.normal(0, self.bh["mood"]["shift_sd"] * 2.3)) if a.role == "student" else 0.0
            a.mood = clamp((self.mood.student_base(a) + a.shift) if a.role == "student" else self.mood.staff_base(a))
        self.fin = Finance(self.story, self.ov)
        self.det = Detector()
        self.principal = Principal(self.story, self.ov["levers"]["autonomy_level"])
        self.sig_lib = signature_library(self.story)
        self.blind_ids = self.world.blind_spot_ids()
        self.class_ids = self.world.ids_of("classroom")
        self.knowers = {a.id for a in self.agents if a.knows_spots}
        self.patrollers = [a.id for a in self.agents if a.patrol_prob > 0]
        self._patrol_weights()
        self.zi = self.world.index
        self.events = self._build_events()
        self.cctv_plan = self.story.cctv_samples()
        self.cam_hist = defaultdict(list)             # camera -> past observed counts, for the 'expected' reference
        self.effects_active = []                      # approved decisions that change the simulation
        self.extra_teachers = 0
        self.days = []                                # one summary per day
        self.alerts, self.decisions, self.flags = [], [], []
        self.canteen_service = self.bh["canteen_service_per_minute"]
        self.members = defaultdict(set)
        self.counts = defaultdict(lambda: [0, 0, 0, 0, 0])

        # Phase 3: Causal Simulation, Ledger, Learning & Fleet subsystems
        self.audit = CausalAuditTrail(run_id=self.ov.get("name", "run"), seed=self.ov["seed"])
        self.ledger = FinancialLedger(
            opening_cash_inr=float(self.story.ledger["opening_cash_balance_inr"]),
            opening_ar_inr=float(self.story.ledger["opening_accounts_receivable_inr"])
        )
        self.learning = LearningModel(seed=self.ov["seed"])
        self.transport = TransportMaintenanceManager(num_routes=12)
        self.causal_registry = CausalHandlerRegistry(self.audit, self.ledger, self.learning, self.transport)
        for a in self.students:
            self.learning.initialize_student(a.sid, a.grade, a.section, a.id)
            if a.route:
                digits = "".join(c for c in str(a.route) if c.isdigit())
                r_num = int(digits) if digits else 1
                self.transport.register_student_route(a.sid, r_num)

        # Phase 4: Cognitive State, Sparse Relationships, and Optional Ollama Reasoning
        self.cognitive = CognitivePopulationManager(seed=self.ov["seed"])
        self.cognitive.initialize_population(self.agents, self.story)
        self.ollama = OllamaReasoner(
            model=self.ov.get("ollama_model", "qwen3.5:4b"),
            enabled=bool(self.ov.get("ollama_enabled", False)),
        )
        if "decision_trace" in self.ov and self.ov["decision_trace"]:
            self.ollama.load_trace(self.ov["decision_trace"])
        self.principal = Principal(
            self.story,
            self.ov["levers"]["autonomy_level"],
            ollama_reasoner=self.ollama,
        )
        self.agent_decisions = []

        # Extension Calendar & Snapshot Resume Support (WP1)
        branch_cfg = self.ov.get("branch", {}) if isinstance(self.ov.get("branch"), dict) else {}
        reopen_dt = self.ov.get("reopening_date") or branch_cfg.get("reopening_date", "2026-07-01")
        self.calendar = ExtensionCalendar(self.story, reopening_date=reopen_dt)

        snapshot_path = self.ov.get("snapshot_path")
        ckpt_id = self.ov.get("checkpoint_id") or branch_cfg.get("checkpoint_id")
        if not snapshot_path and not ckpt_id and self.ov.get("start_day", 0) >= 151:
            ckpt_id = "CKPT-DAY-150-TERM-CLOSE"
        if not snapshot_path and ckpt_id:
            from .snapshots import SNAPSHOTS_DIR
            cand = SNAPSHOTS_DIR / f"{ckpt_id}.json.gz"
            if cand.exists():
                snapshot_path = str(cand)

        if snapshot_path and Path(snapshot_path).exists():
            from .snapshots import load_snapshot_file, restore_snapshot
            snap = load_snapshot_file(Path(snapshot_path))
            restore_snapshot(self, snap)
            self._snapshot_resumed = True
        else:
            self._snapshot_resumed = False

    def capture_snapshot(self, day_idx: int):
        from .snapshots import capture_snapshot
        return capture_snapshot(self, day_idx)

    # ------------------------------------------------------------------ setup
    def _build_events(self):
        e, evs = self.ov["events"], []
        if e["use_story_events"]:
            evs += story_events(self.story, e["disable"])
        for x in e["add"]:
            p = dict(x.get("params") or {})
            for k, v in x.items():
                if k not in ("type", "date", "severity", "day", "id", "params"):
                    p.setdefault(k, v)
            evs.append(make_event(x["date"], x["type"], x.get("severity", "medium"), p, "user"))
        r = e["random"]
        if r["per_month"] > 0:
            open_dates = [
                self.calendar.info(d)["date"]
                for d in range(self.ov["start_day"], self.ov["end_day"] + 1)
                if self.calendar.info(d)["open"]
            ]
            evs += random_events(self.story, np.random.default_rng([self.ov["seed"], 7]), r["per_month"] * self.ov["randomness"]["intensity"],
                                 r["types"], open_dates, {x["date"] for x in evs})
        return evs

    def _patrol_weights(self):
        w = self.bh["patrol"]["weights"]
        self.p_dest, self.p_w = [], []
        for z in self.world.zones.values():
            key = "blind_spot" if z.blind_spot else z.type
            if key in w:
                self.p_dest.append(z.id)
                self.p_w.append(w[key])

    def lever(self, i, name):
        return ovmod.lever(self.ov, i, name)

    def day_rng(self, i):
        return np.random.default_rng([self.ov["seed"], 1000 + i])

    def _events_on(self, iso, i):
        out = []
        for ev in self.events:
            days = ev["params"].get("days", 1)
            if days <= 1:
                hit = ev["date"] == iso
            else:                                      # multi-day events run over the next open days
                open_dates = [
                    self.calendar.info(d)["date"]
                    for d in range(i, min(i + 30, self.ov["end_day"] + 1))
                    if self.calendar.info(d)["open"]
                ][:days]
                hit = iso in open_dates
            if hit:
                out.append(ev)
        return out

    # ------------------------------------------------------------------- PLAN
    def _assess_grades(self, iso):
        out = set()
        for w in self.story.assessments:
            if w["start"] <= iso <= w["end"]:
                out |= set(w["grades"])
        return out

    def _plan(self, i, rng):
        st, bh = self.story, self.bh
        info = self.calendar.info(i)
        iso = info["date"]
        row = self.calendar.by_date(iso)
        sig = row["operational_signals"]["signals"]
        K = self.ov["randomness"]["intensity"]
        day = dict(i=i, iso=iso, type=info["type"], open=info["open"], weather=sig["weather_disruption_index"],
                   heat=sig["heat_pressure_index"], assess_grades=self._assess_grades(iso), signals={}, sig_minute={},
                   incidents=[], parent_queries=0, topics=[], finance_items=[], timed=[], mood_events=[], notices=[],
                   absence_mult=1.0, grade_mult={}, late_riders=[], teacher_names=[], teacher_count=0, events=[], rider_delay=(8, 24),
                   friends={}, weekday=self.calendar.weekday(i))
        anchor = ovmod.mode_at(self.ov, i) == "anchor"
        day["anchor"] = anchor
        for a in self.students:                                   # who is in which class today
            rec = self.srec[a.sid]
            a.grade, a.section = st.grade_on(rec, iso), rec["section"]
            a.home_zone = room_id(a.grade, a.section)
        roll = {a.id for a in self.students if st.on_roll(self.srec[a.sid], iso)}
        day["roll"] = roll
        # Phase 3: Evaluate any effective-dated teacher resignations reaching departure today
        for tname in list(self.causal_registry.active_resignations.keys()):
            self.causal_registry.evaluate_resignation_departure(tname, iso, [a for a in self.agents if a.role == "teacher"])

        # ---- events -> effects
        for ev in self._events_on(iso, i):
            day["events"].append(ev)
            # Register versioned event in causal audit trail
            ev_rec = EventRecord(
                event_id=ev["id"],
                event_type=ev["type"],
                effective_date=iso,
                target_entities=list(ev.get("params", {}).get("student_ids", [])),
                params=dict(ev.get("params", {})),
                source=ev.get("source", "scenario"),
                title=ev.get("title", ""),
            )
            self.audit.register_event(ev_rec)

            # Causal domain handlers
            etype = ev["type"]
            if etype == "serious_student_fight":
                self.causal_registry.handle_serious_student_fight(ev_rec, {a.sid for a in self.students}, iso)
            elif etype == "suspected_prohibited_business":
                self.causal_registry.handle_suspected_prohibited_business(ev_rec, iso)
            elif etype == "teacher_resignation_notice":
                self.causal_registry.handle_teacher_resignation(ev_rec, iso)
                eff_dt = ev.get("params", {}).get("effective_date", iso)
                if iso >= eff_dt:
                    resig_name = ev.get("params", {}).get("teacher_name") or ev.get("params", {}).get("name") or ev.get("teacher_name", "Ritu Kapoor")
                    self.causal_registry.evaluate_resignation_departure(resig_name, iso, [a for a in self.agents if a.role == "teacher"])
            elif etype in ("transport_lateness_spike", "bus_breakdown"):
                bkp = min(int(self.lever(i, "bus_backup_capacity") or 0), 4)
                self.causal_registry.handle_bus_breakdown(ev_rec, iso, backup_capacity=bkp)
            elif etype == "school_fee_increase":
                ok = self.lever(i, "fee_change_approved")
                self.causal_registry.handle_fee_increase(ev_rec, iso, is_approved=bool(ok))
            elif etype == "additional_teacher_hired":
                self.causal_registry.handle_additional_teacher_hired(ev_rec, iso)
                tname = ev.get("params", {}).get("teacher_name") or ev.get("params", {}).get("name") or ev.get("teacher_name") or f"Additional teacher {self.extra_teachers + 1}"
                self.extra_teachers += 1
                self.agents.append(Agent(id=len(self.agents), role="teacher", sid=f"STF-X{self.extra_teachers:02d}", subrole="teacher",
                                         name=tname, home_zone="staffroom", mood=68.0))
                self.tracked.append(len(self.agents) - 1)
            elif etype == "water_cooler_breakdown":
                self.causal_registry.handle_water_cooler_breakdown(ev_rec, iso)
            elif etype == "collective_strike":
                self.causal_registry.handle_collective_strike(ev_rec, iso)

            # Phase 4: Propagate event perception to cognitive population
            target_sids = list(ev.get("params", {}).get("student_ids") or ev.get("student_ids") or [])
            target_aids = [self.cognitive.agent_sid_to_id[s] for s in target_sids if s in self.cognitive.agent_sid_to_id]
            if etype in ("transport_lateness_spike", "bus_breakdown"):
                raw_r = ev.get("params", {}).get("route_number") or ev.get("params", {}).get("route") or ev.get("route_number", 3)
                digits = "".join(c for c in str(raw_r) if c.isdigit())
                r_num = int(digits) if digits else 3
                r_code = f"BUS-R{r_num:02d}"
                target_aids = self.cognitive.route_students.get(r_code, []) or self.cognitive.route_students.get(r_num, [])

            if target_aids or etype in (
                "serious_student_fight", "bus_breakdown", "transport_lateness_spike", "teacher_resignation_notice",
                "suspected_prohibited_business", "water_cooler_breakdown", "collective_strike",
                "campus_power_outage", "water_service_disruption", "student_group_complaint",
                "urgent_cover_requirement", "maintenance_team_overload"
            ):
                self.cognitive.propagate_event_perception(
                    event_id=ev["id"],
                    event_type=etype,
                    date_str=iso,
                    primary_agent_ids=target_aids,
                    location=ev.get("params", {}).get("location", "campus"),
                    details=ev.get("title", ""),
                )
                # Level 3 Selective Deeper Reasoning for primary affected agents
                for aid in target_aids[:3]:
                    cs = self.cognitive.states.get(aid)
                    if cs:
                        dec = self.ollama.reason_agent_decision(
                            agent_id=aid,
                            role=cs.role,
                            state=cs,
                            active_goal=self.cognitive.get_active_goal(aid),
                            recent_memories=self.cognitive.retrieve_memories(aid, limit=3),
                            date_str=iso,
                            trigger_context=f"Responding to event {etype}",
                        )
                        self.agent_decisions.append(dec)

            for fx in effects_for(ev, self.sig_lib, rng):
                self._apply_effect(day, ev, fx, anchor, i)
        # ---- decisions from earlier days that are still active
        self.effects_active = [e for e in self.effects_active if e["until"] >= i]
        for e in self.effects_active:
            if e["name"] == "notify_families":
                day["absence_mult"] *= 0.97
        # ---- extra teachers lever
        want = int(self.lever(i, "additional_teachers") or 0)
        while self.extra_teachers < want:
            self.extra_teachers += 1
            self.agents.append(Agent(id=len(self.agents), role="teacher", sid=f"STF-X{self.extra_teachers:02d}", subrole="teacher",
                                     name=f"Additional teacher {self.extra_teachers}", home_zone="staffroom", mood=66.0))
            self.tracked.append(len(self.agents) - 1)
        if not day["open"]:
            self._plan_closed(day, rng)
            return day
        # ---- students present / late
        present, late = self._plan_students(day, row, roll, rng, anchor, K)
        day["present_students"], day["late_ids"] = present, late
        self._arrivals(day, rng, K)
        # ---- teachers & staff
        self._plan_staff(day, row, rng, anchor)
        for a in self.students:
            day["friends"][a.id] = sum(1 for f in a.friends if f in present) if a.id in present else 0
        return day

    def _plan_students(self, day, row, roll, rng, anchor, K):
        g, st = self.bh["generate"], self.story
        riders = [a for a in self.students if a.id in roll and a.route]
        if anchor and isinstance(row.get("student_enrollment"), dict) and "present_student_ids" in row["student_enrollment"]:
            ids = set(row["student_enrollment"]["present_student_ids"])
            present = {a.id for a in self.students if a.sid in ids}
            n_late = row["student_enrollment"].get("late_arrivals", 0)
        else:
            fee = (self.lever(day["i"], "tuition_fee_delta_pct") or 0) / 100.0 if self.lever(day["i"], "fee_change_approved") else 0.0
            support = (self.lever(day["i"], "attendance_support_budget_inr_per_month") or 0) / 300000.0
            mult = day["absence_mult"] * (1 + g["fee_stress_absence"] * max(fee, 0)) * (1 - 0.06 * support ** 0.7)
            noise = rng.normal(0, g["absence_noise_sd"] * K)
            env = 1 - g["weather_absence"] * day["weather"] - g["heat_absence"] * max(0.0, day["heat"] - 1.0)
            present = set()
            for a in self.students:
                if a.id not in roll:
                    continue
                p_abs = (1 - min(0.995, a.att_prop + g["attendance_offset"]))
                p_abs = p_abs * mult
                gm = day["grade_mult"].get(a.grade, 1.0)
                p_pres = (1 - min(0.97, p_abs * gm)) * env + noise
                if rng.random() < p_pres:
                    present.add(a.id)
            n_late = None
        # who arrives after assembly begins
        pres = [a for a in self.students if a.id in present]
        late = set()
        if anchor:
            late = self._pick_late(day, pres, n_late, rng)
        else:
            for a in pres:
                if rng.random() < g["late_base"] * K * (1 + g["late_low_propensity_boost"] * (1 - a.att_prop)):
                    late.add(a.id)
        return present, late

    def _pick_late(self, day, pres, n, rng):
        late = set()
        riders = {}
        for ev_n, routes in day["late_riders"]:
            pool = [a for a in pres if a.route in routes]
            rng.shuffle(pool)
            if len(pool) < min(ev_n, n):                             # a merged-route morning spills onto other buses
                spill = [a for a in pres if a.route and a.route not in routes]
                rng.shuffle(spill)
                pool += spill[:min(ev_n, n) - len(pool)]
            for a in pool[:min(ev_n, n)]:
                late.add(a.id)
        rest = [a for a in pres if a.id not in late]
        w = np.array([(1 - a.att_prop) + 0.05 for a in rest])
        if len(rest) and n > len(late):
            pick = rng.choice(len(rest), size=min(n - len(late), len(rest)), replace=False, p=w / w.sum())
            late |= {rest[j].id for j in pick}
        return late

    def _arrivals(self, day, rng, K):
        A, ar = self.D["assembly_start"], self.bh["arrival"]
        shape, scale = ar["arrive_gamma"]
        lo, hi = ar["late_window"]
        riders_hit = {}
        for n, routes in day["late_riders"]:
            for rid in routes:
                riders_hit[rid] = n
        for a in self.students:
            if a.id not in day["present_students"]:
                a.present_today = False
                continue
            a.present_today = True
            a.late_today = a.id in day["late_ids"]
            if a.late_today:
                t = A + int(rng.integers(lo, hi + 1))
            elif a.route:
                t = int(np.clip(rng.normal(480, 12), 445, A - 3))
            else:
                t = int(max(self.D["gate_open"] + 3, A - rng.gamma(shape, scale)))
            if a.route in riders_hit and not a.late_today and not day["anchor"]:   # late-bus morning: held up too
                t = min(A + 24, t + int(rng.integers(*day["rider_delay"])))
                a.late_today = t >= A
            a.arrive = t
            a.arrival_pref = "classroom" if rng.random() < ar["early_classroom_fraction"] else "north_ground"
            a.dodge = rng.random() < self.bh["assembly"]["dodge_probability"]
            dj = self.bh["departure"]
            a.leave = self.D["blocks"][-1]["start"] + int(rng.integers(*dj["dismissal_jitter"]))
            if rng.random() < dj["early_leave_probability"]:
                a.leave = int(rng.integers(self.D["blocks"][4]["start"], self.D["blocks"][-1]["start"]))
            a.shifts = [(a.arrive, a.leave)]
        # break and lunch choices are split in fixed proportions each day (a steady canteen line, not coin flips)
        order = [a for a in self.students if a.present_today]
        for field, key in (("break_pref", "short_break"), ("lunch_pref", "lunch")):
            perm = rng.permutation(len(order))
            m = self.bh["breaks"][key]
            tot, edges, acc = sum(m.values()), [], 0.0
            for k, v in m.items():
                acc += v / tot * len(order)
                edges.append((acc, k))
            for rank, idx in enumerate(perm):
                setattr(order[idx], field, next(k for e, k in edges if rank < e + 1e-9))

    @staticmethod
    def _pick(m, rng):
        r, acc, tot = rng.random() * sum(m.values()), 0.0, 0.0
        for k, v in m.items():
            acc += v
            if r <= acc:
                return k
        return k

    def _plan_staff(self, day, row, rng, anchor):
        g = self.bh["generate"]
        teachers = [a for a in self.agents if a.role == "teacher" and not (a.exit_date and day["iso"] >= a.exit_date)]
        out = set()
        for nm in day["teacher_names"]:
            for a in teachers:
                if a.name == nm:
                    out.add(a.id)
        k = row["staffing"]["teachers_absent"] if anchor else int(rng.binomial(len(teachers), min(g["teacher_absence_base"] + (0.0), 0.5)))
        pool = [a.id for a in teachers if a.id not in out and a.subrole == "teacher" and not a.sid.startswith("STF-X")]
        rng.shuffle(pool)
        while len(out) < max(k, len(out)) and pool:
            out.add(pool.pop())
            if len(out) >= k:
                break
        day["teachers_absent"] = out
        A = self.D["assembly_start"]
        for a in self.agents:
            if a.role == "visitor" or a.role == "student":
                continue
            a.present_today = (a.id not in out) and not (a.exit_date and day["iso"] >= a.exit_date)
            if a.role == "staff" and a.subrole != "canteen_staff" and rng.random() < 0.02:
                a.present_today = False
            a.late_today = False
            a.break_pref = self._pick(self.bh["breaks"]["teacher"], rng)
            a.lunch_pref = a.break_pref
            if a.subrole in ("driver", "bus_attendant", "transport_supervisor"):
                a.shifts = [(int(rng.integers(438, 462)), 512), (int(rng.integers(832, 842)), int(rng.integers(880, 895)))]
            elif a.role == "teacher":
                a.shifts = [(A - int(rng.integers(20, 50)), 880 + int(rng.integers(0, 40)))]
            elif a.subrole == "security":
                a.shifts = [(430, 900)]
            else:
                a.shifts = [(int(rng.integers(430, 470)), 880 + int(rng.integers(0, 40)))]
            a.arrive, a.leave = a.shifts[0][0], a.shifts[-1][1]
        # each absent teacher's periods need cover: the first few are covered, the rest become 'uncovered'
        day["cover_periods"] = len(out) * 4

    def _plan_closed(self, day, rng):
        want = dict(CLOSED_STAFF.get(day["type"], {"security": 2}))
        for a in self.students:
            a.present_today = False
        day["present_students"], day["late_ids"], day["teachers_absent"] = set(), set(), set()
        for a in self.agents:
            if a.role in ("student", "visitor"):
                continue
            key = "teacher" if a.role == "teacher" else a.subrole
            a.present_today = False
            if want.get(key, 0) > 0 and not (a.exit_date and day["iso"] >= a.exit_date):
                want[key] -= 1
                a.present_today = True
                a.shifts = [(int(rng.integers(500, 560)), int(rng.integers(780, 900))) if key != "security" else (430, 900)]
                a.arrive, a.leave = a.shifts[0]
                a.break_pref = "staffroom"
        day["cover_periods"] = 0

    # ---------------------------------------------------------------- effects
    def _apply_effect(self, day, ev, fx, anchor, i):
        v, a = fx.verb, fx.args
        if v == "absence":
            if not anchor:
                if a.get("grades"):
                    for g in a["grades"]:
                        day["grade_mult"][g] = day["grade_mult"].get(g, 1.0) * a["mult"]
                else:
                    day["absence_mult"] *= a["mult"]
        elif v == "late_riders":
            backup = min(int(self.lever(i, "bus_backup_capacity") or 0), 4)
            n = int(a["n"] * (1 - 0.2 * backup))
            routes = sorted({s["transport_route"] for s in self.story.students if s["transport_route"]})
            k = a["routes"] if isinstance(a["routes"], int) else len(a["routes"])
            pick = np.random.default_rng([self.ov["seed"], 11, i]).choice(len(routes), size=min(k, len(routes)), replace=False)
            day["late_riders"].append((n, {routes[j] for j in pick}))
            day["rider_delay"] = tuple(a["delay"])
        elif v == "teacher_absent":
            day["teacher_names"] += list(a.get("names", []))
        elif v == "mood":
            day["mood_events"].append(a)
        elif v in ("queue_extra", "visitors", "close_zone", "relocate", "infirmary", "staff_visit"):
            day["timed"].append((v, a))
        elif v == "signal":
            day["signals"].update(a)
        elif v == "incident":
            sev = a["severity"]
            day["incidents"].append({"kind": a["kind"], "summary": (ev.get("impact") or a["summary"]), "zone": a["zone"],
                                     "minute": a["minute"], "severity": sev, "event_id": ev["id"], "title": ev["title"]})
            for k in day["signals"]:
                day["sig_minute"].setdefault(k, a["minute"])
        elif v == "parent_queries":
            day["parent_queries"] += a["n"]
            day["topics"] += a.get("topics", [])
        elif v == "finance":
            day["finance_items"].append((a["account"], a["amount"], a["desc"]))
        elif v == "staff_notice":
            day["notices"].append(a["name"])

    # ------------------------------------------------------------------- PLAY
    def _block_at(self, t):
        for b in self.D["blocks"]:
            if b["start"] <= t < b["end"]:
                return b
        return {"name": "post", "type": "dismissal", "start": self.D["blocks"][-1]["end"], "end": 10 ** 6}

    def _setup_timetable(self, day):
        sd = self.ov["seed"]
        teachers = [a.id for a in self.agents if a.role == "teacher" and a.subrole == "teacher" and not a.sid.startswith("STF-X")]
        rooms_all = sorted(self.class_ids)
        have = {a.home_zone for a in self.students if a.id in day.get("present_students", ())}
        self.teach_today, self.lab_plan, self.uncovered, self.cover_taken = {}, {}, set(), {}
        free_frac = self.bh["staffing"]["substitute_availability"]
        if any(e["name"] == "replan_cover" for e in self.effects_active):
            free_frac = min(1.0, free_frac + 0.25)
        for bi, b in enumerate(self.D["blocks"]):
            if b["type"] != "class":
                continue
            base = schedule_weekly(sd, day["weekday"], bi, teachers, rooms_all)
            tt = {tid: room for tid, room in base.items() if room in have and tid not in day["teachers_absent"]}
            missing = [room for tid, room in base.items() if room in have and tid in day["teachers_absent"]]
            free = [t for t in teachers if t not in tt and t not in day["teachers_absent"]]
            extras = [a.id for a in self.agents if a.sid.startswith("STF-X")]
            rng = np.random.default_rng([sd, 8, day["i"], bi])
            rng.shuffle(free)
            pool = extras + free[:int(len(free) * free_frac + 0.5)]
            for room in missing:
                if pool:
                    sub = pool.pop(0)
                    tt[sub] = room
                    self.cover_taken[sub] = self.cover_taken.get(sub, 0) + 1
                else:
                    self.uncovered.add((b["name"], room))
            self.teach_today[b["name"]] = tt
            rr = np.random.default_rng([sd, 6, day["weekday"], bi])
            senior = [r for r in rooms_all if r in have and not self.world.zones[r].camera_id and self.world.zones[r].grade not in ("Nursery", "KG", "Class 1", "Class 2", "Class 3", "Class 4", "Class 5")]
            labs = list(rr.permutation(LAB_ZONES))
            picks = list(rr.permutation(senior))[:len(labs)] if senior else []
            self.lab_plan[b["name"]] = dict(zip(picks, labs))
        # a scheduled lab failure needs a class in that lab at that time
        for v, a in day["timed"]:
            if v == "close_zone":
                bname = self._block_at(a["from"] + 1)["name"]
                senior = [r for r in rooms_all if r in have and self.world.zones[r].grade in ("Class 9", "Class 10", "Class 11", "Class 12")]
                if senior and bname in self.lab_plan:
                    self.lab_plan[bname] = {r: z for r, z in self.lab_plan[bname].items() if z != a["zone"]}
                    self.lab_plan[bname][senior[0]] = a["zone"]

    def _target(self, a, block):
        z = schedule.target_zone(a, block, self.teach_today)
        if block["type"] == "class":
            z = self.zone_map.get(z, z)
        if z in self.closed:
            z = a.home_zone if a.role == "student" else "staffroom"
        return self._normalize_zone(z)

    def _normalize_zone(self, zid):
        if not zid or zid == OUTSIDE or zid in self.world.zones:
            return zid
        s = str(zid).lower().replace("-", "_").strip()
        if s.startswith("class_") or s.startswith("classroom_"):
            parts = s.split("_")
            cand = "C" + parts[-1].upper()
            if cand in self.world.zones:
                return cand
        cand = "C" + str(zid).upper()
        if cand in self.world.zones:
            return cand
        cand_upper = str(zid).upper()
        if cand_upper in self.world.zones:
            return cand_upper
        return "admin_lobby" if "admin_lobby" in self.world.zones else list(self.world.zones.keys())[0]

    def _log_move(self, a, zid, t):
        norm_z = self._normalize_zone(zid)
        zi_val = self.zi.get(norm_z, -1) if norm_z != OUTSIDE else -1
        self.paths[a.id].extend((t, zi_val))

    def _move(self, a, zid, t):
        zid = self._normalize_zone(zid)
        if a.zone == zid:
            return
        ri = ROLE_IDX[a.role]
        if a.zone != OUTSIDE and a.zone in self.members:
            self.members[a.zone].discard(a.id)
            self.counts[a.zone][ri] -= 1
        a.zone = zid
        self._log_move(a, zid, t)
        if zid == OUTSIDE:
            return
        z = self.world.zones.get(zid)
        if not z:
            return
        a.floor = z.floor
        a.x, a.y = z.sample_point(self.rng)
        if zid in self.members:
            self.members[zid].add(a.id)
            self.counts[zid][ri] += 1
        if z.measure.startswith("entries") and (a.role == "student" or zid not in ("main_gate", "bus_bay")):
            self.entries[zid].append(t)
        if zid == "canteen" and a.role == "student" and a.away_until < 0:
            self._canteen_join(a, t)

    def _adjust(self, a, delta, why):
        a.mood = clamp(a.mood + delta)
        self.drv[a.id][why] += delta

    def _canteen_join(self, a, t):
        rate = self.canteen_service * (1.3 if any(e["name"] == "stagger_canteen" for e in self.effects_active) else 1.0)
        if self.service_mod and self.service_mod[0] <= t <= self.service_mod[1]:
            rate *= self.service_mod[2]
        start = max(float(t), self.canteen_last)
        if start - t > self.bh["canteen_balk_minutes"]:             # the line is too long: give up and go outside
            self._adjust(a, -1.0, "canteen wait")
            self.queue[t + 1].append(("eat_done", a.id))
            return
        self.canteen_last = start + 1.0 / rate
        self.canteen_finish.append(self.canteen_last)
        wait = self.canteen_last - t
        a.queue_wait = wait
        c = self.bh["mood"]["canteen_wait"]
        if wait > c["free_minutes"]:
            self._adjust(a, max(c["cap"], c["per_extra_minute"] * (wait - c["free_minutes"])), "canteen wait")
        self.queue[int(self.canteen_last + self.rng.integers(5, 12))].append(("eat_done", a.id))

    def _queue_len(self, t):
        return len(self.canteen_finish) - bisect.bisect_right(self.canteen_finish, t)

    def _start_block(self, t, block, bi):
        lo, hi = self.D["transit_minutes"]
        stagger = self.D["stagger_minutes"]
        btype = block["type"]
        if btype == "class":
            self.zone_map = {}
            for room, lab in self.lab_plan.get(block["name"], {}).items():
                if lab not in self.closed:
                    self.zone_map[room] = lab
            for (bname, room) in self.uncovered:
                if bname == block["name"]:
                    for i in self.members.get(room, ()):
                        if self.agents[i].role == "student":
                            self._adjust(self.agents[i], self.bh["mood"]["uncovered_class"], "uncovered class")
        else:
            self.zone_map = {}
        for zid, z in self.world.zones.items():                           # shared discomfort of packed places
            if z.type not in ("classroom", "gate", "bus") and sum(self.counts[zid]) / z.capacity > 0.85:
                for i in self.members[zid]:
                    if self.agents[i].role == "student":
                        self._adjust(self.agents[i], self.bh["mood"]["crowded_zone"], "crowding")
        win = 10 if btype == "break" else 45
        bound = [a for a in self.agents if a.role == "student" and a.zone != OUTSIDE and btype in ("break", "lunch")
                 and (a.break_pref if btype == "break" else a.lunch_pref) == "canteen" and a.away_until <= t]
        slots = dict(zip((a.id for a in bound), self.rng.permutation(np.linspace(1, win, max(len(bound), 1)))))   # even spread: a steady line
        for a in self.agents:
            if a.zone == OUTSIDE or a.role == "visitor":
                continue
            a.target = self._target(a, block)
            if btype in ("break", "lunch") and a.role == "student" and a.target == "playground":
                self._adjust(a, self.bh["mood"]["playground_break"], "time outdoors")
            if a.away_until > t or a.target == a.zone:
                continue
            delay = int(slots[a.id] + self.rng.integers(0, 2)) if a.id in slots and a.target == "canteen" else int(self.rng.integers(0, stagger + 1))
            self.queue[t + delay].append(("depart", a.id))
        self._snap(t)

    def _snap(self, t):
        self.snaps.append((t, np.array([int(round(a.mood)) for a in self.agents if a.role != "visitor"], dtype=np.int16)))

    def _handle(self, t, item, block):
        kind = item[0]
        if kind == "timed":
            return self._timed(t, item[1], item[2])
        if kind == "mood_evt":
            return self._mood_event(t, item[1])
        a = self.agents[item[1]]
        lo, hi = self.D["transit_minutes"]
        if kind == "arrive_bus":
            self._move(a, "bus_bay", t)
        elif kind == "arrive":
            a.target = self._target(a, block)
            self._move(a, "main_gate", t)
            self.queue[t + int(self.rng.integers(1, 3))].append(("enter", a.id))
        elif kind == "enter":
            if a.zone != "main_gate":
                return
            a.target = self._target(a, block)
            if a.role == "student" and a.late_today and block["type"] != "assembly":
                self._adjust(a, self.bh["mood"]["late_arrival"], "arrived late")
            if a.target != "main_gate":
                self._move(a, a.target, t)
        elif kind == "depart":
            if a.zone == OUTSIDE or a.away_until > t or a.target == a.zone:
                return
            self._move(a, self.world.corridor_of(self.world.zones[a.target].floor).id, t)
            self.queue[t + int(self.rng.integers(lo, hi + 1))].append(("go", a.id))
        elif kind == "go":
            if a.zone != OUTSIDE and a.away_until <= t and a.zone != a.target:
                self._move(a, a.target or a.home_zone, t)
        elif kind == "eat_done":
            if a.zone == "canteen" and a.away_until <= t:
                self._move(a, "playground" if self.rng.random() < 0.6 else a.home_zone, t)
        elif kind == "errand_go":
            dest, dur = item[2], item[3]
            if a.zone != OUTSIDE and a.away_until > t:
                self._move(a, dest, t)
                a.away_until = t + dur
                a.away_zone = dest
                self.queue[t + dur].append(("return", a.id))
        elif kind == "return":
            if a.zone != OUTSIDE and a.away_until == t:
                a.away_until, a.away_zone = -1, ""
                if a.target and a.target != a.zone:
                    if self.world.zones[a.zone].type != "corridor":
                        self._move(a, self.world.corridor_of(a.floor).id, t)
                    self.queue[t + int(self.rng.integers(lo, hi + 1))].append(("go", a.id))
        elif kind == "vis_in":
            self._move(a, "main_gate", t)
            self.queue[t + 2].append(("go", a.id))
        elif kind == "exit":
            if a.zone != OUTSIDE and a.away_until <= t:
                self._move(a, "bus_bay" if a.route else "main_gate", t)
        elif kind == "leave":
            a.away_until = -1
            if a.zone != OUTSIDE:
                self._move(a, OUTSIDE, t)
        elif kind == "vis_out":
            if a.zone != OUTSIDE:
                self._move(a, "main_gate", t)
                self.queue[t + 2].append(("leave", a.id))

    def _away_via_corridor(self, a, dest, t, dur):
        """Leave where you are, pass through the corridor, spend `dur` minutes at dest, come back through the corridor."""
        trans = int(self.rng.integers(1, 3))
        self._move(a, self.world.corridor_of(a.floor).id, t)
        a.away_until = t + trans + dur
        self.queue[t + trans].append(("errand_go", a.id, dest, dur))
        a.away_zone = dest

    def _go_away(self, a, zid, t, dur):
        a.away_until, a.away_zone = t + dur, zid
        self._move(a, zid, t)
        self.queue[t + dur].append(("return", a.id))

    # --------------------------------------------------- the 'real school' layer
    def _behaviors(self, t, block):
        if block["type"] == "class":
            self._errands(t)
            if block["name"] in ("P3", "P4", "P5"):
                self._library(t)
        self._blind(t, block)
        self._spread(t)
        self._patrols(t)

    def _students_in_class(self):
        return sum(self.counts[z][0] for z in self.class_ids)

    def _pick_in_class(self, _=None):
        """A random present student who is currently sitting in their own classroom (rejection sampling: fast)."""
        pl = self.pres_list
        for _ in range(8):
            a = pl[int(self.rng.integers(len(pl)))]
            if a.zone == a.home_zone and a.away_until < 0:
                return a
        return None

    def _errands(self, t):
        e, K = self.bh["errands"], self.ov["randomness"]["intensity"]
        n = self._students_in_class()
        if n == 0:
            return
        for _ in range(int(self.rng.binomial(n, e["trip_prob_per_student_per_class_minute"] * K))):
            a = self._pick_in_class()
            if a and a.away_until <= t and a.zone == a.home_zone:
                dur = int(self.rng.integers(*e["duration"]))
                dest = f"wash_{a.floor}" if self.rng.random() < e["washroom_share"] else f"corridor_{a.floor}"
                self._away_via_corridor(a, dest, t, dur)

    def _library(self, t):
        lv = self.bh["library_visits"]
        if self._students_in_class() == 0:
            return
        for _ in range(int(self.rng.poisson(lv["per_class_minute"]))):
            a = self._pick_in_class()
            if a and a.away_until <= t and a.zone == a.home_zone and a.grade not in ("Nursery", "KG"):
                self._away_via_corridor(a, "library", t, int(self.rng.integers(*lv["stay"])))

    def _blind(self, t, block):
        c, K, btype = self.bh["blind_spots"], self.ov["randomness"]["intensity"], block["type"]
        self.stats["blind_minutes"] += sum(self.counts[s][0] for s in self.blind_ids)
        if btype not in ("class", "break", "lunch"):
            return
        for i in sorted(self.knowers):
            a = self.agents[i]
            if a.zone == OUTSIDE or a.away_until > t or not a.present_today or a.role != "student":
                continue
            scale = 0.3 + 4 * a.disc_risk
            if btype == "class":
                if a.zone != a.home_zone:
                    continue
                p = c["class_skip_prob_per_minute"] * scale * K
                if (block["name"], a.home_zone) in self.uncovered:
                    p *= c["uncovered_class_multiplier"]
            else:
                p = c["break_use_prob_per_minute"] * scale * K
            if self.rng.random() < p:
                spot = str(self.rng.choice(a.knows_spots))
                if self.counts[spot][0] < self.world.zones[spot].capacity:
                    self._go_away(a, spot, t, int(self.rng.integers(*c["duration"])))

    def _spread(self, t):
        lp = self.bh["blind_spots"]["learn_prob_per_minute"]
        for spot in self.blind_ids:
            kids = [i for i in self.members[spot] if self.agents[i].role == "student"]
            if len(kids) < 2:
                continue
            for i in kids:
                if self.rng.random() < lp * (1 - self.world.zones[spot].secrecy) and self.agents[i].friends:
                    f = self.agents[int(self.rng.choice(self.agents[i].friends))]
                    if spot not in f.knows_spots:
                        f.knows_spots.append(spot)
                        self.knowers.add(f.id)

    def _patrols(self, t):
        cfg = self.bh["patrol"]
        boost = 2.0 if any(e["name"] == "boost_patrol" for e in self.effects_active) else 1.0
        for i in self.patrollers:
            a = self.agents[i]
            if a.zone == OUTSIDE or a.away_until > t or not a.present_today:
                continue
            if self.rng.random() >= a.patrol_prob * boost:
                continue
            w = np.array(self.p_w, dtype=float)
            if a.role == "principal":
                for k, z in enumerate(self.p_dest):
                    if self.world.zones[z].blind_spot:
                        w[k] *= cfg["principal_blind_spot_factor"]
            dest = self.p_dest[int(self.rng.choice(len(w), p=w / w.sum()))]
            self._go_away(a, dest, t, int(self.rng.integers(*cfg["stay_minutes"])))
            if self.world.zones[dest].blind_spot:
                self._catch(t, dest)

    def _catch(self, t, spot):
        kids = [self.agents[i] for i in sorted(self.members[spot]) if self.agents[i].role == "student"]
        if not kids:
            return
        lo, hi = self.D["transit_minutes"]
        for k in kids:
            k.away_until, k.away_zone = -1, ""
            self._adjust(k, self.bh["mood"]["caught"], "caught in a hidden area")
            self._move(k, self.world.corridor_of(self.world.zones[spot].floor).id, t)
            self.queue[t + int(self.rng.integers(lo, hi + 1))].append(("go", k.id))
        self.stats["caught"] += len(kids)
        self.micro_events.append({"minute": t, "zone": spot, "kind": "blind_spot_caught", "sev": 1,
                                  "text": f"{len(kids)} student(s) found in an unwatched area and sent back to class."})

    # ------------------------------------------------------- timed (event) effects
    def _timed(self, t, verb, a):
        rng = self.rng
        pres = [x for x in self.students if x.present_today and x.zone != OUTSIDE and x.away_until <= t]
        if verb == "infirmary":
            pool = [x for x in pres if x.zone == x.home_zone]
            for x in (rng.choice(pool, size=min(a["n"], len(pool)), replace=False) if pool else []):
                self._away_via_corridor(x, "infirmary", t, a.get("stay", 30))
                self.infirm_visits += 1
        elif verb == "staff_visit":
            staff = [x for x in self.agents if x.role != "student" and x.role != "visitor" and x.subrole in a["roles"]
                     and x.present_today and x.zone != OUTSIDE and x.away_until <= t]
            for x in staff[:3]:
                self._go_away(x, a["zone"], t, max(5, a["to"] - t))
        elif verb == "queue_extra":
            pool = [x for x in pres if x.zone != "canteen"]
            for x in (rng.choice(pool, size=min(a["n"], len(pool)), replace=False) if pool else []):
                x.target = "canteen"
                self.queue[t + int(rng.integers(0, 10))].append(("go", x.id))
        elif verb == "visitors":
            free = [x for x in self.visitors if x.zone == OUTSIDE][:a["n"]]
            for x in free:
                x.target = a["zone"]
                x.present_today = True
                self.queue[t + int(rng.integers(0, 6))].append(("vis_in", x.id))
                self.queue[a["to"] + int(rng.integers(0, 6))].append(("vis_out", x.id))
        elif verb == "close_zone":
            z = a["zone"]
            self.closed.add(z)
            moved = 0
            for i in sorted(self.members[z]):
                x = self.agents[i]
                dest = x.home_zone if x.role == "student" else self._classroom_of_group(z, x)
                x.target = dest
                self._move(x, dest, t)
                moved += x.role == "student"
            zone = self.world.zones[z]
            if zone.camera_id:
                self.cctv.append(self._record(zone.camera_id, z, t, "room cleared after operational interruption", "occupancy", 0, 0))
        elif verb == "relocate":
            for i in sorted(self.members[a["room"]]):
                x = self.agents[i]
                x.target = a["to"]
                self._move(x, a["to"], t)
            self.zone_map[a["room"]] = a["to"]
        return None

    def _classroom_of_group(self, closed_zone, teacher):
        for room, lab in self.lab_plan.get(self._block_at(self.t_now)["name"], {}).items():
            if lab == closed_zone:
                return room
        return "staffroom"

    def _mood_event(self, t, k):
        e = self.day["mood_events"][k]
        if e.get("all") == "students":
            group = [x for x in self.students if x.present_today]
        elif e.get("all") == "teachers":
            group = [x for x in self.agents if x.role == "teacher" and x.present_today]
        elif e.get("ids"):
            target_ids = set(str(sid) for sid in e["ids"])
            group = [x for x in self.agents if x.present_today and (str(x.sid) in target_ids or str(x.id) in target_ids or str(x.name) in target_ids)]
        else:
            group = [x for x in self.students if x.present_today and x.home_zone == e.get("room", "")]
            if e.get("n"):
                group.sort(key=lambda x: (not x.character, x.id))
                group = group[:e["n"]]
        for x in group:
            self._adjust(x, e["delta"], "event")

    # --------------------------------------------------------------- counters
    CLOSED_LABELS = ("staff/approved visitor flow", "vehicle movement count", "restricted-room aggregate access", "perimeter exit count")

    def _reading(self, z, t):
        rng, m = self.rng, z.measure
        if m == "occupancy":
            n = sum(self.counts[z.id])
            return n, observe(z, n, rng)
        if m == "queue":
            n = self._queue_len(t)
            return n, int(rng.binomial(n, 0.95)) if n > 0 else 0
        e = self.entries[z.id]
        if m == "entries_window":
            n = bisect.bisect_right(e, t) - bisect.bisect_right(e, t - 15)
            return n, int(rng.binomial(n, 0.97)) if n > 0 else 0
        n = bisect.bisect_right(e, t)
        return n, int(rng.binomial(n, 0.985)) if n > 0 else 0

    def _record(self, camera, zone, t, label, measure, true, observed):
        hist = self.cam_hist[(camera, t)]
        exp = float(np.median(hist[-10:])) if len(hist) >= 3 else float(observed)
        hist.append(observed)
        dev = round(100.0 * (observed - exp) / exp, 1) if exp >= 8 else 0.0     # tiny baselines say nothing
        return {"camera_id": camera, "zone": zone, "minute": t, "label": label, "measure": measure,
                "observed_count": int(observed), "expected_count": round(exp, 1), "deviation_pct": dev, "true_count": int(true)}

    def _tally(self, t, block):
        thr = self.bh["crowding"]["threshold_ratio"]
        if t % self.D["count_every"] == 0:
            for zid, c in self.counts.items():
                tot = sum(c)
                if tot <= 0:
                    continue
                z = self.world.zones[zid]
                self.stats["peak"][zid] = max(self.stats["peak"].get(zid, 0.0), tot / z.capacity)
            for z in self.cam_zone.values():
                self.cam_series[z.id].append(self._reading(z, t)[1])
        for (m, cam, zlabel, label) in self.samples_today:
            if m == t:
                z = self.cam_zone[cam]
                true, obs = self._reading(z, t)
                self.cctv.append(self._record(cam, z.id, t, label, z.measure, true, obs))

    # ------------------------------------------------------------------- PLAY
    def _play(self, day, rng):
        D = self.D
        self.rng, self.day = rng, day
        self.queue = defaultdict(list)
        self.members.clear()
        self.counts.clear()
        self.paths, self.entries = defaultdict(list), defaultdict(list)
        self.canteen_finish, self.canteen_last, self.service_mod = [], 0.0, None
        self.closed, self.zone_map = set(), {}
        self.stats = {"blind_minutes": 0, "caught": 0, "peak": {}}
        self.cctv, self.snaps, self.micro_events, self.infirm_visits, self.t_now = [], [], [], 0, 0
        self.cam_series = defaultdict(list)
        self.drv = defaultdict(lambda: defaultdict(float))
        self.pres_list = [a for a in self.students if a.id in day.get("present_students", ())]
        self.cam_zone = {z.camera_id: z for z in self.world.camera_zones()}
        self.samples_today = [s for s in self.cctv_plan if s[3] not in self.CLOSED_LABELS] if day["open"] else []
        for a in self.agents:
            a.zone, a.away_until, a.away_zone = OUTSIDE, -1, ""
        self._setup_timetable(day)
        self._pre_mood(day)
        anyone = any(a.present_today for a in self.agents if a.role != "visitor")
        K = self.ov["randomness"]["intensity"]
        if anyone:
            for a in self.agents:
                if a.role == "visitor" or not a.present_today:
                    continue
                for (s, e) in a.shifts:
                    if a.role == "student" and a.route:
                        self.queue[max(s - int(rng.integers(*self.bh["arrival"]["rider_bus_lead"])), D["start"])].append(("arrive_bus", a.id))
                    self.queue[s].append(("arrive", a.id))
                    if a.role == "student":
                        self.queue[e - 2].append(("exit", a.id))
                    self.queue[e].append(("leave", a.id))
            for v, args in day["timed"]:
                self.queue[args.get("from", args.get("minute", 540))].append(("timed", v, args))
            for k, e in enumerate(day["mood_events"]):
                self.queue[e["minute"]].append(("mood_evt", k))
            if day["open"]:
                for m in rng.integers(545, 800, size=int(rng.poisson(0.94 * K))):
                    self.queue[int(m)].append(("timed", "infirmary", {"n": 1, "stay": int(rng.integers(20, 40))}))
            starts = {b["start"]: (bi, b) for bi, b in enumerate(D["blocks"])}
            self._snap(D["start"])
            for t in range(D["start"], D["end"] + 1):
                self.t_now = t
                block = self._block_at(t)
                if t in starts:
                    self._start_block(t, starts[t][1], starts[t][0])
                for item in self.queue.pop(t, []):
                    self._handle(t, item, block)
                self._behaviors(t, block)
                self._tally(t, block)
            self._snap(D["end"])
        else:
            self._snap(D["start"])
        if not day["open"]:                                   # staff-flow counters on closed days
            for (m, cam, zlabel, label) in self.cctv_plan:
                if label in self.CLOSED_LABELS and cam in self.cam_zone:
                    z = self.cam_zone[cam]
                    n = int(rng.poisson(2.5)) if anyone else 0
                    self.cctv.append(self._record(cam, z.id, m, label, z.measure, n, n))

    def _pre_mood(self, day):
        mc, M = self.bh["mood"], self.mood
        if not day["open"]:
            for a in self.students:
                if a.id in day["roll"]:
                    a.mood = clamp(a.mood + 0.3 * (M.student_base(a) - a.mood))
                    self.drv[a.id]["break from school"] += mc["recovery_on_closed_day"] * 0.3
            for a in self.agents:
                if a.role in ("teacher", "principal", "staff"):
                    a.mood = clamp(a.mood + 0.3 * (M.staff_base(a) - a.mood))
            return
        for a in self.students:
            if a.id not in day["roll"]:
                continue
            new_shift = 0.9 * a.shift + self.rng.normal(0, mc["shift_sd"])
            if a.id in day["present_students"]:
                target, d = M.student_target(a, day)
                M.pull(a, target + new_shift)
                self.drv[a.id]["recent change"] += (new_shift - a.shift) * mc["pull"]
                a.absent_streak = 0
                for k, v in d.items():
                    self.drv[a.id][k] += v * mc["pull"]
            else:
                a.absent_streak += 1
                self._adjust(a, mc["absence_drift"], "missed school")
            a.shift = new_shift
        sm = self.bh["staff_mood"]
        strain = any(e["type"] == "teacher_absence_and_cover_pressure" for e in day["events"])
        for a in self.agents:
            if a.role in ("teacher", "principal", "staff") and a.present_today:
                base = M.staff_base(a)
                load = sm["cover_period"] * self.cover_taken.get(a.id, 0)
                a.mood = clamp(a.mood + sm["pull"] * (base + load - a.mood))
                if load:
                    self.drv[a.id]["workload"] += load * sm["pull"]

    # ------------------------------------------------------------------ CLOSE
    def _close(self, day, rng):
        i, iso, st, anchor = day["i"], day["iso"], self.story, day["anchor"]
        K, mc = self.ov["randomness"]["intensity"], self.bh["mood"]
        opened = day["open"]
        pres = [a for a in self.students if a.id in day["present_students"]]
        roll_n, pres_n = len(day["roll"]), len(pres)
        att = pres_n / roll_n if opened and roll_n else 1.0
        late_n = sum(1 for a in pres if a.late_today)
        t_abs = len(day["teachers_absent"])
        moods = np.array([a.mood for a in pres]) if pres else np.array([60.0])
        # ---- feedback (what a survey would hear, drawn from today's moods)
        pos = neu = neg = 0
        themes = []
        if opened and pres:
            sample = rng.choice(pres_n, size=min(pres_n, int(rng.integers(55, 80))), replace=False)
            for j in sample:
                m = pres[j].mood + rng.normal(0, 9)
                neg += m < mc["feedback"]["negative_below"]
                pos += m > mc["feedback"]["positive_above"]
            neu = len(sample) - pos - neg
            waits = [a.queue_wait for a in pres if a.queue_wait > 0]
            if waits and np.mean(waits) > 8: themes.append("canteen queues")
            if self.uncovered: themes.append("teacher availability")
            if day["heat"] >= 1.2: themes.append("room comfort")
            if day["assess_grades"]: themes.append("assessment clarity")
            themes += [str(x) for x in rng.choice(THEMES, size=3, replace=False) if str(x) not in themes]
            themes = themes[:3]
        tstaff = [a for a in self.agents if a.role == "teacher" and a.present_today]
        t_pos = sum(a.mood > 72 for a in tstaff[:18]); t_str = sum(a.mood < 58 for a in tstaff[:18])
        disagreements = int(rng.poisson(0.71 * K)) + (2 if any(e["type"] == "student_teacher_conflict" for e in day["events"]) else 0)
        # ---- signals and counters the detector may see
        sig = dict(day["signals"])
        sig["weather_disruption_index"], sig["heat_pressure_index"] = day["weather"], day["heat"]
        sig["infirmary_entries"] = self.infirm_visits
        sig["cover_timetable_conflicts"] = max(sig.get("cover_timetable_conflicts", 0), len(self.uncovered))
        queries = int(rng.poisson(4.4)) + day["parent_queries"]
        cam = {}
        for r in self.cctv:
            key = {"CAM-CANTEEN": "canteen", "CAM-B1-COR": "corridor", "CAM-ROOM-8B": "room"}.get(r["camera_id"])
            if key and opened:
                cam[key] = r["deviation_pct"]
        metrics = dict(att=att, att_z=self.det.attendance_z(att, day["weekday"]) if opened else 0.0, weather=day["weather"],
                       heat=day["heat"], late=late_n, t_abs=t_abs, disagreements=disagreements, neg=int(neg), sig=sig,
                       queries=queries, cam=cam)
        minute_of = dict(day["sig_minute"], attendance_rate=510, late_arrivals=515, teachers_absent=525,
                         queue_estimate_deviation_pct=755, room_occupancy_dev_pct=790, teacher_student_disagreements=570,
                         negative_count=570, queries=620, _default=540)
        alerts = self.det.review(iso, minute_of, metrics)
        self.alerts += alerts
        # ---- decisions
        state = {"attendance_rate": round(att, 3), "late_arrivals": late_n, "teachers_absent": t_abs, "cash_inr": round(self.fin.cash)}
        decisions = []
        if anchor:
            for d in st.decisions:
                if d["decision_id"].endswith(iso):
                    decisions.append({"decision_id": d["decision_id"], "date": iso, "title": d["title"], "risk_level": d["risk_level"],
                                      "autonomy_mode": d["autonomy_mode"], "status": d["status"], "action": d["action"],
                                      "reasoning": d["reasoning_summary"], "state_summary_used": d["state_summary_used"],
                                      "alert_id": "", "rule_code": "", "source": "story", "effect": None})
        else:
            for al in alerts:
                if al["rule_code"] == "classroom_friction_cluster" and disagreements < 3:
                    continue
                d = self.principal.propose(al, state)
                if d:
                    ap = self.ov["approvals"].get(d["decision_id"])
                    if d["status"] == "proposed_awaiting_approval" and ap is not None:
                        d["status"] = "implemented_with_human_review" if ap else "rejected_by_human"
                    d["source"] = "engine"
                    decisions.append(d)
                    if d["status"].startswith("implemented") and d["effect"]:
                        self.effects_active.append({"name": d["effect"][0], "until": i + d["effect"][1]})
        self.decisions += decisions
        # ---- finance
        if anchor:
            fin = self.fin.story_day(iso)
        else:
            extra = [(a, m) for a, m, _ in day["finance_items"]]
            support = (self.lever(i, "attendance_support_budget_inr_per_month") or 0) / 30.0
            backup = 14000 * min(int(self.lever(i, "bus_backup_capacity") or 0), 4) / 30.0
            summer = (self.lever(i, "summer_maintenance_budget_inr") or 0) / 16.0 if day["type"] == "summer_break_staff_only" else 0.0
            extra += [("attendance_support", support), ("transport_operations", backup), ("maintenance", summer)]
            ok = self.lever(i, "fee_change_approved")
            fee = (self.lever(i, "tuition_fee_delta_pct") or 0) / 100.0 if ok else 0.0
            tfee = (self.lever(i, "transport_fee_delta_pct") or 0) / 100.0 if ok else 0.0
            fin = self.fin.model_day(iso, 0, extra, payroll_extra=48000.0 * self.extra_teachers, fee_delta=fee, transport_delta=tfee)
        # Step Phase 3 Learning progression model
        eff = self.lever(i, "instructional_effectiveness") or 1.0
        diff = self.lever(i, "assessment_difficulty") or 1.0
        assess_dates = {w["start"] for w in self.story.assessments} | {w["end"] for w in self.story.assessments}
        acad_res = self.learning.step_day(
            date_str=iso,
            day_index=i,
            is_school_open=opened,
            present_student_ids={a.sid for a in pres},
            uncovered_classes=self.uncovered,
            scheduled_periods_per_day=6,
            instructional_effectiveness=float(eff),
            assessment_difficulty=float(diff),
            is_assessment_day=(iso in assess_dates),
        )

        # Step Phase 3 Transport fleet maintenance
        self.transport.step_day(iso)

        # Record Phase 3 Financial ledger transactions
        mc = next((v for v in self.fin.mca.values() if v["month"] == iso[:7]), None)
        if mc and (iso.endswith("-01") or i == 0):
            fee_pct = (self.lever(i, "tuition_fee_delta_pct") or 0) / 100.0 if self.lever(i, "fee_change_approved") else 0.0
            tfee_pct = (self.lever(i, "transport_fee_delta_pct") or 0) / 100.0 if self.lever(i, "fee_change_approved") else 0.0
            self.ledger.bill_student_fees(iso, mc["tuition_due"] * (1 + fee_pct), mc["transport_due"] * (1 + tfee_pct))
        if fin.get("inflow", 0) > 0:
            self.ledger.collect_fees(iso, float(fin["inflow"]))
        if fin.get("outflow", 0) > 0:
            self.ledger.disburse_payroll(iso, float(fin["outflow"]))

        # Step Phase 4 Cognitive Population Daily State
        pres_ids = {a.id for a in pres}
        uncovered_set = set(self.uncovered)
        cog_res = self.cognitive.step_daily_states(iso, opened, pres_ids, uncovered_set)

        # ---- flags
        flags = self._flags(day, alerts, decisions)
        incidents = day["incidents"]
        res = {
            "i": i, "date": iso, "dow": self.calendar.info(i)["dow"], "type": day["type"], "open": opened, "anchor": anchor,
            "enrolled": roll_n, "present": pres_n, "absent": roll_n - pres_n if opened else 0, "late": late_n,
            "attendance_rate": round(att, 4) if opened else None, "teachers_absent": t_abs,
            "mood_avg": round(float(moods.mean()), 1), "mood_low_share": round(float((moods < self.bh["mood"]["low"]).mean()), 3) if opened else 0,
            "feedback": {"pos": int(pos), "neu": int(neu), "neg": int(neg), "themes": themes},
            "teacher_feedback": {"positive": int(t_pos), "strained": int(t_str)},
            "queries": queries, "disagreements": disagreements, "signals": sig, "weather": day["weather"], "heat": day["heat"],
            "caught": self.stats["caught"], "infirmary": self.infirm_visits, "uncovered": len(self.uncovered),
            "canteen_peak_queue": max((r["observed_count"] for r in self.cctv if r["camera_id"] == "CAM-CANTEEN"), default=0),
            "finance": fin, "cctv": self.cctv, "incidents": incidents, "alerts": alerts, "decisions": decisions,
            "flags": flags, "events": [e["id"] for e in day["events"]],
            "teachers_absent_names": [self.agents[x].name for x in sorted(day["teachers_absent"])],
            "academics": acad_res,
            "transport": self.transport.get_transport_metrics(),
            "ledger_status": self.ledger.verify_reconciliation(iso),
            "cognitive": cog_res,
        }
        self.flags += flags
        res["_micro"] = {"paths": self.paths, "snaps": self.snaps, "drv": self.drv, "mood_end": {a.id: a.mood for a in self.agents if a.role != "visitor"}, "cam": dict(self.cam_series)}
        return res

    def _flags(self, day, alerts, decisions):
        iso, out = day["iso"], []
        add = lambda **k: out.append(dict(id=f"F-{iso}-{len(out)+1}", date=iso, day=day["i"], **k))
        for a in alerts:
            add(minute=a["minute"], kind="alert", sev=SEVERITY[a["severity"]], vis="operator", title=a["rule_code"].replace("_", " ").capitalize(),
                text=a["text"], zone="", ref=a["alert_id"], evidence=a["evidence"])
        for inc in day["incidents"]:
            if SEVERITY[inc["severity"]] >= 2:
                add(minute=inc["minute"], kind="incident", sev=SEVERITY[inc["severity"]], vis="operator", title=inc["title"],
                    text=inc["summary"], zone=inc["zone"], ref=inc["event_id"])
        for d in decisions:
            add(minute=600, kind="decision", sev={"low": 1, "medium": 2, "high": 3}[d["risk_level"]], vis="operator", title=d["title"],
                text=f'{d["status"].replace("_", " ")}: {d["action"]}', zone="", ref=d["decision_id"])
        for ev in day["events"]:
            add(minute=min([x["minute"] for x in day["incidents"] if x["event_id"] == ev["id"]] or [540]), kind="event",
                sev=SEVERITY[ev["severity"]], vis="author", title=ev["title"],
                text=f'Hidden cause: {ev.get("cause") or "scenario-defined"}', zone="", ref=ev["id"], source=ev["source"])
        prev = self.calendar.info(day["i"] - 1)["type"] if day["i"] else ""
        if day["type"] != prev and day["type"] not in ("instructional_day", "limited_school_day", "weekly_closure"):
            add(minute=480, kind="calendar", sev=0, vis="all", title=day["type"].replace("_", " ").capitalize(),
                text="School calendar change.", zone="", ref="")
        return out

    # ------------------------------------------------------------------- STEP
    def step(self, i):
        rng = self.day_rng(i)
        day = self._plan(i, rng)
        self._play(day, rng)
        return self._close(day, rng)

    def run(self, on_day=None, progress=None):
        for i in range(self.ov["start_day"], self.ov["end_day"] + 1):
            res = self.step(i)
            self.days.append({k: v for k, v in res.items() if k != "_micro"})
            if on_day:
                on_day(i, res)
            if progress:
                progress(i, self.ov["end_day"])
        return self.days
