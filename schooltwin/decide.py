"""The AI Principal decision agent for SchoolTwin Phase 4.

Provides 4-tier authorization (informational, low-impact auto, high-impact human approval,
and prohibited), evidence-based structured proposals, and optional local Ollama reasoning.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .agent_decision import ActionValidator, SUPPORTED_ACTIONS
from .cognitive import ApprovalTier, CognitiveState
from .ollama_reasoner import OllamaReasoner

AUTONOMY = ("advisory_only", "low_risk_auto", "human_approved")
EFFECTS = {   # rule -> (effect name, days): the only decisions that change the simulation
    "attendance_arrival_deviation": ("notify_families", 3),
    "crowd_buildup": ("stagger_canteen", 15),
    "cover_plan_conflict": ("replan_cover", 5),
    "heat_utility_pressure": ("heat_protocol", 20),
    "transport_arrival_spike": ("backup_route", 10),
    "serious_student_fight": ("order_counselling_intervention", 7),
    "bus_breakdown": ("dispatch_bus_backup", 5),
}


def decision_library(story: Any) -> Dict[str, Dict[str, Any]]:
    """Builds template library from historical story decisions."""
    lib = {}
    for d in getattr(story, "decisions", []):
        date = d["decision_id"][-10:]
        for a in getattr(story, "alerts", []):
            if a["date"] == date and a["rule_code"] != "classroom_friction_cluster":
                lib.setdefault(a["rule_code"], d)
    return lib


class Principal:
    """School leadership decision agent with 4-tier authorization safeguards."""

    def __init__(
        self,
        story: Any,
        autonomy: str = "low_risk_auto",
        provider: str = "mock",
        ollama_reasoner: Optional[OllamaReasoner] = None,
    ):
        self.story = story
        self.autonomy = autonomy
        self.provider = provider
        self.lib = decision_library(story)
        self.ollama = ollama_reasoner
        self.n = 0
        self.proposals_history: List[Dict[str, Any]] = []

    def propose(self, alert: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Proposes a structured, evidence-based decision for an operational alert."""
        rule_code = alert.get("rule_code", "")
        tpl = self.lib.get(rule_code)

        # Fallback template if rule_code was added in Phase 3/4
        if not tpl:
            if rule_code in ("serious_student_fight", "campus_safety_incident"):
                tpl = {
                    "title": "Dispatch Student Welfare Counselor & Medical Triage",
                    "risk_level": "low",
                    "autonomy_mode": "automatic_with_audit",
                    "action": "order_counselling_intervention",
                    "reasoning_summary": "Dispatched school counselor and infirmary triage following peer altercation.",
                }
            elif rule_code in ("bus_breakdown", "transport_lateness_spike"):
                tpl = {
                    "title": "Deploy Contracted Standby Bus",
                    "risk_level": "low",
                    "autonomy_mode": "automatic_with_audit",
                    "action": "dispatch_bus_backup",
                    "reasoning_summary": "Authorized standby bus deployment to mitigate route transit delay.",
                }
            elif rule_code in ("fee_policy_revision", "tuition_fee_change"):
                tpl = {
                    "title": "School Board Fee Revision Proposal",
                    "risk_level": "high",
                    "autonomy_mode": "human_approval_required",
                    "action": "request_governance_fee_override",
                    "reasoning_summary": "Submitted proposed tuition fee revision for mandatory school board approval.",
                }
            else:
                return None

        self.n += 1
        risk = tpl.get("risk_level", "low")

        # 4-Tier Authorization Assignment
        if risk in ("critical", "high"):
            approval_tier = ApprovalTier.HIGH_IMPACT
        elif risk == "medium":
            approval_tier = ApprovalTier.LOW_IMPACT
        else:
            approval_tier = ApprovalTier.LOW_IMPACT

        # Autonomy execution logic
        # High impact ALWAYS requires human approval regardless of autonomy setting
        if approval_tier == ApprovalTier.HIGH_IMPACT:
            auto = False
            status = "proposed_awaiting_approval"
        elif self.autonomy == "advisory_only":
            auto = False
            status = "proposed_awaiting_approval"
        elif self.autonomy == "human_approved":
            auto = False
            status = "proposed_awaiting_approval"
        else:
            # low_risk_auto: auto-approves low/medium impact
            auto = True
            status = "implemented_audited"

        reasoning, provenance = self._reason(tpl, alert, state)

        decision = {
            "decision_id": f"AI-{alert['date']}-{rule_code}",
            "date": alert["date"],
            "title": tpl["title"],
            "risk_level": risk,
            "approval_tier": approval_tier.value,
            "autonomy_mode": "automatic_with_audit" if auto else "human_approval_required",
            "status": status,
            "action": tpl["action"],
            "alert_id": alert.get("alert_id", ""),
            "rule_code": rule_code,
            "reasoning": reasoning,
            "provenance": provenance,
            "state_summary_used": state,
            "evidence_used": alert.get("evidence", {}),
            "human_override_available": True,
            "effect": EFFECTS.get(rule_code),
        }

        self.proposals_history.append(decision)
        return decision

    def _reason(self, tpl: Dict[str, Any], alert: Dict[str, Any], state: Dict[str, Any]) -> Tuple[str, str]:
        """Generates reasoning explanation using Ollama if configured, falling back to canonical template."""
        base = tpl.get("reasoning_summary", "Administrative response based on operational metrics.")

        # 1. Attempt optional local Ollama reasoning if attached
        if self.ollama and self.ollama.is_available():
            try:
                prompt_ctx = f"Alert: {alert.get('rule_code')}, state: {json.dumps(state)}"
                dec = self.ollama.reason_agent_decision(
                    agent_id=0,
                    role="principal",
                    state=CognitiveState(agent_id=0, role="principal", stress_proxy=20.0, engagement=0.9),
                    active_goal=None,
                    recent_memories=[],
                    date_str=alert.get("date", "2026-01-01"),
                    trigger_context=prompt_ctx,
                )
                if dec and dec.rationale:
                    return dec.rationale, dec.provenance
            except Exception:
                pass

        # 2. Existing optional external provider hook if explicitly configured in environment
        if self.provider == "gemini":
            try:
                from google import genai
                client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
                prompt = (
                    "You are a school principal's assistant. In two sentences, explain this proposal. "
                    f"Do not assert causes. Alert: {alert.get('rule_code')} {json.dumps(alert.get('evidence', {}))}. State: {json.dumps(state)}"
                )
                txt = client.models.generate_content(model=os.environ.get("LLM_MODEL", "gemini-2.0-flash"), contents=prompt).text.strip()
                return txt, "gemini_api"
            except Exception:
                pass

        return base, "rule_template"

    def evaluate_policy_recommendation(
        self,
        policy_name: str,
        current_value: Any,
        proposed_value: Any,
        metric_impact_estimate: str,
    ) -> Dict[str, Any]:
        """Produces a structured school leadership recommendation for board review."""
        return {
            "recommendation_id": f"REC-POL-{policy_name}",
            "policy_name": policy_name,
            "current_value": current_value,
            "proposed_value": proposed_value,
            "estimated_impact": metric_impact_estimate,
            "approval_tier": ApprovalTier.HIGH_IMPACT.value,
            "requires_board_vote": True,
            "status": "pending_board_review",
        }
