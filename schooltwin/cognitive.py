"""Core Cognitive State, Memory, Goals, and Relationship Models for SchoolTwin Phase 4.

Defines the Level 1 lightweight individual agent state, bounded epistemic memory,
sparse relationship graphs, and structured decision action schemas.
"""
from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


class EpistemicStatus(str, enum.Enum):
    """Epistemological ground for an agent's memory or belief.
    
    Preserves strict boundaries between verified ground truth, eyewitness observation,
    unsubstantiated rumor/hearsay, and administrative communication.
    """
    CONFIRMED_FACT = "confirmed_fact"          # Agent directly involved or official administrative record
    EYEWITNESS_ACCOUNT = "eyewitness_account"  # Agent was present in zone when event occurred
    UNSUBSTANTIATED_HEARSAY = "unsubstantiated_hearsay" # Peer hearsay, rumor, or second-hand talk
    ADMINISTRATIVE_NOTICE = "administrative_notice"     # Official school announcement or notice


class GoalStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    DEFERRED = "deferred"


class RelationshipType(str, enum.Enum):
    CLASSMATE = "classmate"
    CLOSE_FRIEND = "close_friend"
    TEACHER_STUDENT = "teacher_student"
    COWORKER = "coworker"
    ADVERSARY = "adversary"


class ApprovalTier(str, enum.Enum):
    """4-Tier authorization model for agent decisions."""
    INFORMATIONAL = "informational"      # Diagnostic reports, metrics queries (automatic)
    LOW_IMPACT = "low_impact"            # Minor reversible actions: tutor session, backup bus (auto if enabled)
    HIGH_IMPACT = "high_impact"          # Consequential actions: suspension, hiring, fee override (requires human approval)
    PROHIBITED = "prohibited"            # Unsupported actions, ledger forgery, biometric tracking (always rejected)


@dataclass
class AgentMemory:
    """A bounded, inspectable memory entry for an individual agent."""
    memory_id: str
    agent_id: int
    source_event_id: str
    simulated_date: str
    memory_type: str                     # "incident", "academic", "policy", "social", "operational"
    summary: str
    importance: float = 0.5             # 0.0 to 1.0 scale
    epistemic_status: EpistemicStatus = EpistemicStatus.EYEWITNESS_ACCOUNT
    tags: List[str] = field(default_factory=list)
    confidence: float = 1.0              # 0.0 to 1.0
    expiry_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["epistemic_status"] = self.epistemic_status.value
        return d


@dataclass
class AgentGoal:
    """An explicit objective guiding agent action selection."""
    goal_id: str
    agent_id: int
    goal_type: str                       # e.g., "prepare_assessment", "maintain_class_coverage", "resolve_investigation"
    target_outcome: str
    priority: int = 3                    # 1 (lowest) to 5 (highest)
    status: GoalStatus = GoalStatus.ACTIVE
    created_date: str = "2026-01-01"
    target_date: Optional[str] = None
    progress: float = 0.0                # 0.0 to 1.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class AgentRelationship:
    """A sparse, directed link between two agents."""
    source_id: int
    target_id: int
    relation_type: RelationshipType
    affinity: float = 0.5                # -1.0 (hostile/adversary) to +1.0 (best friend / trusted ally)
    last_interaction_date: str = "2026-01-01"
    shared_event_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["relation_type"] = self.relation_type.value
        return d


@dataclass
class CognitiveState:
    """Level 1 lightweight individual dynamic state for students and staff.
    
    Contains only bounded, documented operational variables connected to simulation rules.
    Does NOT duplicate authoritative academic/attendance truth.
    """
    agent_id: int
    role: str                            # student | teacher | principal | staff
    engagement: float = 0.75             # 0.0 (disengaged) to 1.0 (highly engaged)
    academic_confidence: float = 0.70    # 0.0 to 1.0 (subject mastery self-efficacy proxy)
    stress_proxy: float = 25.0           # 0.0 (calm) to 100.0 (severe operational friction)
    compliance_tendency: float = 0.85    # 0.0 to 1.0 tendency to follow instructions
    current_goal_id: Optional[str] = None
    memory_ids: List[str] = field(default_factory=list)
    relationships: Dict[int, str] = field(default_factory=dict) # target_id -> RelationshipType
    active_action: Optional[str] = None
    last_activated_date: str = "2026-01-01"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDecision:
    """Structured, validated decision record proposed by an agent or AI Principal."""
    decision_id: str
    agent_id: int
    agent_role: str
    action_name: str
    target_entity: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    supporting_event_ids: List[str] = field(default_factory=list)
    memory_ids_used: List[str] = field(default_factory=list)
    rationale: str = ""
    uncertainty: float = 0.0             # 0.0 to 1.0
    approval_tier: ApprovalTier = ApprovalTier.LOW_IMPACT
    provenance: str = "rule_engine"      # "rule_engine" | "ollama_<model>" | "fallback_rule" | "replayed_trace"
    status: str = "proposed"             # "proposed" | "approved" | "rejected" | "executed" | "unresolved"
    date: str = "2026-01-01"
    validation_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["approval_tier"] = self.approval_tier.value
        return d
