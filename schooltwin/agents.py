"""Everyone on campus. Students and staff come straight from the story's roster, with real names and IDs."""
from dataclasses import dataclass, field

import numpy as np

from .story import grade_short, room_id

GRADE_ORDER = ["Nursery", "KG"] + [f"Class {i}" for i in range(1, 13)]


@dataclass
class Agent:
    id: int
    role: str                          # student | teacher | principal | staff | visitor
    sid: str = ""                      # story id, e.g. STU-0001 / STF-020
    name: str = ""
    subrole: str = ""                  # staff roles: vice_principal, security, nurse, ...
    grade: str = ""
    section: str = ""
    home_zone: str = ""
    temperament: list = field(default_factory=list)
    traits: list = field(default_factory=list)
    strengths: list = field(default_factory=list)
    frictions: list = field(default_factory=list)
    arc: str = ""
    character: bool = False            # one of the 24 named protagonists
    route: str = ""
    att_prop: float = 0.93             # hidden: chance of coming in on a normal day
    disc_risk: float = 0.2             # hidden: tendency to bend rules
    acad: float = 67.0                 # hidden: academic index
    enroll: str = ""
    withdraw: str = ""
    exit_date: str = ""
    # live state
    zone: str = "outside"
    floor: int = 0
    x: float = 0.0
    y: float = 0.0
    target: str = ""
    away_until: int = -1
    away_zone: str = ""
    # per-day
    present_today: bool = False
    late_today: bool = False
    dodge: bool = False
    shifts: list = field(default_factory=list)      # [(arrive, leave), ...]
    arrive: int = 0
    leave: int = 0
    break_pref: str = "playground"
    lunch_pref: str = "playground"
    arrival_pref: str = "north_ground"
    queue_wait: float = 0.0
    # long-lived
    mood: float = 62.0
    shift: float = 0.0                 # slow personal drift in mood (persists for days)
    absent_streak: int = 0
    knows_spots: list = field(default_factory=list)
    friends: list = field(default_factory=list)
    patrol_prob: float = 0.0


STAFF_HOME = {
    "principal": "principal_office", "vice_principal": "admin_lobby", "coordinator": "staffroom",
    "teacher": "staffroom", "counselor": "counselling_room", "special_educator": "staffroom",
    "nurse": "infirmary", "admin_accounts": "admin_lobby", "librarian": "library",
    "lab_assistant": "lab_sci_1", "IT": "comp_lab_1", "security": "main_gate",
    "housekeeping": "corridor_0", "maintenance_gardener": "playground",
    "transport_supervisor": "bus_bay", "driver": "bus_bay", "bus_attendant": "bus_bay",
    "canteen_staff": "canteen",
}
SPREAD = {"lab_assistant": ["lab_sci_1", "lab_sci_2", "lab_sci_3"], "IT": ["comp_lab_1", "comp_lab_2"],
          "housekeeping": ["corridor_0", "corridor_1", "corridor_2", "wash_0", "wash_1", "wash_2"],
          "security": ["main_gate", "main_gate", "main_exit", "stair_A", "playground", "north_ground"],
          "maintenance_gardener": ["playground", "store_room", "pump_house"]}


def create_population(story, world, bh, rng):
    agents, ks = [], bh["blind_spots"]["initial_knowledge"]
    spots = world.blind_spot_ids()
    pat = bh["patrol"]["visit_prob_per_minute"]

    def new(role, **kw):
        a = Agent(id=len(agents), role=role, **kw)
        agents.append(a)
        return a

    by_class = {}
    for s in story.students:
        prof = s["profile"]
        char = story.characters.get(s["name"])
        gi = GRADE_ORDER.index(s["grade"])
        a = new("student", sid=s["student_id"], name=s["name"], grade=s["grade"], section=s["section"],
                temperament=list(prof["temperament"]) if not char else list(char["traits"][:2]),
                strengths=list(prof["strengths"]) if not char else list(char["strengths"]),
                frictions=list(prof["frictions"]) if not char else list(char["frictions"]),
                traits=list(char["traits"]) if char else [], arc=char["arc"] if char else "",
                character=bool(char), route=s["transport_route"] or "",
                att_prop=s["attendance_propensity_hidden"], disc_risk=s["discipline_risk_hidden"],
                acad=s["academic_index_hidden"], enroll=s["enrollment_date"], withdraw=s["withdrawal_date"] or "")
        if rng.random() < ks["base"] + ks["per_grade_index"] * gi:
            a.knows_spots = [str(rng.choice(spots))]
        by_class.setdefault((s["grade"], s["section"]), []).append(a.id)
    for ids in by_class.values():
        for i in ids:
            others = [j for j in ids if j != i]
            agents[i].friends = [int(x) for x in rng.choice(others, size=min(3, len(others)), replace=False)]

    k = {}
    for s in story.staff:
        role = s["role"]
        n = k.get(role, 0); k[role] = n + 1
        home = SPREAD[role][n % len(SPREAD[role])] if role in SPREAD else STAFF_HOME[role]
        agents_role = "teacher" if role == "teacher" else "principal" if role == "principal" else "staff"
        new(agents_role, sid=s["staff_id"], name=s["name"], subrole=role, home_zone=home,
            traits=list(s.get("traits", [])), strengths=list(s.get("strengths", [])),
            frictions=list(s.get("frictions", [])), arc=s.get("arc", "") or s.get("character_note", ""),
            exit_date=s.get("exit_date") or "", patrol_prob=pat.get(role, 0.0))
    for i in range(6):                                       # contractor-run canteen: not on payroll
        new("staff", sid=f"CON-CANTEEN-{i+1:02d}", name=f"Canteen staff {i+1}", subrole="canteen_staff", home_zone="canteen")
    for i in range(160):                                     # parents / guests, activated only by events
        new("visitor", sid=f"VIS-{i+1:03d}", name="Visitor", subrole="visitor", home_zone="admin_lobby")
    return agents
