"""Events: the 'overview' a user hands the engine, and what each event actually does.

An event is plain data: {id, date, type, severity, params}. Each TYPE maps to a template that turns it into
a list of EFFECTS (small verbs the engine understands). Story events, your own events and randomly generated
events all use the same templates, so a transport spike you add behaves like the one in the story.

Effect verbs (the engine implements each):
  absence        macro: scale absence this day                  {mult, grades?}      (generate mode only)
  late_riders    macro: bus riders arrive late                  {n, delay:[lo,hi], routes}
  teacher_absent macro: named teachers out                      {names | count}
  mood           lower or raise mood of a group                 {room|ids|all, n?, delta, minute}
  queue_extra    pull students into a zone for a while          {zone, n, from, to}
  visitors       parents/guests appear in a zone                {n, zone, from, to}
  close_zone     a room shuts mid-day; occupants move           {zone, from, to?}
  relocate       a class moves to another room                  {room, from, to}
  infirmary      students visit the nurse                       {n, minute, stay}
  staff_visit    staff go and deal with something               {roles, zone, from, to}
  signal         operational counters the detector can see      {name: value}
  incident       an entry in the incident register              {kind, summary, zone?, minute, severity}
  parent_queries extra queries and complaints                   {n, topics}
  finance        an unplanned cost                              {account, amount, desc}
  staff_notice   a resignation notice                           {name}
"""
import re
from dataclasses import dataclass, field

SEVERITY = {"low": 1, "medium": 2, "high": 3}

ALIASES = {
    "rain": "weather_attendance_dip",
    "fog": "weather_attendance_dip",
    "bus_breakdown": "transport_lateness_spike",
    "power_cut": "computer_lab_circuit_trip",
    "sick_teacher": "teacher_absence_and_cover_pressure",
    "heatwave": "heat_and_utility_pressure",
    "open_day": "annual_day_crowd_buildup",
    "fight": "serious_student_fight",
    "student_fight": "serious_student_fight",
    "serious_fight": "serious_student_fight",
    "prohibited_business": "suspected_prohibited_business",
    "policy_violation": "suspected_prohibited_business",
    "teacher_resignation": "teacher_resignation_notice",
    "fee_increase": "school_fee_increase",
    "teacher_hired": "additional_teacher_hired",
    "water_cooler": "water_cooler_breakdown",
    "cooler_breakdown": "water_cooler_breakdown",
    "strike": "collective_strike",
    "staff_strike": "collective_strike",
    "teacher_strike": "collective_strike",
}

TITLES = {
    "weather_attendance_dip": "Weather-related attendance dip",
    "student_teacher_conflict": "Class conflict over an assessment",
    "lab_inventory_discrepancy": "Lab kit count mismatch",
    "first_aid_visit": "Student first-aid visit",
    "transport_lateness_spike": "Late buses: arrival spike",
    "annual_day_crowd_buildup": "Annual day crowd build-up",
    "duplicate_fee_reminder": "Duplicate fee reminder sent",
    "teacher_absence_and_cover_pressure": "Teacher absence, cover pressure",
    "exam_paper_printing_error": "Exam papers printed incomplete",
    "marks_import_anomaly": "Marks import mismatch",
    "classroom_fan_failure": "Classroom fans fail in the heat",
    "bus_gate_pillar_scrape": "Bus scrapes the gate pillar",
    "teacher_resignation_notice": "Teacher resignation notice",
    "fee_transparency_queries": "Parents ask about fee heads",
    "heat_and_utility_pressure": "Early heat and utility pressure",
    "computer_lab_circuit_trip": "Computer lab circuit trips",
    "fuel_invoice_variance": "Fuel invoice higher than quote",
    "water_motor_failure": "Water motor fails",
    "serious_student_fight": "Serious student altercation (3 students)",
    "suspected_prohibited_business": "Suspected policy violation (allegation under review)",
    "school_fee_increase": "School fee revision announcement",
    "additional_teacher_hired": "Additional faculty member onboarded",
    "water_cooler_breakdown": "Water cooler unit breakdown",
    "collective_strike": "Staff collective strike action",
}


@dataclass
class Effect:
    verb: str
    args: dict = field(default_factory=dict)


def make_event(date, etype, severity="medium", params=None, source="user", cause="", impact="", resolution="", eid=None):
    etype = ALIASES.get(etype, etype)
    return {"id": eid or f"EV-{date}-{etype[:10]}", "date": date, "type": etype, "severity": severity,
            "params": params or {}, "source": source, "cause": cause, "impact": impact, "resolution": resolution,
            "title": TITLES.get(etype, etype.replace("_", " ").capitalize())}


