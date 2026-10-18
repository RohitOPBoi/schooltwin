"""Supported Agent Actions, Validation, and Deterministic Decision Reasoning for SchoolTwin Phase 4.

Defines the action catalog, precondition validation, approval tier assignments,
and the deterministic RuleBasedReasoner that powers routine agent choices without an LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .cognitive import (
    AgentDecision,
    AgentGoal,
    AgentMemory,
    ApprovalTier,
    CognitiveState,
    EpistemicStatus,
    GoalStatus,
)

# Canonical catalog of supported agent actions across roles
SUPPORTED_ACTIONS = {
    # Student actions
    "seek_academic_help": {
        "role": "student",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Student requests remedial guidance or peer study session to improve mastery.",
        "params": ["subject", "target_teacher_or_peer"],
    },
    "report_safety_incident": {
        "role": "student",
        "approval_tier": ApprovalTier.INFORMATIONAL,
        "description": "Student informs teacher or security of playground or corridor friction.",
        "params": ["location", "involved_student_ids"],
    },
    "cooperate_with_investigation": {
        "role": "student",
        "approval_tier": ApprovalTier.INFORMATIONAL,
        "description": "Student provides formal testimony or eyewitness account to administration.",
        "params": ["case_id", "statement_summary"],
    },
    "focus_on_exam_prep": {
        "role": "student",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Student prioritizes library study and assessment preparation.",
        "params": ["target_subject"],
    },

    # Teacher actions
    "provide_remedial_instruction": {
        "role": "teacher",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Teacher schedules remedial review for classes affected by uncovered periods.",
        "params": ["class_section", "subject", "duration_minutes"],
    },
    "intervene_classroom_friction": {
        "role": "teacher",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Teacher defuses classroom disagreement and separates disruptive students.",
        "params": ["class_section", "involved_student_ids"],
    },
    "request_substitute_cover": {
        "role": "teacher",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Teacher requests administrative coverage due to medical or official leave.",
        "params": ["date", "periods"],
    },
    "escalate_to_principal": {
        "role": "teacher",
        "approval_tier": ApprovalTier.INFORMATIONAL,
        "description": "Teacher refers persistent behavioral or academic issue to school leadership.",
        "params": ["student_id", "issue_summary"],
    },

    # Principal actions
    "dispatch_bus_backup": {
        "role": "principal",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Principal authorizes standby backup bus to mitigate route breakdown delays.",
        "params": ["route_number", "backup_bus_id"],
    },
    "order_counselling_intervention": {
        "role": "principal",
        "approval_tier": ApprovalTier.LOW_IMPACT,
        "description": "Principal assigns school counselor to support students involved in altercation.",
        "params": ["student_ids", "session_date"],
    },
    "open_formal_investigation": {
        "role": "principal",
        "approval_tier": ApprovalTier.INFORMATIONAL,
        "description": "Principal initiates formal administrative review into an allegation.",
        "params": ["case_id", "accused_student_id", "lead_investigator"],
    },
    "request_governance_fee_override": {
        "role": "principal",
        "approval_tier": ApprovalTier.HIGH_IMPACT,
        "description": "Principal requests school board approval for tuition or transport fee changes.",
        "params": ["fee_category", "delta_pct"],
    },
    "authorize_student_suspension": {
        "role": "principal",
        "approval_tier": ApprovalTier.HIGH_IMPACT,
        "description": "Principal orders temporary disciplinary suspension following substantiated violation.",
        "params": ["student_id", "duration_days", "justification"],
    },
}


class ActionValidator:
    """Validates action proposals against supported schemas, bounds, and permissions."""

    @staticmethod
    def validate_action(
        agent_id: int,
        agent_role: str,
        action_name: str,
        params: Dict[str, Any],
        known_student_sids: Optional[Set[str]] = None,
    ) -> Tuple[bool, List[str], ApprovalTier]:
        """Validates action existence, role authorization, and required parameters."""
        errors = []
        if action_name not in SUPPORTED_ACTIONS:
            return False, [f"Action '{action_name}' is not in the canonical simulation catalog."], ApprovalTier.PROHIBITED

        schema = SUPPORTED_ACTIONS[action_name]
        expected_role = schema["role"]
        tier = schema["approval_tier"]

        # 1. Role permission check
        if agent_role != expected_role and not (agent_role == "principal" and expected_role in ("teacher", "principal")):
            errors.append(f"Agent {agent_id} (role: {agent_role}) is not authorized to execute {action_name} (requires {expected_role}).")

        # 2. Parameter checks
        req_params = schema.get("params", [])
        for p in req_params:
            if p not in params:
                errors.append(f"Missing required parameter '{p}' for action '{action_name}'.")

        # 3. Entity reference validation if student IDs are passed
        if known_student_sids and "student_id" in params:
            sid = str(params["student_id"])
            if sid not in known_student_sids:
                errors.append(f"Referenced student ID '{sid}' does not exist in active school roster.")

        if known_student_sids and "student_ids" in params:
            sids = params["student_ids"]
            if isinstance(sids, list):
                for sid in sids:
                    if str(sid) not in known_student_sids:
                        errors.append(f"Referenced student ID '{sid}' does not exist in active school roster.")

        is_valid = len(errors) == 0
        return is_valid, errors, tier


class RuleBasedReasoner:
    """Deterministic, fast decision-making engine for routine and event-triggered agent choices."""

    def __init__(self, seed: int = 20261014):
        self.seed = seed

    def decide_student_action(
        self,
        agent_id: int,
        state: CognitiveState,
        active_goal: Optional[AgentGoal],
        recent_memories: List[AgentMemory],
        date_str: str,
    ) -> AgentDecision:
        """Determines the most appropriate student action using deterministic state rules."""
        # 1. Check if student has high stress or recent incident memory
        incident_mems = [m for m in recent_memories if m.memory_type in ("serious_student_fight", "incident")]
        if incident_mems and state.stress_proxy > 40.0:
            top_mem = incident_mems[0]
            if top_mem.epistemic_status == EpistemicStatus.CONFIRMED_FACT:
                # Cooperate with investigation if asked
                return AgentDecision(
                    decision_id=f"DEC-{agent_id}-{date_str}-COOP",
                    agent_id=agent_id,
                    agent_role="student",
                    action_name="cooperate_with_investigation",
                    target_entity=top_mem.source_event_id,
                    parameters={"case_id": top_mem.source_event_id, "statement_summary": "Provided factual statement regarding altercation"},
                    supporting_event_ids=[top_mem.source_event_id],
                    memory_ids_used=[top_mem.memory_id],
                    rationale="Complying with administrative inquiry regarding playground incident.",
                    approval_tier=ApprovalTier.INFORMATIONAL,
                    provenance="rule_engine",
                    status="approved",
                    date=date_str,
                )

        # 2. Check if student has low academic confidence
        if state.academic_confidence < 0.55:
            return AgentDecision(
                decision_id=f"DEC-{agent_id}-{date_str}-HELP",
                agent_id=agent_id,
                agent_role="student",
                action_name="seek_academic_help",
                parameters={"subject": "Mathematics", "target_teacher_or_peer": "Teacher"},
                rationale="Seeking remedial guidance to recover lost instructional exposure.",
                approval_tier=ApprovalTier.LOW_IMPACT,
                provenance="rule_engine",
                status="approved",
                date=date_str,
            )

        # 3. Default: Exam prep and assessment focus
        return AgentDecision(
            decision_id=f"DEC-{agent_id}-{date_str}-PREP",
            agent_id=agent_id,
            agent_role="student",
            action_name="focus_on_exam_prep",
            parameters={"target_subject": "General"},
            rationale="Continuing scheduled curriculum study and preparation.",
            approval_tier=ApprovalTier.LOW_IMPACT,
            provenance="rule_engine",
            status="approved",
            date=date_str,
        )

    def decide_teacher_action(
        self,
        agent_id: int,
        state: CognitiveState,
        active_goal: Optional[AgentGoal],
        recent_memories: List[AgentMemory],
        date_str: str,
        uncovered_in_school: bool = False,
    ) -> AgentDecision:
        """Determines teacher response given timetable pressure and student needs."""
        # If school has uncovered periods and teacher has capacity -> offer remedial instruction
        if uncovered_in_school:
            return AgentDecision(
                decision_id=f"DEC-{agent_id}-{date_str}-REMEDIAL",
                agent_id=agent_id,
                agent_role="teacher",
                action_name="provide_remedial_instruction",
                parameters={"class_section": "Class 8B", "subject": "Science", "duration_minutes": 45},
                rationale="Organizing extra lesson to bridge instructional deficit from vacant periods.",
                approval_tier=ApprovalTier.LOW_IMPACT,
                provenance="rule_engine",
                status="approved",
                date=date_str,
            )

        # Default teacher action: routine curriculum delivery
        return AgentDecision(
            decision_id=f"DEC-{agent_id}-{date_str}-DELIVER",
            agent_id=agent_id,
            agent_role="teacher",
            action_name="intervene_classroom_friction",
            parameters={"class_section": "General", "involved_student_ids": []},
            rationale="Maintaining classroom order and instructional delivery.",
            approval_tier=ApprovalTier.LOW_IMPACT,
            provenance="rule_engine",
            status="approved",
            date=date_str,
        )

    def decide_principal_action(
        self,
        alert_code: str,
        evidence: Dict[str, Any],
        date_str: str,
        human_approvals: Dict[str, bool],
    ) -> AgentDecision:
        """Determines AI Principal action with 4-tier authorization checks."""
        dec_id = f"DEC-PRIN-{date_str}-{alert_code}"

        if alert_code in ("transport_arrival_spike", "bus_breakdown"):
            return AgentDecision(
                decision_id=dec_id,
                agent_id=0,
                agent_role="principal",
                action_name="dispatch_bus_backup",
                parameters={"route_number": evidence.get("route", 3), "backup_bus_id": "BUS-STANDBY-01"},
                supporting_event_ids=[evidence.get("event_id", "")],
                rationale="Deploying contracted standby vehicle to alleviate route delays.",
                approval_tier=ApprovalTier.LOW_IMPACT,
                provenance="rule_engine",
                status="approved", # Low impact auto-approves
                date=date_str,
            )

        if alert_code in ("serious_student_fight", "campus_safety_incident"):
            sids = evidence.get("student_ids", ["STU-0012", "STU-0015", "STU-0021"])
            return AgentDecision(
                decision_id=dec_id,
                agent_id=0,
                agent_role="principal",
                action_name="order_counselling_intervention",
                parameters={"student_ids": sids, "session_date": date_str},
                supporting_event_ids=[evidence.get("event_id", "")],
                rationale="Dispatching student welfare counselor and nursing triage post-altercation.",
                approval_tier=ApprovalTier.LOW_IMPACT,
                provenance="rule_engine",
                status="approved",
                date=date_str,
            )

        if alert_code in ("suspected_prohibited_business", "disciplinary_allegation"):
            case_id = evidence.get("case_id", f"CASE-{date_str}")
            accused = evidence.get("student_id", "STU-0044")
            # Opening investigation is Informational
            return AgentDecision(
                decision_id=dec_id,
                agent_id=0,
                agent_role="principal",
                action_name="open_formal_investigation",
                parameters={"case_id": case_id, "accused_student_id": accused, "lead_investigator": "Vice Principal"},
                supporting_event_ids=[case_id],
                rationale="Commencing formal review under presumption of innocence.",
                approval_tier=ApprovalTier.INFORMATIONAL,
                provenance="rule_engine",
                status="approved",
                date=date_str,
            )

        if alert_code == "fee_policy_revision":
            # HIGH IMPACT: Requires human approval gate
            is_approved = human_approvals.get(dec_id)
            if is_approved is True:
                status = "approved"
            elif is_approved is False:
                status = "rejected"
            else:
                status = "proposed_awaiting_approval"

            return AgentDecision(
                decision_id=dec_id,
                agent_id=0,
                agent_role="principal",
                action_name="request_governance_fee_override",
                parameters={"fee_category": "tuition", "delta_pct": evidence.get("delta_pct", 10.0)},
                rationale="Requesting school board approval for tuition fee revision.",
                approval_tier=ApprovalTier.HIGH_IMPACT,
                provenance="rule_engine",
                status=status,
                date=date_str,
            )

        # Default fallback informational decision
        return AgentDecision(
            decision_id=dec_id,
            agent_id=0,
            agent_role="principal",
            action_name="open_formal_investigation",
            parameters={"case_id": f"GEN-{date_str}", "accused_student_id": "", "lead_investigator": "Administration"},
            rationale="Reviewing operational log and monitoring school indicators.",
            approval_tier=ApprovalTier.INFORMATIONAL,
            provenance="rule_engine",
            status="approved",
            date=date_str,
        )
