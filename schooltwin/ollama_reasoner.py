"""Optional Local Ollama Reasoning and Deterministic Replay Trace for SchoolTwin Phase 4.

Integrates with locally running Ollama (e.g. qwen3.5:4b) via HTTP. Enforces strict
structured JSON schemas, bounded circuit breakers (3 failures -> trip), transparent
fallback to RuleBasedReasoner, and canonical hash-based decision trace replay.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .agent_decision import ActionValidator, RuleBasedReasoner, SUPPORTED_ACTIONS
from .cognitive import AgentDecision, AgentGoal, AgentMemory, ApprovalTier, CognitiveState
from .nlp import is_ollama_available

OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen3.5:4b"


def compute_request_hash(agent_id: int, date_str: str, trigger: str, context: str) -> str:
    """Computes a canonical SHA-256 hash for an agent decision context."""
    raw = f"{agent_id}|{date_str}|{trigger}|{context}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class OllamaReasoner:
    """Optional LLM-assisted decision maker with circuit breaker and deterministic replay."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        enabled: bool = True,
        timeout_seconds: float = 2.5,
        rule_fallback: Optional[RuleBasedReasoner] = None,
    ):
        self.model = model
        self.enabled = enabled
        self.timeout = timeout_seconds
        self.rule_engine = rule_fallback or RuleBasedReasoner()

        # Circuit breaker state
        self.failure_count = 0
        self.circuit_open_until = 0.0
        self.total_calls = 0
        self.fallback_calls = 0
        self.replayed_calls = 0

        # Persistent decision trace for bit-for-bit replay
        self.decision_trace: Dict[str, Dict[str, Any]] = {}

    def is_available(self) -> bool:
        """Returns True if enabled, circuit breaker is closed, and Ollama is reachable."""
        if not self.enabled:
            return False
        if time.time() < self.circuit_open_until:
            return False
        return is_ollama_available()

    def record_failure(self) -> None:
        """Trips circuit breaker after 3 consecutive failures for 60 seconds."""
        self.failure_count += 1
        if self.failure_count >= 3:
            self.circuit_open_until = time.time() + 60.0

    def record_success(self) -> None:
        self.failure_count = 0

    def load_trace(self, trace_data: Dict[str, Dict[str, Any]]) -> None:
        """Loads a pre-recorded decision trace for deterministic scenario replay."""
        self.decision_trace = dict(trace_data)

    def export_trace(self) -> Dict[str, Dict[str, Any]]:
        """Exports the recorded decision trace."""
        return dict(self.decision_trace)

    def reason_agent_decision(
        self,
        agent_id: int,
        role: str,
        state: CognitiveState,
        active_goal: Optional[AgentGoal],
        recent_memories: List[AgentMemory],
        date_str: str,
        trigger_context: str,
    ) -> AgentDecision:
        """Evaluates an agent decision via: Replay Trace -> Local Ollama -> Rule Fallback."""
        self.total_calls += 1
        req_hash = compute_request_hash(agent_id, date_str, role, trigger_context)

        # 1. Check if decision is already in replay trace
        if req_hash in self.decision_trace:
            self.replayed_calls += 1
            rec = self.decision_trace[req_hash]
            return AgentDecision(
                decision_id=rec["decision_id"],
                agent_id=agent_id,
                agent_role=role,
                action_name=rec["action_name"],
                target_entity=rec.get("target_entity"),
                parameters=rec.get("parameters", {}),
                supporting_event_ids=rec.get("supporting_event_ids", []),
                memory_ids_used=rec.get("memory_ids_used", []),
                rationale=rec.get("rationale", ""),
                uncertainty=rec.get("uncertainty", 0.0),
                approval_tier=ApprovalTier(rec.get("approval_tier", "low_impact")),
                provenance="replayed_trace",
                status=rec.get("status", "approved"),
                date=date_str,
            )

        # 2. If Ollama is available, attempt structured inference
        if self.is_available():
            decision = self._call_ollama_structured(
                agent_id=agent_id,
                role=role,
                state=state,
                active_goal=active_goal,
                recent_memories=recent_memories,
                date_str=date_str,
                trigger=trigger_context,
                req_hash=req_hash,
            )
            if decision:
                self.record_success()
                self.decision_trace[req_hash] = decision.to_dict()
                return decision
            else:
                self.record_failure()

        # 3. Transparent deterministic fallback to RuleBasedReasoner
        self.fallback_calls += 1
        st = state or CognitiveState(agent_id=agent_id, role=role)
        if role == "student":
            dec = self.rule_engine.decide_student_action(agent_id, st, active_goal, recent_memories, date_str)
        elif role == "teacher":
            dec = self.rule_engine.decide_teacher_action(agent_id, st, active_goal, recent_memories, date_str)
        else:
            dec = self.rule_engine.decide_principal_action("general", {}, date_str, {})

        dec.provenance = "fallback_rule"
        self.decision_trace[req_hash] = dec.to_dict()
        return dec

    def _call_ollama_structured(
        self,
        agent_id: int,
        role: str,
        state: Optional[CognitiveState],
        active_goal: Optional[AgentGoal],
        recent_memories: List[AgentMemory],
        date_str: str,
        trigger: str,
        req_hash: str,
    ) -> Optional[AgentDecision]:
        """Calls local Ollama with a compact prompt and validates structured JSON output."""
        # Filter supported actions for this role
        valid_actions = [k for k, v in SUPPORTED_ACTIONS.items() if v["role"] == role or (role == "principal" and v["role"] in ("teacher", "principal"))]
        if state:
            state_desc = f"State: stress={state.stress_proxy:.0f}/100, engagement={state.engagement:.2f}, confidence={state.academic_confidence:.2f}."
        else:
            state_desc = f"State: Active {role} duty."

        prompt = (
            f"You are agent {agent_id} ({role}) in a Delhi school simulation on {date_str}.\n"
            f"{state_desc}\n"
            f"Active Goal: {active_goal.target_outcome if active_goal else 'None'}.\n"
            f"Memories: {[m.summary for m in recent_memories[:2]]}.\n"
            f"Context: {trigger}.\n"
            f"Allowed actions: {valid_actions}.\n"
            "Return valid JSON ONLY with fields: action_name (string), parameters (object), rationale (string, max 15 words), uncertainty (float 0-1)."
        )

        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_predict": 100},
        }

        try:
            req = urllib.request.Request(
                OLLAMA_ENDPOINT,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                response_text = data.get("response", "")
                parsed = json.loads(response_text)

                act_name = parsed.get("action_name", "")
                params = parsed.get("parameters", {})
                is_valid, errs, tier = ActionValidator.validate_action(agent_id, role, act_name, params)
                if not is_valid:
                    return None

                return AgentDecision(
                    decision_id=f"DEC-{agent_id}-{date_str}-LLM-{req_hash[:6]}",
                    agent_id=agent_id,
                    agent_role=role,
                    action_name=act_name,
                    parameters=params,
                    supporting_event_ids=[m.source_event_id for m in recent_memories[:2]],
                    memory_ids_used=[m.memory_id for m in recent_memories[:2]],
                    rationale=str(parsed.get("rationale", "Autonomous model decision.")),
                    uncertainty=float(parsed.get("uncertainty", 0.1)),
                    approval_tier=tier,
                    provenance=f"ollama_{self.model}",
                    status="approved" if tier != ApprovalTier.HIGH_IMPACT else "proposed_awaiting_approval",
                    date=date_str,
                )
        except Exception:
            return None
