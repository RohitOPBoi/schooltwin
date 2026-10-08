"""The story file, indexed.

The file plays three roles and this module keeps them apart:
  * SCENARIO INPUT   calendar, roster, staff, facilities, cameras, the causes of events
  * REFERENCE        the author's daily history: what the engine should look like when it is right
  * ANSWER KEY       hidden causes of the 18 planted events, used only by the evaluator
"""
import copy
import json
import re
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT

STORY_PATH = ROOT / "story" / "saraswati_heights_story.json"
APRIL_PROMOTION = "2026-04-01"


def grade_short(g):
    return {"Nursery": "N", "KG": "KG"}.get(g, g.replace("Class ", ""))


def room_id(grade, section):
    return f"C{grade_short(grade)}{section}"


def minutes_of(ts):
    """'2026-01-20T08:20:00+05:30' -> 500"""
    return int(ts[11:13]) * 60 + int(ts[14:16])


class Story:
    def __init__(self, path=None):
        raw = json.loads(Path(path or STORY_PATH).read_text(encoding="utf-8"))
        self.raw = raw
        self.name = raw["school_configuration"]["name"]
        self.cfg = raw["school_configuration"]
        self.days = list(raw["five_month_daily_timeline"])
        self.students = raw["student_roster"]["records"]
        self._extend_calendar_to_year_end()
        self.by_date = {d["date"]: d for d in self.days}
        self.dates = [d["date"] for d in self.days]
        self.characters = {c["name"]: c for c in raw["student_roster"]["character_profiles"]["students"]}
        self.staff = raw["operational_staff_roster"]["staff"]
        self.events = raw["ground_truth_events_hidden_from_detector"]["events"]
        self.alerts = raw["detector"]["alerts"]
        self.decisions = raw["ai_principal"]["decision_log"]
        self.policy = raw["ai_principal"]["policy"]
        self.assessments = raw["academic_calendar_and_assessments"]["assessment_windows"]
        self.ledger = raw["financial_ledger"]
        self.levers = raw["checkpoints_and_forking"]["scenario_levers"]
        self.cameras = self.cfg["cameras"]
        self.summary = raw["summary_metrics"]

    def _extend_calendar_to_year_end(self):
        """Synthetically continues the school calendar beyond the 5-month baseline up to Day 364 (2026-12-31)."""
        current_len = len(self.days)
        if current_len >= 365:
            return

        base_date = date(2026, 1, 1)
        last_day = self.days[-1] if self.days else {}
        last_fin = copy.deepcopy(last_day.get("finance", {}))

        for i in range(current_len, 365):
            cur_date = base_date + timedelta(days=i)
            iso = cur_date.isoformat()
            dow = cur_date.strftime("%A")
            month = cur_date.month
            dom = cur_date.day
            weekday = cur_date.weekday()

            heat = 0.2
            weather = 0.05

            if month == 6:
                heat = 0.85
                weather = 0.05
                if weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                else:
                    day_type = "summer_break_staff_only"
                    is_open = False
            elif month == 7:
                heat = 0.55
                weather = 0.35
                if weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                elif weekday == 5:
                    sat_num = (dom - 1) // 7 + 1
                    if sat_num in (2, 4):
                        day_type = "weekly_closure"
                        is_open = False
                    else:
                        day_type = "limited_school_day"
                        is_open = True
                else:
                    day_type = "instructional_day"
                    is_open = True
            elif month == 8:
                heat = 0.40
                weather = 0.30
                if dom == 15:
                    day_type = "planned_closure"
                    is_open = False
                elif weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                elif weekday == 5:
                    sat_num = (dom - 1) // 7 + 1
                    if sat_num in (2, 4):
                        day_type = "weekly_closure"
                        is_open = False
                    else:
                        day_type = "limited_school_day"
                        is_open = True
                else:
                    day_type = "instructional_day"
                    is_open = True
            elif month == 9:
                heat = 0.30
                weather = 0.15
                if weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                elif weekday == 5:
                    sat_num = (dom - 1) // 7 + 1
                    if sat_num in (2, 4):
                        day_type = "weekly_closure"
                        is_open = False
                    else:
                        day_type = "limited_school_day"
                        is_open = True
                else:
                    day_type = "instructional_day"
                    is_open = True
            elif month == 10:
                heat = 0.15
                weather = 0.05
                if dom in (2, 20):
                    day_type = "planned_closure"
                    is_open = False
                elif weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                elif weekday == 5:
                    sat_num = (dom - 1) // 7 + 1
                    if sat_num in (2, 4):
                        day_type = "weekly_closure"
                        is_open = False
                    else:
                        day_type = "limited_school_day"
                        is_open = True
                else:
                    day_type = "instructional_day"
                    is_open = True
            elif month == 11:
                heat = 0.05
                weather = 0.10
                if dom in (8, 9):
                    day_type = "planned_closure"
                    is_open = False
                elif weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                elif weekday == 5:
                    sat_num = (dom - 1) // 7 + 1
                    if sat_num in (2, 4):
                        day_type = "weekly_closure"
                        is_open = False
                    else:
                        day_type = "limited_school_day"
                        is_open = True
                else:
                    day_type = "instructional_day"
                    is_open = True
            else:
                heat = 0.0
                weather = 0.15
                if dom >= 25:
                    day_type = "winter_break"
                    is_open = False
                elif weekday == 6:
                    day_type = "weekly_closure"
                    is_open = False
                elif weekday == 5:
                    sat_num = (dom - 1) // 7 + 1
                    if sat_num in (2, 4):
                        day_type = "weekly_closure"
                        is_open = False
                    else:
                        day_type = "limited_school_day"
                        is_open = True
                else:
                    day_type = "instructional_day"
                    is_open = True

            day_dict = {
                "date": iso,
                "day_of_week": dow,
                "day_number_in_run": i + 1,
                "day_type": day_type,
                "school_open_to_students": is_open,
                "student_enrollment": {"active": len(self.students)},
                "staffing": {"teachers": 58, "total_staff": 123},
                "academics": {},
                "student_feedback": {},
                "teacher_staff_feedback": {},
                "parent_feedback": {},
                "cctv_synthetic_event_stream": {"source": "synthetic CCTV event stream", "records": []},
                "incident_register_today": [],
                "character_observations_today": [],
                "daily_story": {"summary": f"Day {i} ({iso}): {day_type.replace('_', ' ').capitalize()}."},
                "finance": copy.deepcopy(last_fin),
                "principal_decision": None,
                "operational_signals": {
                    "source": "synthetic operational baseline continuation",
                    "signals": {
                        "lab_kit_count_variance_count": 0,
                        "infirmary_entries": 0,
                        "late_routes_count": 0,
                        "duplicate_bulk_message_alert": 0,
                        "cover_timetable_conflicts": 0,
                        "incomplete_exam_packet_count": 0,
                        "marks_import_row_mismatch_count": 0,
                        "fan_fault_reports": 0,
                        "gate_vehicle_flow_interruption": 0,
                        "new_staff_notice_count": 0,
                        "fee_head_queries": 0,
                        "heat_pressure_index": heat,
                        "electrical_trip_count": 0,
                        "fuel_invoice_variance_pct": 0.0,
                        "water_motor_fault_count": 0,
                        "weather_disruption_index": weather,
                    }
                }
            }
            self.days.append(day_dict)

    # ---------------------------------------------------------------- calendar
    def info(self, i):
        d = self.days[i]
        return {"date": d["date"], "dow": d["day_of_week"], "type": d["day_type"], "open": d["school_open_to_students"]}

    def weekday(self, i):
        return date.fromisoformat(self.dates[i]).weekday()

    # ----------------------------------------------------------------- students
    def grade_on(self, s, iso):
        return s["grade_on_2026_04_01"] if iso >= APRIL_PROMOTION else s["grade"]

    def on_roll(self, s, iso):
        if s["enrollment_date"] > iso:
            return False
        return s["withdrawal_date"] is None or iso < s["withdrawal_date"]

    def rooms(self):
        """Every (grade, section) that ever hosts a class, with the largest roll it ever has."""
        sizes = {}
        for iso in (self.dates[0], APRIL_PROMOTION, self.dates[150] if len(self.dates) > 150 else self.dates[-1]):
            cnt = {}
            for s in self.students:
                if self.on_roll(s, iso):
                    k = (self.grade_on(s, iso), s["section"])
                    cnt[k] = cnt.get(k, 0) + 1
            for k, n in cnt.items():
                sizes[k] = max(sizes.get(k, 0), n)
        order = ["Nursery", "KG"] + [f"Class {i}" for i in range(1, 13)]
        return sorted(sizes.items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1]))

    # -------------------------------------------------------------- reference
    def cctv_samples(self):
        """The camera sample schedule: [(minute, camera_id, zone, label)] seen on typical days."""
        seen = {}
        for d in self.days:
            for r in d["cctv_synthetic_event_stream"]["records"]:
                k = (minutes_of(r["timestamp"]), r["camera_id"], r["zone"], r["event_label"])
                seen[k] = seen.get(k, 0) + 1
        return sorted(k for k, n in seen.items() if n >= 10)

    def event_signature(self, ev):
        """Non-zero operational signals on the event's day: what the event looks like to the detector."""
        sig = self.by_date[ev["date"]]["operational_signals"]["signals"]
        return {k: v for k, v in sig.items() if v and k not in ("weather_disruption_index", "heat_pressure_index")}

    def numbers_in(self, text):
        return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]
