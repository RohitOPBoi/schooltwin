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
    op = [d for d in days if d.get("open")]
    ref = {d["date"]: d for d in story.days if isinstance(d, dict)}
    out = {"days": len(days), "open_days": len(op), "mode": eng.ov.get("mode", "generate")}
    # fidelity
    op_ref = [
        d for d in op
        if d.get("date") in ref
        and isinstance(ref[d["date"]].get("student_enrollment"), dict)
        and "attendance_rate" in ref[d["date"]]["student_enrollment"]
        and d.get("attendance_rate") is not None
    ]
    if op_ref:
        att_err = [abs(d["attendance_rate"] - ref[d["date"]]["student_enrollment"]["attendance_rate"]) for d in op_ref]
        late_err = [abs(d.get("late", 0) - ref[d["date"]]["student_enrollment"].get("late_arrivals", 0)) for d in op_ref]
        out["attendance_mae_pts"] = round(100 * st.mean(att_err), 2) if att_err else None
        out["late_mae"] = round(st.mean(late_err), 1) if late_err else None
    else:
        out["attendance_mae_pts"] = None
        out["late_mae"] = None

    last_day = days[-1] if days else None
    last_cash = last_day.get("finance", {}).get("cash") if last_day else None
    out["finance_final_cash"] = last_cash

    ref_last = ref.get(last_day["date"]) if last_day else None
    ref_cash = ref_last.get("finance", {}).get("closing_cash_balance_inr") if ref_last else None
    if ref_cash is None:
        for bd in reversed(story.days):
            if isinstance(bd, dict) and "closing_cash_balance_inr" in bd.get("finance", {}):
                ref_cash = bd["finance"]["closing_cash_balance_inr"]
                break
    if last_cash is not None and ref_cash:
        out["closing_cash_diff_pct"] = round(100 * (last_cash - ref_cash) / ref_cash, 2)
    else:
        out["closing_cash_diff_pct"] = None

    cams = {}
    for d in op_ref:
        cctv_stream = ref[d["date"]].get("cctv_synthetic_event_stream", {}).get("records", [])
        for r in d.get("cctv", []):
            story_vals = [
                x["observed_count"] for x in cctv_stream
                if x.get("camera_id") == r.get("camera_id")
                and int(x.get("timestamp", "T00:00")[11:13]) * 60 + int(x.get("timestamp", "T00:00")[14:16]) == r.get("minute")
            ]
            if story_vals:
                cams.setdefault(r["camera_id"], []).append((r["observed_count"], story_vals[0]))
    out["camera_fidelity"] = [
        {"camera": c, "engine_mean": round(st.mean(x for x, _ in v), 1), "story_mean": round(st.mean(y for _, y in v), 1),
         "diff_pct": round(100 * (st.mean(x for x, _ in v) - st.mean(y for _, y in v)) / st.mean(y for _, y in v)) if st.mean(y for _, y in v) else 0}
        for c, v in sorted(cams.items())
    ]

    tot = sum(d.get("feedback", {}).get("pos", 0) + d.get("feedback", {}).get("neu", 0) + d.get("feedback", {}).get("neg", 0) for d in op) or 1
    out["negative_feedback_share"] = round(sum(d.get("feedback", {}).get("neg", 0) for d in op) / tot, 3)

    fb_op = [d for d in op_ref if ref[d["date"]].get("student_feedback", {}).get("sample_responses")]
    tot_samples = sum(ref[d["date"]]["student_feedback"]["sample_responses"] for d in fb_op)
    if tot_samples > 0:
        out["story_negative_feedback_share"] = round(sum(ref[d["date"]]["student_feedback"].get("negative_count", 0) for d in fb_op) / tot_samples, 3)
    else:
        out["story_negative_feedback_share"] = None

    mood_lows = [d["mood_low_share"] for d in op if d.get("mood_low_share") is not None]
    out["mood_low_share_mean"] = round(st.mean(mood_lows), 3) if mood_lows else None

    # detection
    mine, my_false = _recall(story, eng.alerts)
    theirs, their_false = _recall(story, [{"date": a["date"], "rule_code": a["rule_code"]} for a in story.alerts])
    out["detection"] = {
        "engine": {"events": mine, "flagged": sum(r["flagged"] for r in mine), "right_rule": sum(r["right_rule"] for r in mine),
                   "total": len(mine), "false_alarm_days": len(my_false), "alerts": len(eng.alerts)},
        "story_detector": {"flagged": sum(r["flagged"] for r in theirs), "total": len(theirs),
                           "false_alarm_days": len(their_false), "alerts": len(story.alerts)}
    }
    return out