def story_events(story, disabled=()):
    out = []
    for e in story.events:
        if e["event_id"] in disabled:
            continue
        ev = make_event(e["date"], e["type"], e["severity"], source="story", cause=e["hidden_cause"],
                        impact=e["impact"], resolution=e["resolution"], eid=e["event_id"])
        ev["signature"] = story.event_signature(e)
        ev["numbers"] = story.numbers_in(e["impact"])
        out.append(ev)
    return out


def random_events(story, rng, per_month, types, open_dates, taken):
    """Sprinkle extra events over open days. Same templates as the story's own."""
    out = []
    months = sorted({d[:7] for d in open_dates})
    for m in months:
        days = [d for d in open_dates if d.startswith(m) and d not in taken]
        for _ in range(int(rng.poisson(per_month))):
            if not days:
                break
            d = str(rng.choice(days)); days.remove(d)
            t = str(rng.choice(types))
            out.append(make_event(d, t, str(rng.choice(["low", "medium", "medium", "high"])), source="random"))
    return out


def signature_library(story):
    """What each event type looks like to the detector, learned from the story's own events."""
    lib = {}
    for e in story.events:
        lib.setdefault(e["type"], story.event_signature(e))
    return lib


def _n(ev, i, default):
    nums = ev.get("numbers") or []
    return nums[i] if len(nums) > i else default


