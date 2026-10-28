"""Event and effect data records and audit trail."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

RULESET_VERSION = "3.0.0"
ENGINE_VERSION = "3.0.0"




@dataclass
class EventRecord:
    event_id: str
    event_type: str
    effective_date: str
    target_entities: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    source: str = "scenario"  # scenario, story, random, policy
    validation_status: str = "valid"  # valid, invalid, rejected
    execution_status: str = "pending"  # pending, executed, skipped, failed
    rule_version: str = RULESET_VERSION
    title: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EffectRecord:
    effect_id: str
    source_event_id: str
    target_subsystem: str  # attendance, academics, staffing, finance, transport, safety, investigation
    target_entity: str     # entity ID or subsystem name
    affected_field: str    # specific field or metric modified
    previous_value: Any
    resulting_value: Any
    applied_rule_id: str
    effective_date: str
    delay_days: int = 0
    assumptions: str = ""
    provenance: str = ""   # formula or derivation rule
    status: str = "applied"  # applied, skipped, rejected, unsupported
    rule_version: str = RULESET_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CausalChainNode:
    node_type: str  # event, rule, state_transition, derived_metric
    node_id: str
    title: str
    detail: str
    date: str
    subsystem: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)




class CausalAuditTrail:


    def __init__(self, run_id: str = "baseline", seed: int = 20261014):
        self.run_id = run_id
        self.seed = seed
        self.events: Dict[str, EventRecord] = {}
        self.effects: List[EffectRecord] = []
        self.chains: Dict[str, List[CausalChainNode]] = {}  # metric_id -> causal chain
        self._effect_counter: int = 0

    def next_effect_id(self, date_str: str) -> str:
        self._effect_counter += 1
        return f"FX-{date_str}-{self._effect_counter:04d}"

    def register_event(self, ev: EventRecord) -> None:
        self.events[ev.event_id] = ev

    def record_effect(self, fx: EffectRecord) -> None:
        self.effects.append(fx)

    def add_causal_link(self, metric_id: str, node: CausalChainNode) -> None:
        if metric_id not in self.chains:
            self.chains[metric_id] = []
        self.chains[metric_id].append(node)

    def get_chain(self, metric_id: str) -> List[Dict[str, Any]]:
        return [node.to_dict() for node in self.chains.get(metric_id, [])]

    def get_effects_for_subsystem(self, subsystem: str) -> List[EffectRecord]:
        return [e for e in self.effects if e.target_subsystem == subsystem and e.status == "applied"]

    def to_summary(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "ruleset_version": RULESET_VERSION,
            "total_events_registered": len(self.events),
            "total_effects_applied": len([e for e in self.effects if e.status == "applied"]),
            "effects_by_subsystem": {
                sub: len([e for e in self.effects if e.target_subsystem == sub])
                for sub in ["attendance", "academics", "staffing", "finance", "transport", "safety", "investigation"]
            },
            "events": [ev.to_dict() for ev in self.events.values()],
            "effects": [fx.to_dict() for fx in self.effects],
            "chains": {k: [node.to_dict() for node in nodes] for k, nodes in self.chains.items()}
        }




class InvestigationStatus:
    REPORTED = "reported"
    UNDER_REVIEW = "under_review"
    INVESTIGATION_IN_PROGRESS = "investigation_in_progress"
    SUBSTANTIATED = "substantiated"
    NOT_SUBSTANTIATED = "not_substantiated"
    UNRESOLVED = "unresolved"
    CLOSED = "closed"

    ALL_STATUSES = {
        REPORTED, UNDER_REVIEW, INVESTIGATION_IN_PROGRESS,
        SUBSTANTIATED, NOT_SUBSTANTIATED, UNRESOLVED, CLOSED
    }


@dataclass
class InvestigationRecord:
    case_id: str
    student_id: str
    reported_date: str
    status: str = InvestigationStatus.UNDER_REVIEW
    allegation_type: str = "unauthorized_peer_transaction"
    location: str = "admin_lobby"
    findings_summary: str = "Presumed innocent; administrative inquiry in progress."
    resolution_date: Optional[str] = None
    disciplinary_action_taken: bool = False
    action_detail: str = ""

    def transition(self, new_status: str, effective_date: str, notes: str = "", disciplinary_action: bool = False) -> None:
        if new_status not in InvestigationStatus.ALL_STATUSES:
            raise ValueError(f"Invalid investigation status: {new_status}")
        self.status = new_status
        self.findings_summary = notes or self.findings_summary
        if new_status in {InvestigationStatus.SUBSTANTIATED, InvestigationStatus.NOT_SUBSTANTIATED, InvestigationStatus.CLOSED, InvestigationStatus.UNRESOLVED}:
            self.resolution_date = effective_date
        self.disciplinary_action_taken = disciplinary_action and (new_status == InvestigationStatus.SUBSTANTIATED)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)




class BusStatus:
    AVAILABLE = "available"
    BROKEN_DOWN = "broken_down"
    IN_REPAIR = "in_repair"
    STANDBY_DEPLOYED = "standby_deployed"


@dataclass
class BusAssetRecord:
    bus_id: str
    route_number: int
    status: str = BusStatus.AVAILABLE
    capacity: int = 50
    breakdown_date: Optional[str] = None
    repair_completion_date: Optional[str] = None
    repair_cost_inr: int = 0
    assigned_students: List[str] = field(default_factory=list)

    def breakdown(self, date_str: str, repair_days: int = 2, estimated_cost_inr: int = 15000) -> None:
        self.status = BusStatus.BROKEN_DOWN
        self.breakdown_date = date_str
        self.repair_cost_inr = estimated_cost_inr
        # compute completion ISO date
        from datetime import datetime, timedelta
        dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=repair_days)
        self.repair_completion_date = dt.strftime("%Y-%m-%d")

    def restore_service(self) -> None:
        self.status = BusStatus.AVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
