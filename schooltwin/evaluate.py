"""Does the engine reproduce the story, and does the detector find what the story hid?

Two separate questions, kept separate:
  FIDELITY   how closely do the engine's numbers track the story's own daily record?
  DETECTION  of the 18 planted events, how many does the detector flag, and at what cost in false alarms?
The story's own rule-based detector is scored the same way, as the yardstick."""
import statistics as st


def _recall(story, alerts, rule_match=False):
    by_date = {}
    for a in alerts:
        by_date.setdefault(a["date"], set()).add(a["rule_code"])
    story_rules = {}
    for a in story.alerts:
        story_rules.setdefault(a["date"], set()).add(a["rule_code"])
    rows = []
    for e in story.events:
        got = by_date.get(e["date"], set())
        want = story_rules.get(e["date"], set()) - {"classroom_friction_cluster"}
        rows.append({"id": e["event_id"], "date": e["date"], "type": e["type"], "flagged": bool(got),
                     "right_rule": bool(got & want) if want else bool(got)})
    gt_dates = {e["date"] for e in story.events}
    false_days = sorted(d for d in by_date if d not in gt_dates)
    return rows, false_days


def evaluate(eng):
    story, days = eng.story, eng.days
    op = [d for d in days if d["open"]]
    ref = {d["date"]: d for d in story.days}
    out = {"days": len(days), "open_days": len(op), "mode": eng.ov["mode"]}
    # ---- fidelity
    att_err = [abs(d["attendance_rate"] - ref[d["date"]]["student_enrollment"]["attendance_rate"]) for d in op]
    late_err = [abs(d["late"] - ref[d["date"]]["student_enrollment"]["late_arrivals"]) for d in op]
    out["attendance_mae_pts"] = round(100 * st.mean(att_err), 2) if att_err else None
    out["late_mae"] = round(st.mean(late_err), 1) if late_err else None
    out["closing_cash_diff_pct"] = round(100 * (days[-1]["finance"]["cash"] - ref[days[-1]["date"]]["finance"]["closing_cash_balance_inr"])
                                         / ref[days[-1]["date"]]["finance"]["closing_cash_balance_inr"], 2)
    cams = {}
    for d in op:
        for r in d["cctv"]:
            story_vals = [x["observed_count"] for x in ref[d["date"]]["cctv_synthetic_event_stream"]["records"]
                          if x["camera_id"] == r["camera_id"] and int(x["timestamp"][11:13]) * 60 + int(x["timestamp"][14:16]) == r["minute"]]
            if story_vals:
                cams.setdefault(r["camera_id"], []).append((r["observed_count"], story_vals[0]))
    out["camera_fidelity"] = [{"camera": c, "engine_mean": round(st.mean(x for x, _ in v), 1), "story_mean": round(st.mean(y for _, y in v), 1),
                               "diff_pct": round(100 * (st.mean(x for x, _ in v) - st.mean(y for _, y in v)) / st.mean(y for _, y in v)) if st.mean(y for _, y in v) else 0}
                              for c, v in sorted(cams.items())]
    tot = sum(d["feedback"]["pos"] + d["feedback"]["neu"] + d["feedback"]["neg"] for d in op) or 1
    out["negative_feedback_share"] = round(sum(d["feedback"]["neg"] for d in op) / tot, 3)
    out["story_negative_feedback_share"] = round(sum(ref[d["date"]]["student_feedback"]["negative_count"] for d in op) /
                                                 sum(ref[d["date"]]["student_feedback"]["sample_responses"] for d in op), 3)
    out["mood_low_share_mean"] = round(st.mean(d["mood_low_share"] for d in op), 3) if op else None
    # ---- detection
    mine, my_false = _recall(story, eng.alerts)
    theirs, their_false = _recall(story, [{"date": a["date"], "rule_code": a["rule_code"]} for a in story.alerts])
    out["detection"] = {"engine": {"events": mine, "flagged": sum(r["flagged"] for r in mine), "right_rule": sum(r["right_rule"] for r in mine),
                                   "total": len(mine), "false_alarm_days": len(my_false), "alerts": len(eng.alerts)},
                        "story_detector": {"flagged": sum(r["flagged"] for r in theirs), "total": len(theirs),
                                           "false_alarm_days": len(their_false), "alerts": len(story.alerts)}}
    out["finance_final_cash"] = days[-1]["finance"]["cash"]
    return out
