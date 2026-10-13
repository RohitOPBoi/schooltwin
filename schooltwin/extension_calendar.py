"""Extension Calendar Provider for SchoolTwin (Days 151+ and beyond).

Implements the canonical calendar provider interface for the simulation engine:
- info(i): day metadata (date, type, open status, weekday, source)
- weekday(i): 0=Monday..6=Sunday
- by_date(iso): daily operational signals, weather, heat, finance
- Delegates Days 0..150 to saraswati_heights_story.json.
- Synthesizes Days 151..364 according to transparent, assumed CBSE calendar policies.
- Every value derived from the extension carries source: 'assumed'.
"""
import copy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .config import ROOT

EXTENSION_CONFIG_PATH = ROOT / "config" / "extension_calendar.yaml"
BASE_DATE = date(2026, 1, 1)


class ExtensionCalendar:
    """Manages continuous timeline extension from Day 151 through Day 365+."""

    def __init__(
        self,
        story: Optional[Any] = None,
        reopening_date: str = "2026-07-01",
        config_path: Optional[Path] = None,
    ):
        if story is None:
            try:
                from .story import Story
                self.story = Story()
            except Exception:
                self.story = None
        else:
            self.story = story
        self.reopening_date = reopening_date
        self.cfg = self._load_config(config_path or EXTENSION_CONFIG_PATH)
        self._cache_info: Dict[int, Dict[str, Any]] = {}
        self._cache_rows: Dict[str, Dict[str, Any]] = {}

    def _load_config(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                pass
        return {
            "reopening_date": self.reopening_date,
            "environment": {"weather_disruption_index": 0.1, "heat_pressure_index": 1.0},
        }

    def date_for_day(self, day_idx: int) -> str:
        """Returns ISO date string for 0-indexed day."""
        return (BASE_DATE + timedelta(days=int(day_idx))).isoformat()

    def day_for_date(self, iso_str: str) -> int:
        """Returns 0-indexed day for ISO date string."""
        y, m, d = map(int, iso_str.split("-"))
        dt = date(y, m, d)
        return (dt - BASE_DATE).days

    def weekday(self, day_idx: int) -> int:
        """Returns 0=Monday..6=Sunday."""
        if self.story and day_idx <= 150:
            return self.story.weekday(day_idx)
        dt = BASE_DATE + timedelta(days=int(day_idx))
        return dt.weekday()

    def info(self, day_idx: int) -> Dict[str, Any]:
        """Returns standardized day information dictionary."""
        day_idx = int(day_idx)
        if day_idx in self._cache_info:
            return self._cache_info[day_idx]

        # Days 0..150: delegate to frozen story baseline
        if self.story and day_idx <= 150:
            base_info = dict(self.story.info(day_idx))
            base_info["source"] = "story"
            self._cache_info[day_idx] = base_info
            return base_info

        # Days 151+: synthesize with transparent assumed rules
        dt = BASE_DATE + timedelta(days=day_idx)
        iso = dt.isoformat()
        dow = dt.strftime("%A")
        wday = dt.weekday()
        dom = dt.day

        # Check summer break vs reopening
        if iso < self.reopening_date:
            if wday == 6:
                day_type = "weekly_closure"
                is_open = False
            else:
                day_type = "summer_break_staff_only"
                is_open = False
        else:
            # Post-reopening term rules
            planned_closures = self.cfg.get("planned_closures", {})
            if iso in planned_closures:
                day_type = "planned_closure"
                is_open = False
            elif wday == 6:  # Sunday
                day_type = "weekly_closure"
                is_open = False
            elif wday == 5:  # Saturday (alternate)
                sat_idx = (dom - 1) // 7 + 1
                if sat_idx in (1, 3, 5):
                    day_type = "limited_school_day"
                    is_open = True
                else:
                    day_type = "weekly_closure"
                    is_open = False
            else:  # Monday to Friday
                day_type = "instructional_day"
                is_open = True

        out = {
            "i": day_idx,
            "date": iso,
            "dow": dow,
            "type": day_type,
            "open": is_open,
            "source": "assumed",
        }
        self._cache_info[day_idx] = out
        return out

    def by_date(self, iso_str: str) -> Dict[str, Any]:
        """Returns the full day row containing operational signals and baseline finance."""
        if iso_str in self._cache_rows:
            return self._cache_rows[iso_str]

        day_idx = self.day_for_date(iso_str)
        if self.story and day_idx <= 150 and iso_str in self.story.by_date:
            row = dict(self.story.by_date[iso_str])
            row["source"] = "story"
            self._cache_rows[iso_str] = row
            return row

        # Extension row (Days 151+)
        info = self.info(day_idx)

        # Baseline neutral end-state environment
        weather_idx = float(
            self.cfg.get("environment", {}).get("weather_disruption_index", 0.1)
        )
        heat_idx = float(self.cfg.get("environment", {}).get("heat_pressure_index", 1.0))

        # Extrapolate May's finance pattern (assumed)
        may_fin = {}
        if self.story and len(self.story.days) > 150:
            may_fin = copy.deepcopy(self.story.days[150].get("finance", {}))
        elif self.story and self.story.days:
            may_fin = copy.deepcopy(self.story.days[-1].get("finance", {}))

        row = {
            "date": iso_str,
            "day_number_in_run": day_idx + 1,
            "day_type": info["type"],
            "school_open_to_students": info["open"],
            "operational_signals": {
                "signals": {
                    "weather_disruption_index": weather_idx,
                    "heat_pressure_index": heat_idx,
                }
            },
            "finance": may_fin,
            "source": "assumed",
            "environment_assumed": True,
        }
        self._cache_rows[iso_str] = row
        return row

    def compute_timeline(
        self,
        start_day: int,
        duration_days: int,
    ) -> Dict[str, Any]:
        """Calculates exact timeline metrics, school days vs calendar days, and assumptions."""
        start_day = int(start_day)
        duration_days = max(1, min(int(duration_days), 365))
        end_day = start_day + duration_days - 1

        start_date = self.date_for_day(start_day)
        end_date = self.date_for_day(end_day)

        school_days = 0
        closed_days = 0
        summer_days = 0

        for d in range(start_day, end_day + 1):
            inf = self.info(d)
            if inf["open"]:
                school_days += 1
            else:
                closed_days += 1
            if inf["type"] == "summer_break_staff_only":
                summer_days += 1

        assumptions: List[Dict[str, str]] = []
        if end_day > 150:
            assumptions.append({
                "id": "A1-REOPENING",
                "text": f"Summer break continues until {self.reopening_date}; school reopens on {self.reopening_date}.",
                "source": "assumed",
            })
            assumptions.append({
                "id": "A2-ENVIRONMENT",
                "text": "Weather and heat disruption indices set to neutral baseline end-state (0.1 / 1.0).",
                "source": "assumed",
            })
            assumptions.append({
                "id": "A3-FINANCE",
                "text": "Fee collection and monthly payroll accrual extrapolate May baseline patterns.",
                "source": "assumed",
            })

        return {
            "start_day": start_day,
            "start_date": start_date,
            "duration_days": duration_days,
            "end_day": end_day,
            "end_date": end_date,
            "calendar_days": duration_days,
            "school_days": school_days,
            "closed_days": closed_days,
            "summer_break_days": summer_days,
            "reopening_date": self.reopening_date,
            "assumptions": assumptions,
        }