def effects_for(ev, sig_lib, rng):
    """Turn one event into effects. Numbers come from the story's impact text where it has them."""
    t, p, sev = ev["type"], ev["params"], ev["severity"]
    fx = []
    sig = dict(ev.get("signature") or sig_lib.get(t, {}))
    sig.pop("infirmary_entries", None)              # counted from real visits in the simulation, never injected
    sig.update(p.get("signals", {}))
    if sig:
        fx.append(Effect("signal", sig))
    inc = lambda kind, summary, zone="", minute=540: fx.append(Effect("incident", dict(kind=kind, summary=summary, zone=zone, minute=minute, severity=sev)))

    env_covers = p.get("env_covers", ev["source"] == "story")      # the story's weather/heat index already lowers attendance
    if t == "weather_attendance_dip":
        if not env_covers:
            fx.append(Effect("absence", {"mult": p.get("mult", 1.5)}))
        fx.append(Effect("mood", {"all": "students", "delta": -4, "minute": 520}))
        inc(t, "Cold, foggy morning; several feeder roads slow. Families used discretion.", "main_gate", 500)
    elif t == "student_teacher_conflict":
        room = p.get("room", "C8B")
        fx += [Effect("mood", {"room": room, "n": 6, "delta": -10, "minute": 570}),
               Effect("mood", {"room": room, "delta": -3, "minute": 570}),
               Effect("parent_queries", {"n": 2, "topics": ["assessment notice"]})]
        inc(t, "Six students file a joint concern about an unannounced worksheet; one lesson loses 9 minutes.", room, 570)
    elif t == "lab_inventory_discrepancy":
        fx.append(Effect("staff_visit", {"roles": ["lab_assistant"], "zone": "lab_sci_2", "from": 640, "to": 690}))
        fx.append(Effect("staff_visit", {"roles": ["lab_assistant"], "zone": "store_room", "from": 700, "to": 720}))
        inc(t, "Three lab kits moved to an adjacent room for a demonstration; the return register was not signed.", "lab_sci_2", 660)
    elif t == "first_aid_visit":
        fx.append(Effect("infirmary", {"n": p.get("n", 4), "minute": 600, "stay": 40}))
        inc(t, "A student felt light-headed after skipping breakfast; cause reported, not medically confirmed.", "infirmary", 600)
    elif t == "transport_lateness_spike":
        fx.append(Effect("late_riders", {"n": int(p.get("n_students", _n(ev, 0, 110))), "routes": p.get("routes", 3),
                                         "delay": p.get("delay", [int(_n(ev, 1, 8)), int(_n(ev, 2, 24))])}))
        fx.append(Effect("parent_queries", {"n": 6, "topics": ["bus timing"]}))
        inc(t, "A driver calls in sick before dispatch; three routes are merged and arrive late.", "bus_bay", 515)
    elif t == "annual_day_crowd_buildup":
        peak = int(_n(ev, 0, 70))
        fx += [Effect("visitors", {"n": int(p.get("visitors", 90)), "zone": "corridor_0", "from": 700, "to": 790}),
               Effect("queue_extra", {"zone": "canteen", "n": max(peak - 30, 20), "from": 745, "to": 775})]
        inc(t, "Rehearsals and parent check-in converge at one junction; queue wait reaches about 11 minutes.", "canteen", 755)
    elif t == "duplicate_fee_reminder":
        fx.append(Effect("parent_queries", {"n": int(p.get("queries", 16)), "topics": ["fee reminder", "payment status"]}))
        inc(t, "A bulk reminder was sent twice after two recipient exports overlapped.", "admin_lobby", 620)
    elif t == "teacher_absence_and_cover_pressure":
        fx.append(Effect("teacher_absent", {"names": p.get("names", ["Ananya Malik"]), "count": p.get("count", 1), "days": p.get("days", 3)}))
        fx.append(Effect("mood", {"all": "teachers", "delta": -3, "minute": 540}))
        inc(t, "A three-day illness-related absence; the prefilled cover plan contains two clashes.", "staffroom", 520)
    elif t == "exam_paper_printing_error":
        fx.append(Effect("mood", {"room": p.get("room", "C10A"), "n": 24, "delta": -6, "minute": 570}))
        fx.append(Effect("staff_visit", {"roles": ["admin_accounts", "IT"], "zone": "admin_lobby", "from": 540, "to": 620}))
        inc(t, "The last three pages of one exam variant are missing in 24 packets; reprint delays the start.", "admin_lobby", 540)
    elif t == "marks_import_anomaly":
        fx.append(Effect("staff_visit", {"roles": ["IT", "admin_accounts"], "zone": "admin_lobby", "from": 600, "to": 700}))
        inc(t, "An import sheet points at the wrong column for 18 records; found before report cards are released.", "admin_lobby", 640)
    elif t == "classroom_fan_failure":
        fx += [Effect("relocate", {"room": p.get("room", "C8B"), "from": 778, "to": "library"}),
               Effect("mood", {"room": p.get("room", "C8B"), "delta": -6, "minute": 778}),
               Effect("staff_visit", {"roles": ["maintenance_gardener"], "zone": p.get("room", "C8B"), "from": 790, "to": 840})]
        inc(t, "Two ageing fans fail on a warm afternoon; the class changes room after 18 minutes.", p.get("room", "C8B"), 778)
    elif t == "bus_gate_pillar_scrape":
        fx += [Effect("late_riders", {"n": int(p.get("n_students", 40)), "routes": 1, "delay": [4, 12]}),
               Effect("staff_visit", {"roles": ["security", "transport_supervisor"], "zone": "main_gate", "from": 485, "to": 560})]
        inc(t, "A driver takes a tight turn around a delivery vehicle and scrapes the gate pillar; no injuries.", "main_gate", 490)
    elif t == "teacher_resignation_notice":
        fx.append(Effect("staff_notice", {"name": p.get("name", "Ritu Kapoor")}))
        fx.append(Effect("mood", {"all": "teachers", "delta": -2, "minute": 540}))
        inc(t, "A teacher gives four weeks' notice after repeated unplanned cover and committee duties.", "staffroom", 560)
    elif t == "fee_transparency_queries":
        fx += [Effect("parent_queries", {"n": int(p.get("queries", 38)), "topics": ["fee heads", "fee increase rumour"]}),
               Effect("visitors", {"n": 28, "zone": "admin_lobby", "from": 600, "to": 720})]
        inc(t, "After a rumour of an increase, parents ask for an itemised explanation of fee heads.", "admin_lobby", 620)
    elif t == "heat_and_utility_pressure":
        if not env_covers:
            fx.append(Effect("absence", {"mult": p.get("mult", 1.7), "grades": ["Nursery", "KG", "Class 1", "Class 2", "Class 3"]}))
        fx.append(Effect("mood", {"all": "students", "delta": -5, "minute": 520}))
        fx.append(Effect("finance", {"account": "utilities", "amount": 9000, "desc": "Extra cooling load"}))
        inc(t, "An early hot spell raises cooling demand; some families keep younger children home.", "north_ground", 540)
    elif t == "computer_lab_circuit_trip":
        fx += [Effect("close_zone", {"zone": "comp_lab_1", "from": 665}),
               Effect("staff_visit", {"roles": ["IT", "maintenance_gardener"], "zone": "comp_lab_1", "from": 670, "to": 780})]
        inc(t, "The lab circuit trips under load; the session moves to supervised paper work. No injury.", "comp_lab_1", 665)
    elif t == "fuel_invoice_variance":
        fx.append(Effect("finance", {"account": "transport_operations", "amount": 3360, "desc": "Fuel invoice variance pending reconciliation"}))
        inc(t, "Fuel vendor invoice is 8% above the written quote; quantities and taxes need reconciliation.", "admin_lobby", 600)
    elif t == "water_motor_failure":
        fx += [Effect("finance", {"account": "maintenance", "amount": 18500, "desc": "Repair parts and labour"}),
               Effect("finance", {"account": "sanitation_and_water", "amount": 12000, "desc": "Emergency tanker"}),
               Effect("staff_visit", {"roles": ["maintenance_gardener", "housekeeping"], "zone": "pump_house", "from": 540, "to": 700})]
        inc(t, "The campus water motor fails during the student-free maintenance period.", "pump_house", 540)
    elif t == "serious_student_fight":
        sids = p.get("student_ids") or ev.get("student_ids") or ["STU-0012", "STU-0015", "STU-0021"]
        loc = p.get("location") or ev.get("location") or "playground"
        fx += [
            Effect("mood", {"ids": sids, "delta": -25, "minute": 570}),
            Effect("infirmary", {"n": min(len(sids), 3), "minute": 575, "stay": 35}),
            Effect("staff_visit", {"roles": ["security", "nurse"], "zone": loc, "from": 570, "to": 615}),
        ]
        inc(t, f"Physical altercation involving three students in {loc}; staff intervened promptly, students escorted for minor first-aid evaluation and disciplinary review.", loc, 570)
    elif t == "suspected_prohibited_business":
        sids = p.get("student_ids") or ev.get("student_ids") or ["STU-0044"]
        loc = p.get("location") or ev.get("location") or "admin_lobby"
        status = p.get("investigation_status", "under_review")
        fx += [
            Effect("mood", {"ids": sids, "delta": -8, "minute": 630}),
            Effect("staff_visit", {"roles": ["counsellor", "admin_accounts"], "zone": loc, "from": 630, "to": 680}),
            Effect("parent_queries", {"n": 3, "topics": ["policy compliance", "investigation status"]}),
        ]
        inc(t, f"Administrative inquiry into alleged unauthorized peer transaction in {loc}; factual review proceeding without presumption of wrongdoing (status: {status}).", loc, 630)
    elif t == "school_fee_increase":
        cat = p.get("fee_category", "tuition")
        pct_val = p.get("delta_pct", 10.0)
        fx += [
            Effect("parent_queries", {"n": int(p.get("queries", 32)), "topics": [f"{cat} fee increase", "fee schedule breakdown"]}),
            Effect("visitors", {"n": 24, "zone": "admin_lobby", "from": 570, "to": 720}),
        ]
        inc(t, f"Proposed {cat} fee revision ({pct_val:+g}%) communicated to parents; information desk active in administrative lobby.", "admin_lobby", 540)
    elif t == "additional_teacher_hired":
        tname = p.get("teacher_name", "Pooja Sharma")
        subj = p.get("subject_or_role", "Social Science")
        fx += [
            Effect("mood", {"all": "teachers", "delta": 3, "minute": 540}),
            Effect("staff_visit", {"roles": ["teacher"], "zone": "staffroom", "from": 500, "to": 560}),
        ]
        inc(t, f"New faculty member {tname} onboarded for {subj}; lesson coverage pressure relieved.", "staffroom", 520)
    elif t == "water_cooler_breakdown":
        loc = p.get("location") or ev.get("location") or "corridor_1"
        fx += [
            Effect("queue_extra", {"zone": "canteen", "n": 35, "from": 600, "to": 750}),
            Effect("staff_visit", {"roles": ["maintenance_gardener", "housekeeping"], "zone": loc, "from": 600, "to": 780}),
            Effect("finance", {"account": "sanitation_and_water", "amount": 8500, "desc": "Water cooler compressor repair and bottled dispenser supply"}),
            Effect("mood", {"all": "students", "delta": -6, "minute": 620}),
        ]
        inc(t, f"Water cooler unit failed in {loc}; students redirecting to alternative water points.", loc, 600)
    elif t == "collective_strike":
        loc = p.get("location") or ev.get("location") or "north_ground"
        fx += [
            Effect("staff_visit", {"roles": ["teacher", "principal"], "zone": loc, "from": 520, "to": 780}),
            Effect("mood", {"all": "teachers", "delta": -15, "minute": 520}),
            Effect("parent_queries", {"n": 45, "topics": ["uncovered classes", "staff action"]}),
            Effect("visitors", {"n": 30, "zone": "admin_lobby", "from": 540, "to": 750}),
        ]
        inc(t, f"Staff collective strike underway at {loc}; classes evacuated to grounds and supervision protocols initiated.", loc, 520)
    return fx
