"""Timetable and 'where should this person be right now?' for every role."""
import numpy as np


def weekly_timetable(seed, weekday, bi, teacher_ids, room_ids):
    """Stable weekly rota: the same weekday and period always put the same teachers in the same rooms."""
    rng = np.random.default_rng([seed, 5, weekday, bi])
    order = rng.permutation(teacher_ids)
    return {int(order[k]): room_ids[k] for k in range(min(len(order), len(room_ids)))}


def target_zone(a, block, teach_zone):
    t, r = block["type"], a.role
    if r == "student":
        if t == "arrival":
            return a.home_zone if a.arrival_pref == "classroom" else "north_ground"
        if t == "assembly":
            if a.late_today:
                return "main_gate"                 # latecomers wait at the gate until prayer ends
            return "wash_0" if a.dodge else "north_ground"
        if t == "class":
            return a.home_zone
        if t in ("break", "lunch"):
            pref = a.break_pref if t == "break" else a.lunch_pref
            return a.home_zone if pref == "classroom" else pref
        return a.home_zone                         # dismissal: pack up, then walk out ("exit")
    if r == "teacher":
        if t == "assembly":
            return "north_ground"
        if t == "class":
            return teach_zone.get(block["name"], {}).get(a.id, "staffroom")
        if t in ("break", "lunch"):
            return a.break_pref
        return "staffroom"
    if r == "principal":
        return "north_ground" if t == "assembly" else "principal_office"
    s = a.subrole
    if s in ("vice_principal", "coordinator"):
        return "north_ground" if t == "assembly" else a.home_zone
    if s in ("driver", "bus_attendant", "transport_supervisor"):
        return "bus_bay"
    return a.home_zone
