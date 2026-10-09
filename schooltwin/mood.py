"""Mood: a 0-100 tendency for each person, with reasons attached. Not a diagnosis, not a measurement.

Each morning a person's mood moves part of the way to a target built from who they are (baseline) and what
today is like (drivers). Things that happen during the day nudge it further. Every nudge is recorded under a
driver code so the player can answer 'why is this student low today?'.
"""
DRIVERS = ["baseline", "weather", "heat", "assessment", "uncovered class", "friends around", "no friends around",
           "missed school", "break from school", "arrived late", "event", "canteen wait", "crowding",
           "caught in a hidden area", "time outdoors", "workload", "recent change"]
CODE = {n: i for i, n in enumerate(DRIVERS)}

STAFF_TRAIT = {"stretched": -6, "guarded": -2, "calm": 4, "measured": 3, "warm": 4, "organised": 3, "organized": 3,
               "reputation-conscious": -1, "overcommitted": -5, "burned": -6, "cautious": 0, "supportive": 3}


def clamp(x):
    return max(0.0, min(100.0, x))


class Mood:
    def __init__(self, bh):
        self.c = bh["mood"]
        self.s = bh["staff_mood"]

    def student_base(self, a):
        c = self.c
        t = sum(c["temperament"].get(x, 0) for x in a.temperament[:2])
        return clamp(c["start"] + t + c["academic_weight"] * (a.acad - 67)
                     + c["attendance_weight"] * (a.att_prop - 0.93) - c["discipline_weight"] * (a.disc_risk - 0.2))

    def staff_base(self, a):
        return clamp(self.s["start"] + sum(v for k, v in STAFF_TRAIT.items() if any(k in t.lower() for t in a.traits)))

    def student_target(self, a, day):
        """Return (target, {driver: delta}) for a present student."""
        c, d = self.c, {}
        base = self.student_base(a)
        d["weather"] = c["weather"] * day["weather"]
        d["heat"] = c["heat"] * max(0.0, day["heat"] - 1.0)
        if a.grade in day["assess_grades"]:
            tmp = next((c["assessment"][t] for t in a.temperament if t in c["assessment"]), c["assessment"]["default"])
            d["assessment"] = tmp
        d["friends around" if day["friends"].get(a.id, 0) >= 2 else "no friends around"] = (
            c["friend_present"] if day["friends"].get(a.id, 0) >= 2 else c["no_friend_present"] if day["friends"].get(a.id, 0) == 0 else 0)
        d = {k: v for k, v in d.items() if v}
        return clamp(base + sum(d.values())), d

    def pull(self, a, target, staff=False):
        k = self.s["pull"] if staff else self.c["pull"]
        a.mood = clamp(a.mood + k * (target - a.mood))
