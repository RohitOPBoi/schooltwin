"""Natural Language Scenario Creation for SchoolTwin.

Connects to local Ollama (if available at http://127.0.0.1:11434) to parse natural-language
prompts into the canonical scenario schema, with a robust rule-based fallback when
Ollama is offline or not installed.

Requires user preview and confirmation before execution.
Never executes generated code or arbitrary commands.
"""
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .schema import EVENT_CATALOG, POLICY_DEFINITIONS, ScenarioConfig, validate_date, validate_scenario
from .story import Story

OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "llama3.2"


def is_ollama_available() -> bool:

    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def day_to_date(day_num: int, story: Optional[Story] = None) -> str:

    st = story or Story()
    idx = max(0, min(day_num, len(st.dates) - 1))
    return st.dates[idx]


from .extension_calendar import ExtensionCalendar


def parse_with_rules(
    text: str,
    story: Optional[Story] = None,
    start_day: int = 151,
    duration_days: int = 30,
    reopening_date: str = "2026-07-01",
    end_day: Optional[int] = None,
) -> Dict[str, Any]:

    st = story or Story()
    cal = ExtensionCalendar(st, reopening_date=reopening_date)
    text_lower = text.lower()
    events: List[Dict[str, Any]] = []
    policy_overrides: Dict[str, Any] = {}
    ambiguities: List[str] = []

    if end_day is not None:
        duration_days = max(1, end_day - start_day + 1)
    end_day = start_day + duration_days - 1


    iso_date_matches = list(re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", text))

    # Month name to number mapping
    month_names = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }

    # Relative day phrases: "on the third day", "on the first day", "on day 3"
    relative_map = {
        "first": 0, "1st": 0,
        "second": 1, "2nd": 1,
        "third": 2, "3rd": 2,
        "fourth": 3, "4th": 3,
        "fifth": 4, "5th": 4,
        "sixth": 5, "6th": 5,
        "seventh": 6, "7th": 6,
    }

    # Helper to resolve day or date near a text position
    def resolve_date_for_pos(pos: int, default_offset: int = 2) -> Tuple[int, str]:
        # Check if there is an explicit ISO date near pos
        best_iso = None
        best_iso_dist = 100000
        for im in iso_date_matches:
            dist = abs(pos - im.start())
            if dist < best_iso_dist:
                best_iso_dist = dist
                best_iso = im.group(1)
        if best_iso and best_iso_dist < 40:
            d_idx = cal.day_for_date(best_iso)
            return d_idx, best_iso

        # Check for natural month + day phrases: e.g. "June 3", "July 1", "3rd of June", "1st July"
        m_pat = r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b"
        for mm in re.finditer(m_pat, text_lower):
            m_month = month_names.get(mm.group(1), 6)
            m_day = int(mm.group(2))
            cand_iso = f"2026-{m_month:02d}-{m_day:02d}"
            try:
                d_idx = cal.day_for_date(cand_iso)
                if abs(pos - mm.start()) < 50:
                    return d_idx, cand_iso
            except Exception:
                pass

        m_pat_rev = r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b"
        for mm in re.finditer(m_pat_rev, text_lower):
            m_day = int(mm.group(1))
            m_month = month_names.get(mm.group(2), 6)
            cand_iso = f"2026-{m_month:02d}-{m_day:02d}"
            try:
                d_idx = cal.day_for_date(cand_iso)
                if abs(pos - mm.start()) < 50:
                    return d_idx, cand_iso
            except Exception:
                pass

        # Check for term milestone phrases
        if re.search(r"\b(reopening\s+day|on\s+reopening|school\s+reopens?|monsoon\s+resumption)\b", text_lower):
            reopen_day = cal.day_for_date(reopening_date)
            return reopen_day, reopening_date

        if re.search(r"\b(first\s+week\s+of\s+july|early\s+july)\b", text_lower):
            target_iso = "2026-07-05"
            return cal.day_for_date(target_iso), target_iso

        if re.search(r"\b(summer\s+break|summer\s+maintenance|early\s+june)\b", text_lower):
            target_iso = "2026-06-03"
            return cal.day_for_date(target_iso), target_iso

        # Check for relative phrase: "on the third day"
        rel_m = re.search(r"on\s+the\s+(first|second|third|fourth|fifth|sixth|seventh|1st|2nd|3rd|4th|5th)\s+day", text_lower)
        if rel_m:
            w = rel_m.group(1)
            rel_off = relative_map.get(w, 0)
            target_day = start_day + rel_off
            return target_day, cal.date_for_day(target_day)

        # Check for "day X"
        day_m = re.search(r"\bday\s+(\d+)\b", text_lower)
        if day_m:
            raw_d = int(day_m.group(1))
            return raw_d, cal.date_for_day(raw_d)

        # Default to start_day + default_offset
        def_d = start_day + default_offset
        return def_d, cal.date_for_day(def_d)


    fight_match = re.search(r"\b(fight|altercation|brawl|physical\s+conflict)\b", text_lower)
    if fight_match:
        # If in summer break without explicit date, default to reopening day where students are present
        def_fight_off = (cal.day_for_date(reopening_date) - start_day) if (start_day == 151 and end_day >= 181) else 2
        d_num, dt = resolve_date_for_pos(fight_match.start(), def_fight_off)
        sids = ["STU-0012", "STU-0015", "STU-0021"]
        events.append({
            "type": "serious_student_fight",
            "date": dt,
            "severity": "high",
            "params": {
                "student_ids": sids,
                "location": "playground",
            },
            "student_ids": sids,
            "location": "playground",
        })
        ambiguities.append(f"Physical altercation placed on {dt} (Day {d_num}) involving sample students STU-0012, STU-0015, STU-0021 in playground.")


    bus_match = re.search(r"\b(bus\b(?:[^.!?\n]*?)(?:breaks\s+down|breakdown|delayed|failure)|broken\s+down\s+bus|transport\s+delay)\b", text_lower)
    if bus_match:
        def_bus_off = (cal.day_for_date(reopening_date) - start_day) if (start_day == 151 and end_day >= 181) else 4
        d_num, dt = resolve_date_for_pos(bus_match.start(), def_bus_off)
        route_num = 3
        rm = re.search(r"route\s+(\d+)", text_lower)
        if rm:
            route_num = int(rm.group(1))
        events.append({
            "type": "bus_breakdown",
            "date": dt,
            "severity": "medium",
            "params": {
                "route_number": route_num,
                "delay_minutes": 20,
                "location": "bus_bay",
            },
            "route_number": route_num,
            "delay_minutes": 20,
            "location": "bus_bay",
        })
        ambiguities.append(f"Bus breakdown placed on {dt} (Day {d_num}) for Route {route_num} with estimated 20-min delay.")


    cooler_match = re.search(r"\b(water\s+cooler|cooler\s+breakdown|drinking\s+water|water\s+dispenser)\b", text_lower)
    if cooler_match:
        d_num, dt = resolve_date_for_pos(cooler_match.start(), 2)
        loc = "corridor_1"
        if "canteen" in text_lower:
            loc = "canteen"
        elif "ground" in text_lower:
            loc = "north_ground"
        events.append({
            "type": "water_cooler_breakdown",
            "date": dt,
            "severity": "medium",
            "params": {
                "location": loc,
            },
            "location": loc,
        })
        ambiguities.append(f"Water cooler breakdown placed on {dt} (Day {d_num}) in {loc}.")


    strike_match = re.search(r"\b(collective\s+strike|staff\s+strike|teachers?\s+strike|faculty\s+strike)\b", text_lower)
    if strike_match:
        d_num, dt = resolve_date_for_pos(strike_match.start(), 3)
        events.append({
            "type": "collective_strike",
            "date": dt,
            "severity": "high",
            "params": {
                "location": "north_ground",
            },
            "location": "north_ground",
        })
        ambiguities.append(f"Staff collective strike placed on {dt} (Day {d_num}) at north_ground.")


    biz_match = re.search(r"\b(prohibited\s+business|unauthorized\s+sale|policy\s+violation|contraband|snack\s+resale)\b", text_lower)
    if biz_match:
        d_num, dt = resolve_date_for_pos(biz_match.start(), 6)
        events.append({
            "type": "suspected_prohibited_business",
            "date": dt,
            "severity": "medium",
            "params": {
                "student_ids": ["STU-0044"],
                "location": "admin_lobby",
                "investigation_status": "under_review",
            },
            "student_ids": ["STU-0044"],
            "location": "admin_lobby",
            "investigation_status": "under_review",
        })
        ambiguities.append(f"Allegation under review placed on {dt} (Day {d_num}) regarding student STU-0044.")


    resig_match = re.search(r"\b(teacher\s+resigns?|resignation|teacher\s+leaves?|faculty\s+resignation)\b", text_lower)
    if resig_match:
        d_num, dt = resolve_date_for_pos(resig_match.start(), 8)
        events.append({
            "type": "teacher_resignation",
            "date": dt,
            "severity": "medium",
            "params": {
                "teacher_name": "Ritu Kapoor",
                "location": "staffroom",
            },
            "teacher_name": "Ritu Kapoor",
            "location": "staffroom",
        })
        ambiguities.append(f"Teacher resignation notice placed on {dt} (Day {d_num}) for Ritu Kapoor.")


    fee_match = re.search(r"\b(fees?\s*(?:increase|hike|rise|revision|delta)|(?:increase|raise|hike|revise)\s*(?:the\s*)?fees?|\d+%\s*fees?)\b", text_lower)
    if fee_match:
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text_lower)
        pct = float(pct_match.group(1)) if pct_match else 10.0
        d_num, dt = resolve_date_for_pos(fee_match.start(), 0)
        events.append({
            "type": "school_fee_increase",
            "date": dt,
            "severity": "medium",
            "params": {
                "fee_category": "tuition",
                "delta_pct": pct,
            },
            "fee_category": "tuition",
            "delta_pct": pct,
        })
        policy_overrides["tuition_fee_delta_pct"] = pct
        policy_overrides["fee_change_approved"] = True
        ambiguities.append(f"Fee increase of +{pct}% scheduled on {dt} (Day {d_num}); policy lever updated and governance approval enabled.")


    hire_match = re.search(r"\b(hire|recruit|appoint|extra\s+teacher|additional\s+teacher)\b", text_lower)
    if hire_match:
        count_m = re.search(r"(\d+)\s*(?:extra|additional|new)?\s*teachers?", text_lower)
        cnt = int(count_m.group(1)) if count_m else 1
        d_num, dt = resolve_date_for_pos(hire_match.start(), 0)
        events.append({
            "type": "additional_teacher_hired",
            "date": dt,
            "severity": "low",
            "params": {
                "teacher_name": "Pooja Sharma",
                "subject_or_role": "Social Science",
            },
            "teacher_name": "Pooja Sharma",
            "subject_or_role": "Social Science",
        })
        policy_overrides["additional_teachers"] = cnt
        ambiguities.append(f"Additional teacher recruitment ({cnt} faculty) applied from {dt} (Day {d_num}).")


    weather_match = re.search(r"\b(weather\s+dip|heat\s+wave|extreme\s+heat|heavy\s+rain|monsoon\s+storm|weather\s+disruption)\b", text_lower)
    if weather_match:
        d_num, dt = resolve_date_for_pos(weather_match.start(), 3)
        events.append({
            "type": "weather_attendance_dip",
            "date": dt,
            "severity": "medium",
            "params": {
                "attendance_dip_pct": 15,
            },
        })
        ambiguities.append(f"Weather attendance dip event scheduled on {dt} (Day {d_num}).")


    fan_match = re.search(r"\b(fan\s+failure|broken\s+fan|classroom\s+fan|fan\s+stops?)\b", text_lower)
    if fan_match:
        d_num, dt = resolve_date_for_pos(fan_match.start(), 2)
        events.append({
            "type": "classroom_fan_failure",
            "date": dt,
            "severity": "low",
            "params": {
                "location": "C8B",
            },
            "location": "C8B",
        })
        ambiguities.append(f"Classroom fan failure placed on {dt} (Day {d_num}) in C8B.")


    lab_match = re.search(r"\b(circuit\s+trip|lab\s+power\s+outage|computer\s+lab\s+trip|lab\s+closed)\b", text_lower)
    if lab_match:
        d_num, dt = resolve_date_for_pos(lab_match.start(), 3)
        events.append({
            "type": "computer_lab_circuit_trip",
            "date": dt,
            "severity": "medium",
            "params": {
                "location": "comp_lab_1",
            },
            "location": "comp_lab_1",
        })
        ambiguities.append(f"Computer lab circuit trip scheduled on {dt} (Day {d_num}) in comp_lab_1.")


    maint_match = re.search(
        r"(?:(?:summer\s+)?maint(?:enance)?\s+budget\s*(?:of\s*)?[₹rRs\.]*\s*(\d+(?:,\d+)*)|(?:[₹rRs\.]*\s*(\d+(?:,\d+)*)\s*(?:inr|rs)?\s*(?:for\s*)?(?:summer\s+)?maint(?:enance)?\s+budget))",
        text_lower
    )
    if maint_match:
        raw_str = maint_match.group(1) or maint_match.group(2)
        raw_val = int(raw_str.replace(",", ""))
        policy_overrides["summer_maintenance_budget_inr"] = raw_val
        ambiguities.append(f"Summer maintenance budget updated to ₹{raw_val:,}.")


    backup_bus_match = re.search(
        r"(?:(\d+)\s*(?:backup|standby)\s*buses?|bus\s+backup\s+capacity\s*(?:to\s*)?(\d+)|backup\s+capacity\s*(?:to\s*)?(\d+))",
        text_lower
    )
    if backup_bus_match:
        b_cnt = int(backup_bus_match.group(1) or backup_bus_match.group(2) or backup_bus_match.group(3))
        policy_overrides["bus_backup_capacity"] = min(b_cnt, 4)
        ambiguities.append(f"Standby backup bus capacity set to {min(b_cnt, 4)} buses.")


    support_match = re.search(r"\battendance\s+support\s*(?:budget)?\s*(?:of\s*)?[₹rRs\.]*\s*(\d+(?:,\d+)*)\b", text_lower)
    if support_match:
        s_val = int(support_match.group(1).replace(",", ""))
        policy_overrides["attendance_support_budget_inr_per_month"] = s_val
        ambiguities.append(f"Monthly attendance support budget set to ₹{s_val:,}.")

    # Name derived from prompt
    clean_name = re.sub(r"[^A-Za-z0-9]+", "_", text[:35]).strip("_") or "nl_scenario"

    return {
        "name": clean_name,
        "description": text.strip(),
        "mode": "generate",
        "events": events,
        "policy_overrides": policy_overrides,
        "ambiguities": ambiguities,
        "parser_used": "rule_based_fallback",
    }


