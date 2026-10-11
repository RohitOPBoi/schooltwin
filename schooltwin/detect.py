"""Rule-based detector. It sees only what an operator could see: daily counters, camera counts, feedback
numbers, operational signals. It never reads incident text, daily stories or the hidden causes.

Like the story's own detector, it is deliberately simple and a little noisy: alerts say 'look here', not
'this is why'. Every alert needs a person to review it."""
import numpy as np

RULES = [   # code, severity, test(metrics) -> evidence list or None, plain-language text
    ("attendance_arrival_deviation", "medium",
     lambda m: [("attendance_rate", m["att"]), ("weather_disruption_index", m["weather"])] if (m["att_z"] <= -2.4 and m["weather"] >= 0.5) or m["att_z"] <= -3.2 else None,
     "Arrival timing and attendance are outside the routine band; weather or transport are possible explanations, not proven causes."),
    ("classroom_friction_cluster", "medium",
     lambda m: [("teacher_student_disagreements", m["disagreements"]), ("negative_count", m["neg"])] if m["disagreements"] >= 2 and m["neg"] >= 8 else None,
     "A class-level disagreement cluster coincides with more negative feedback; review both student and teacher accounts before attributing fault."),
    ("inventory_register_mismatch", "medium",
     lambda m: [("lab_kit_count_variance_count", m["sig"].get("lab_kit_count_variance_count", 0))] if m["sig"].get("lab_kit_count_variance_count", 0) > 0 else None,
     "A lab kit count does not match the register. Recount before assuming loss."),
    ("infirmary_activity_spike", "low",
     lambda m: [("infirmary_entries", m["sig"].get("infirmary_entries", 0))] if m["sig"].get("infirmary_entries", 0) >= 4 else None,
     "More infirmary visits than usual. A count cannot say why; check with the nurse."),
    ("transport_arrival_spike", "medium",
     lambda m: [("late_routes_count", m["sig"].get("late_routes_count", 0)), ("late_arrivals", m["late"])] if m["sig"].get("late_routes_count", 0) > 0 or m["late"] >= 45 else None,
     "Bus-bay and gate flow arrive late. Several routes may share a cause."),
    ("crowd_buildup", "medium",
     lambda m: [("queue_estimate_deviation_pct", m["cam"].get("canteen", 0))] if m["cam"].get("canteen", 0) >= 85 or m["cam"].get("corridor", 0) >= 150 else None,
     "Counts at the canteen or corridor are well above their usual level. A count cannot show intent or cause."),
    ("communication_batch_duplicate", "medium",
     lambda m: [("duplicate_bulk_message_alert", 1), ("queries_and_complaints_count", m["queries"])] if m["sig"].get("duplicate_bulk_message_alert", 0) > 0 else None,
     "The same bulk message appears to have gone out twice."),
    ("cover_plan_conflict", "medium",
     lambda m: [("cover_timetable_conflicts", m["sig"].get("cover_timetable_conflicts", 0)), ("teachers_absent", m["t_abs"])] if m["sig"].get("cover_timetable_conflicts", 0) > 0 or m["t_abs"] >= 9 else None,
     "Teacher absence and cover plans do not line up. Some periods may have no suitable cover."),
    ("exam_material_integrity", "high",
     lambda m: [("incomplete_exam_packet_count", m["sig"].get("incomplete_exam_packet_count", 0))] if m["sig"].get("incomplete_exam_packet_count", 0) > 0 else None,
     "Exam packets are reported incomplete. Protect fairness before the sitting."),
    ("marks_data_integrity", "high",
     lambda m: [("marks_import_row_mismatch_count", m["sig"].get("marks_import_row_mismatch_count", 0))] if m["sig"].get("marks_import_row_mismatch_count", 0) > 0 else None,
     "Imported marks do not match their source rows. Hold publication until reconciled."),
    ("classroom_occupancy_or_comfort_deviation", "medium",
     lambda m: [("fan_fault_reports", m["sig"].get("fan_fault_reports", 0)), ("room_occupancy_dev_pct", m["cam"].get("room", 0))] if m["sig"].get("fan_fault_reports", 0) > 0 or m["cam"].get("room", 0) <= -80 else None,
     "A room's occupancy or comfort signal is off. A count alone cannot say why."),
    ("vehicle_gate_flow_interruption", "high",
     lambda m: [("gate_vehicle_flow_interruption", m["sig"].get("gate_vehicle_flow_interruption", 0))] if m["sig"].get("gate_vehicle_flow_interruption", 0) > 0 else None,
     "Vehicle flow at the gate was interrupted. Review safety before the next peak."),
    ("staff_retention_signal", "medium",
     lambda m: [("new_staff_notice_count", m["sig"].get("new_staff_notice_count", 0))] if m["sig"].get("new_staff_notice_count", 0) > 0 else None,
     "A staff notice was recorded. Plan handover and cover."),
    ("fee_transparency_query_spike", "medium",
     lambda m: [("fee_head_queries", m["sig"].get("fee_head_queries", 0)), ("queries_and_complaints_count", m["queries"])] if m["sig"].get("fee_head_queries", 0) >= 15 or m["queries"] >= 30 else None,
     "Parents are asking about fee heads more than usual."),
    ("heat_utility_pressure", "medium",
     lambda m: [("heat_pressure_index", m["heat"]), ("attendance_rate", m["att"])] if m["heat"] >= 1.3 and m["att"] < 0.9 else None,
     "Heat and utility pressure coincide with lower attendance."),
    ("electrical_system_interruption", "high",
     lambda m: [("electrical_trip_count", m["sig"].get("electrical_trip_count", 0))] if m["sig"].get("electrical_trip_count", 0) > 0 else None,
     "A circuit tripped. Keep the area closed until it is checked by a qualified person."),
    ("supplier_price_variance", "medium",
     lambda m: [("fuel_invoice_variance_pct", m["sig"].get("fuel_invoice_variance_pct", 0))] if m["sig"].get("fuel_invoice_variance_pct", 0) >= 5 else None,
     "A supplier invoice is higher than its written quote."),
    ("water_service_failure", "high",
     lambda m: [("water_motor_fault_count", m["sig"].get("water_motor_fault_count", 0))] if m["sig"].get("water_motor_fault_count", 0) > 0 else None,
     "The water service has failed. Check drinking-water safety before use."),
]
SCORE = {"low": 0.7, "medium": 0.75, "high": 0.9}


class Detector:
    def __init__(self):
        self.hist = {}          # weekday -> recent attendance rates
        self.n = 0

    def attendance_z(self, att, weekday):
        h = self.hist.setdefault(weekday, [])
        z = 0.0
        if len(h) >= 4:
            med = float(np.median(h)); mad = float(np.median(np.abs(np.array(h) - med))) or 0.008
            z = 0.6745 * (att - med) / mad
        h.append(att)
        del h[:-12]
        return z

    def review(self, date, minute_of, metrics):
        """metrics -> list of alerts for the day. minute_of: {signal name: minute} gives the UI somewhere to jump."""
        out = []
        for code, sev, test, text in RULES:
            ev = test(metrics)
            if ev:
                self.n += 1
                minute = next((minute_of[f] for f, _ in ev if f in minute_of), minute_of.get("_default", 540))
                out.append({"alert_id": f"ALERT-{self.n:03d}", "date": date, "rule_code": code, "severity": sev,
                            "score": round(SCORE[sev] + 0.02 * len(ev), 2), "text": text, "minute": int(minute),
                            "evidence": [{"field": f, "value": (round(v, 3) if isinstance(v, float) else v)} for f, v in ev],
                            "status": "requires_human_review"})
        return out
