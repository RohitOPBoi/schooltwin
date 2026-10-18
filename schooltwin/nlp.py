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
    """Checks whether local Ollama service is reachable."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def day_to_date(day_num: int, story: Optional[Story] = None) -> str:
    """Maps a 1-indexed or 0-indexed day number to an ISO calendar date from the story timeline."""
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
    """Rule-based extractor that parses natural language scenario text into structured events and policies."""
    st = story or Story()
    cal = ExtensionCalendar(st, reopening_date=reopening_date)
    text_lower = text.lower()
    events: List[Dict[str, Any]] = []
    policy_overrides: Dict[str, Any] = {}
    ambiguities: List[str] = []

    if end_day is not None:
        duration_days = max(1, end_day - start_day + 1)
    end_day = start_day + duration_days - 1

    # 1. Look for explicit ISO dates first: "2026-04-10"
    iso_date_matches = list(re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", text))

    # Look for relative day phrases: "on the third day", "on the first day", "on day 3"
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
            # If raw_d is small (e.g. Day 5) but start_day is 151, user might have explicitly specified Day 5
            return raw_d, cal.date_for_day(raw_d)

        # Default to start_day + default_offset
        def_d = start_day + default_offset
        return def_d, cal.date_for_day(def_d)

    # 2. Check for Serious Fight
    fight_match = re.search(r"\b(fight|altercation|brawl)\b", text_lower)
    if fight_match:
        d_num, dt = resolve_date_for_pos(fight_match.start(), 2)
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

    # 3. Check for Bus Breakdown / Transport delay
    bus_match = re.search(r"\b(bus\b(?:[^.!?\n]*?)(?:breaks\s+down|breakdown|delayed|failure)|broken\s+down\s+bus)\b", text_lower)
    if bus_match:
        d_num, dt = resolve_date_for_pos(bus_match.start(), 4)
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

    # 4. Check for Water Cooler Breakdown (WP1 & WP2)
    cooler_match = re.search(r"\b(water\s+cooler|cooler\s+breakdown|drinking\s+water|water\s+dispenser)\b", text_lower)
    if cooler_match:
        d_num, dt = resolve_date_for_pos(cooler_match.start(), 1)
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

    # 5. Check for Collective Strike (WP1 & WP2)
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

    # 6. Check for Prohibited Business / Policy Violation
    biz_match = re.search(r"\b(prohibited\s+business|unauthorized\s+sale|policy\s+violation|contraband)\b", text_lower)
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

    # 7. Check for Teacher Resignation
    resig_match = re.search(r"\b(teacher\s+resigns?|resignation|teacher\s+leaves?)\b", text_lower)
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

    # 6. Check for Fee Revision / Fee Increase
    fee_match = re.search(r"\b(fees?\s*(?:increase|hike|rise|revision|delta)|(?:increase|raise|hike|revise)\s*(?:the\s*)?fees?|\d+%\s*fees?)\b", text_lower)
    if fee_match:
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text_lower)
        pct = float(pct_match.group(1)) if pct_match else 10.0
        d_num, dt = resolve_date_for_pos(fee_match.start(), 90)
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

    # 7. Check for Additional Teacher Hired
    hire_match = re.search(r"\b(hire|recruit|appoint|extra\s+teacher|additional\s+teacher)\b", text_lower)
    if hire_match:
        count_m = re.search(r"(\d+)\s*(?:extra|additional|new)?\s*teachers?", text_lower)
        cnt = int(count_m.group(1)) if count_m else 1
        d_num = find_day_for_pos(hire_match.start(), 60)
        dt = day_to_date(d_num, st)
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


def parse_with_ollama(text: str, model: str = DEFAULT_MODEL) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Calls local Ollama to translate prompt into structured JSON according to the canonical schema."""
    system_prompt = (
        "You are an assistant for SchoolTwin, a synthetic school simulation. "
        "Your task is to convert the user's natural language scenario prompt into valid JSON. "
        "Return ONLY a single valid JSON object with keys: name (string), description (string), "
        "events (list of objects with type, date [YYYY-MM-DD between 2026-01-01 and 2026-05-31], "
        "severity ['low','medium','high'], and params), policy_overrides (object with keys like "
        "additional_teachers, tuition_fee_delta_pct, fee_change_approved). "
        "Recognized event types: serious_student_fight, suspected_prohibited_business, teacher_resignation, "
        "bus_breakdown, school_fee_increase, additional_teacher_hired, weather_attendance_dip. "
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
        res, err = parse_with_ollama(text)
        if res and isinstance(res, dict):
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
                fallback["ollama_attempt_error"] = f"Ollama returned invalid schema: {validation_errors}"
                return fallback

    # Rule-based fallback
    result = parse_with_rules(text, start_day=start_day, duration_days=duration_days, reopening_date=reopening_date, end_day=end_day)
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
