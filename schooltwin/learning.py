"""Transparent Academic and Learning Progression Model for SchoolTwin.

Maintains student-level subject mastery and learning progress driven by
instructional exposure, teacher coverage, configured instructional effectiveness,
assessment difficulty, and deterministic PRNG assessment variance.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

CORE_SUBJECTS = ["Mathematics", "Science", "English", "Social Science"]


@dataclass
class StudentAcademicState:
    student_id: str
    grade: str
    section: str
    subject_mastery: Dict[str, float]
    instructional_periods_attended: int = 0
    instructional_periods_lost: int = 0
    assessment_history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def overall_mastery(self) -> float:
        if not self.subject_mastery:
            return 60.0
        return sum(self.subject_mastery.values()) / len(self.subject_mastery)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "grade": self.grade,
            "section": self.section,
            "subject_mastery": {k: round(v, 2) for k, v in self.subject_mastery.items()},
            "overall_mastery": round(self.overall_mastery, 2),
            "instructional_periods_attended": self.instructional_periods_attended,
            "instructional_periods_lost": self.instructional_periods_lost,
            "assessments_count": len(self.assessment_history),
        }


class LearningModel:
    """Deterministic, bounded learning progression engine."""

    def __init__(self, seed: int = 20261014):
        self.seed = seed
        self.students: Dict[str, StudentAcademicState] = {}
        self.total_uncovered_periods: int = 0
        self.total_lost_instructional_minutes: int = 0

    def initialize_student(self, student_id: str, grade: str, section: str, sid_index: int) -> StudentAcademicState:
        """Initializes a student's prior subject mastery deterministically."""
        rng = np.random.default_rng([self.seed, 42, sid_index])
        masteries = {}
        for idx, subj in enumerate(CORE_SUBJECTS):
            base = float(rng.normal(68.5, 6.5))
            masteries[subj] = float(np.clip(base, 40.0, 95.0))

        state = StudentAcademicState(
            student_id=student_id,
            grade=grade,
            section=section,
            subject_mastery=masteries,
        )
        self.students[student_id] = state
        return state

    def step_day(
        self,
        date_str: str,
        day_index: int,
        is_school_open: bool,
        present_student_ids: set[str],
        uncovered_classes: set[Tuple[str, str]],  # (block_name, room_id)
        scheduled_periods_per_day: int = 6,
        instructional_effectiveness: float = 1.0,
        assessment_difficulty: float = 1.0,
        is_assessment_day: bool = False,
    ) -> Dict[str, Any]:
        """Advances student learning progression by one calendar day."""
        if not is_school_open:
            return self.get_summary()

        effectiveness = max(0.5, min(1.5, instructional_effectiveness))
        difficulty = max(0.5, min(1.5, assessment_difficulty))

        # Count uncovered periods for each room
        uncovered_by_room: Dict[str, int] = {}
        for bname, room in uncovered_classes:
            uncovered_by_room[room] = uncovered_by_room.get(room, 0) + 1
            self.total_uncovered_periods += 1
            self.total_lost_instructional_minutes += 45

        for sid, st in self.students.items():
            is_present = sid in present_student_ids
            # room format typically room_id e.g. C8B
            room_key = f"C{st.grade.replace('Class ', '')}{st.section}"
            uncovered_count = uncovered_by_room.get(room_key, 0)

            if is_present:
                covered_periods = max(0, scheduled_periods_per_day - uncovered_count)
                st.instructional_periods_attended += covered_periods
                st.instructional_periods_lost += uncovered_count

                # Exposure delta: base progression +0.15 pts per fully taught day
                # Uncovered lessons reduce exposure proportionally
                fraction_covered = covered_periods / max(scheduled_periods_per_day, 1)
                # If fully covered: +0.15 * effectiveness
                # If partially covered: reduced
                # If 0 covered: slight -0.03 retention drop
                delta = (0.15 * fraction_covered - 0.03 * (1.0 - fraction_covered)) * effectiveness
            else:
                # Absent student: minor retention decay (-0.03 pts)
                delta = -0.03

            # Update masteries across subjects
            for subj in CORE_SUBJECTS:
                prev = st.subject_mastery[subj]
                new_val = float(np.clip(prev + delta, 15.0, 100.0))
                st.subject_mastery[subj] = new_val

            # Optional periodic assessment
            if is_assessment_day and is_present:
                sid_num = int("".join(c for c in sid if c.isdigit()) or "0")
                rng = np.random.default_rng([self.seed, day_index, sid_num])
                noise = float(rng.normal(0, 2.5))
                # Raw score adjusted by assessment difficulty
                raw_score = float(np.clip((st.overall_mastery / difficulty) + noise, 0.0, 100.0))
                st.assessment_history.append({
                    "date": date_str,
                    "score": round(raw_score, 1),
                    "difficulty": round(difficulty, 2),
                    "overall_mastery": round(st.overall_mastery, 1),
                })

        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Computes aggregate academic mastery metrics across all students."""
        if not self.students:
            return {
                "average_subject_mastery": 68.5,
                "uncovered_periods_total": 0,
                "lost_instructional_hours": 0.0,
                "mastery_p10": 58.0,
                "mastery_p50": 68.5,
                "mastery_p90": 78.0,
                "total_students_tracked": 0,
            }

        masteries = [st.overall_mastery for st in self.students.values()]
        arr = np.array(masteries)
        mean_m = round(float(arr.mean()), 2)
        return {
            "average_subject_mastery": mean_m,
            "mean_subject_mastery": mean_m,
            "uncovered_periods_total": self.total_uncovered_periods,
            "lost_instructional_hours": round(self.total_lost_instructional_minutes / 60.0, 1),
            "mastery_p10": round(float(np.percentile(arr, 10)), 1),
            "mastery_p50": round(float(np.percentile(arr, 50)), 1),
            "mastery_p90": round(float(np.percentile(arr, 90)), 1),
            "total_students_tracked": len(self.students),
        }