def parse_with_ollama(
    text: str,
    model: str = DEFAULT_MODEL,
    start_day: int = 151,
    duration_days: int = 30,
    reopening_date: str = "2026-07-01",
    end_day: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Calls local Ollama to translate prompt into structured JSON according to the canonical schema."""
    cal = ExtensionCalendar(reopening_date=reopening_date)
    if end_day is None:
        end_day = start_day + duration_days - 1
    start_date = cal.date_for_day(start_day)
    end_date = cal.date_for_day(end_day)

    system_prompt = (
        "You are an assistant for SchoolTwin, a synthetic school simulation. "
        "Your task is to convert the user's natural language scenario prompt into valid JSON. "
        "Return ONLY a single valid JSON object with keys: name (string), description (string), "
        f"events (list of objects with type, date [YYYY-MM-DD between {start_date} and {end_date}], "
        "severity ['low','medium','high'], and params), policy_overrides (object with keys like "
        "additional_teachers, tuition_fee_delta_pct, fee_change_approved, bus_backup_capacity, summer_maintenance_budget_inr). "
        "Recognized event types: serious_student_fight, suspected_prohibited_business, teacher_resignation, "
        "bus_breakdown, school_fee_increase, additional_teacher_hired, weather_attendance_dip, "
        "water_cooler_breakdown, collective_strike, classroom_fan_failure, computer_lab_circuit_trip. "
        "No prose, no explanation, only raw JSON."
    )

    payload = {
        "model": model,
        "prompt": f"System: {system_prompt}\nUser request: {text}\nJSON Output:",
        "stream": False,
        "format": "json",
    }
    try:
        req = urllib.request.Request(
            OLLAMA_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_response = data.get("response", "{}")
            parsed = json.loads(raw_response)
            parsed["parser_used"] = f"ollama_{model}"
            return parsed, None
    except Exception as e:
        return None, str(e)


def parse_scenario_prompt(
    text: str,
    prefer_ollama: bool = True,
    start_day: int = 151,
    duration_days: int = 30,
    reopening_date: str = "2026-07-01",
    end_day: Optional[int] = None,
) -> Dict[str, Any]:
    """Primary entry point: attempts Ollama parsing if available, with transparent rule-based fallback."""
    if end_day is not None:
        duration_days = max(1, end_day - start_day + 1)
    if prefer_ollama and is_ollama_available():
        res, err = parse_with_ollama(
            text,
            start_day=start_day,
            duration_days=duration_days,
            reopening_date=reopening_date,
            end_day=end_day,
        )
        if res and isinstance(res, dict):
            res["start_day"] = start_day
            res["duration_days"] = duration_days
            res["end_day"] = start_day + duration_days - 1
            res["branch"] = {
                "start_day": start_day,
                "duration_days": duration_days,
                "reopening_date": reopening_date,
            }
            # Validate against canonical schema
            is_valid, validation_errors = validate_scenario(res)
            if is_valid:
                res["validation_status"] = "valid"
                res["validation_errors"] = []
                return res
            else:
                # If Ollama JSON had validation issues, augment with fallback
                fallback = parse_with_rules(text, start_day=start_day, duration_days=duration_days, reopening_date=reopening_date, end_day=end_day)
                fallback["start_day"] = start_day
                fallback["duration_days"] = duration_days
                fallback["end_day"] = start_day + duration_days - 1
                fallback["ollama_attempt_error"] = f"Ollama returned invalid schema: {validation_errors}"
                return fallback

    # Rule-based fallback
    result = parse_with_rules(text, start_day=start_day, duration_days=duration_days, reopening_date=reopening_date, end_day=end_day)
    result["start_day"] = start_day
    result["duration_days"] = duration_days
    result["end_day"] = start_day + duration_days - 1
    result["branch"] = {
        "start_day": start_day,
        "duration_days": duration_days,
        "reopening_date": reopening_date,
    }
    is_valid, validation_errors = validate_scenario(result)
    result["validation_status"] = "valid" if is_valid else "rejected"
    result["validation_errors"] = validation_errors
    if not is_valid:
        result["error"] = "; ".join(validation_errors)
    return result
