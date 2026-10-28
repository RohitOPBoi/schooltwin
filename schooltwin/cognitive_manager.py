"""Cognitive Population Manager for SchoolTwin Phase 4.

Maintains Level 1 lightweight cognitive state for all 1,309 agents, manages
sparse relationship graphs, bounded epistemic memory storage with eviction,
and event-triggered perception propagation.
"""
from __future__ import annotations

import collections
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .cognitive import (
    AgentGoal,
    AgentMemory,
    AgentRelationship,
    CognitiveState,
    EpistemicStatus,
    GoalStatus,
    RelationshipType,
)


class CognitivePopulationManager:


    MAX_MEMORIES_PER_AGENT = 12

    def __init__(self, seed: int = 20261014):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.states: Dict[int, CognitiveState] = {}
        self.memories: Dict[int, List[AgentMemory]] = collections.defaultdict(list)
        self.goals: Dict[str, AgentGoal] = {}
        self.relationships: Dict[int, Dict[int, AgentRelationship]] = collections.defaultdict(dict)

        # Fast lookup indices
        self.agent_class: Dict[int, Tuple[str, str]] = {}
        self.class_roster: Dict[Tuple[str, str], List[int]] = collections.defaultdict(list)
        self.route_students: Dict[Any, List[int]] = collections.defaultdict(list)
        self.teachers_by_subject: Dict[str, List[int]] = collections.defaultdict(list)
        self.agent_sid_to_id: Dict[str, int] = {}
        self.agent_id_to_sid: Dict[int, str] = {}

    def initialize_population(self, agents: List[Any], story: Optional[Any] = None) -> None:

        for a in agents:
            self.agent_sid_to_id[a.sid] = a.id
            self.agent_id_to_sid[a.id] = a.sid


            acad_conf = float(np.clip((getattr(a, "acad", 67.0) / 100.0), 0.3, 0.95))
            disc_risk = getattr(a, "disc_risk", 0.2)
            comp_tend = float(np.clip(1.0 - (disc_risk * 0.5), 0.4, 0.98))
            stress = float(np.clip(35.0 - (getattr(a, "mood", 62.0) * 0.25), 10.0, 70.0))

            cs = CognitiveState(
                agent_id=a.id,
                role=a.role,
                engagement=0.78 if a.role == "student" else 0.88,
                academic_confidence=acad_conf,
                stress_proxy=round(stress, 1),
                compliance_tendency=round(comp_tend, 2),
            )
            self.states[a.id] = cs

            # Indexing by class and route
            if a.role == "student":
                self.agent_class[a.id] = (a.grade, a.section)
                self.class_roster[(a.grade, a.section)].append(a.id)
                if a.route:
                    self.route_students[a.route].append(a.id)
                    digits = "".join(c for c in str(a.route) if c.isdigit())
                    if digits:
                        self.route_students[int(digits)].append(a.id)
                # Assign default student academic goal
                g_id = f"GOAL-{a.id}-ACAD-01"
                g = AgentGoal(
                    goal_id=g_id,
                    agent_id=a.id,
                    goal_type="prepare_assessment",
                    target_outcome="Maintain subject mastery and pass assessments",
                    priority=3,
                    status=GoalStatus.ACTIVE,
                    created_date="2026-01-01",
                )
                self.goals[g_id] = g
                cs.current_goal_id = g_id

            elif a.role == "teacher":
                # Index teacher
                subj = getattr(a, "subrole", "") or "General"
                self.teachers_by_subject[subj].append(a.id)
                g_id = f"GOAL-{a.id}-COVER-01"
                g = AgentGoal(
                    goal_id=g_id,
                    agent_id=a.id,
                    goal_type="maintain_class_coverage",
                    target_outcome="Deliver scheduled syllabus without uncovered periods",
                    priority=4,
                    status=GoalStatus.ACTIVE,
                    created_date="2026-01-01",
                )
                self.goals[g_id] = g
                cs.current_goal_id = g_id

            elif a.role == "principal":
                g_id = f"GOAL-{a.id}-MGMT-01"
                g = AgentGoal(
                    goal_id=g_id,
                    agent_id=a.id,
                    goal_type="school_operational_stability",
                    target_outcome="Maintain 90%+ attendance, balanced budget, and zero safety alerts",
                    priority=5,
                    status=GoalStatus.ACTIVE,
                    created_date="2026-01-01",
                )
                self.goals[g_id] = g
                cs.current_goal_id = g_id


        self._build_sparse_relationships(agents)

    def _build_sparse_relationships(self, agents: List[Any]) -> None:
        """Constructs a sparse graph: classmates, explicit close friends, and staff coworkers."""
        # Classmate links (sparse: within same section only)
        for (grade, sec), sids in self.class_roster.items():
            for i, sid1 in enumerate(sids):
                # Connect to up to 6 random classmates
                neighbors = [sids[j] for j in range(len(sids)) if j != i]
                if len(neighbors) > 6:
                    chosen = self.rng.choice(neighbors, size=6, replace=False)
                else:
                    chosen = neighbors

                for sid2 in chosen:
                    rel = AgentRelationship(
                        source_id=sid1,
                        target_id=int(sid2),
                        relation_type=RelationshipType.CLASSMATE,
                        affinity=round(float(self.rng.uniform(0.3, 0.7)), 2),
                    )
                    self.relationships[sid1][int(sid2)] = rel
                    self.states[sid1].relationships[int(sid2)] = RelationshipType.CLASSMATE.value

        # Close friends from agent profile (higher affinity)
        for a in agents:
            if hasattr(a, "friends") and a.friends:
                for fid in a.friends:
                    if fid in self.states:
                        rel = AgentRelationship(
                            source_id=a.id,
                            target_id=fid,
                            relation_type=RelationshipType.CLOSE_FRIEND,
                            affinity=0.88,
                        )
                        self.relationships[a.id][fid] = rel
                        self.states[a.id].relationships[fid] = RelationshipType.CLOSE_FRIEND.value

        # Staff coworker links (sparse within department/role)
        staff_ids = [a.id for a in agents if a.role in ("teacher", "principal", "staff")]
        for sid1 in staff_ids:
            # Connect to 4 peer coworkers
            peers = [s for s in staff_ids if s != sid1]
            if peers:
                chosen = self.rng.choice(peers, size=min(4, len(peers)), replace=False)
                for sid2 in chosen:
                    rel = AgentRelationship(
                        source_id=sid1,
                        target_id=int(sid2),
                        relation_type=RelationshipType.COWORKER,
                        affinity=0.65,
                    )
                    self.relationships[sid1][int(sid2)] = rel
                    self.states[sid1].relationships[int(sid2)] = RelationshipType.COWORKER.value


    def add_memory(self, memory: AgentMemory) -> None:

        aid = memory.agent_id
        if aid not in self.states:
            return

        mem_list = self.memories[aid]
        # Avoid duplicate memories for same source event
        if any(m.source_event_id == memory.source_event_id and m.memory_type == memory.memory_type for m in mem_list):
            return

        # Eviction if capacity reached: preserve highest importance
        if len(mem_list) >= self.MAX_MEMORIES_PER_AGENT:
            # Sort by importance ascending, then simulated_date
            mem_list.sort(key=lambda m: (m.importance, m.simulated_date))
            evicted = mem_list.pop(0)
            if evicted.memory_id in self.states[aid].memory_ids:
                self.states[aid].memory_ids.remove(evicted.memory_id)

        mem_list.append(memory)
        self.states[aid].memory_ids.append(memory.memory_id)

    def retrieve_memories(
        self,
        agent_id: int,
        query_type: Optional[str] = None,
        limit: int = 5,
        min_importance: float = 0.2,
    ) -> List[AgentMemory]:

        if agent_id not in self.memories:
            return []

        mems = self.memories[agent_id]
        if query_type:
            mems = [m for m in mems if m.memory_type == query_type]
        mems = [m for m in mems if m.importance >= min_importance]
        # Sort descending by importance, then recency
        mems.sort(key=lambda m: (m.importance, m.simulated_date), reverse=True)
        return mems[:limit]


    def add_goal(self, goal: AgentGoal) -> None:

        self.goals[goal.goal_id] = goal
        if goal.agent_id in self.states:
            self.states[goal.agent_id].current_goal_id = goal.goal_id

    def get_active_goal(self, agent_id: int) -> Optional[AgentGoal]:

        cs = self.states.get(agent_id)
        if not cs or not cs.current_goal_id:
            return None
        return self.goals.get(cs.current_goal_id)

    def update_goal_progress(self, goal_id: str, delta: float, new_status: Optional[GoalStatus] = None) -> None:

        g = self.goals.get(goal_id)
        if not g:
            return
        g.progress = float(np.clip(g.progress + delta, 0.0, 1.0))
        if g.progress >= 1.0:
            g.status = GoalStatus.COMPLETED
        elif new_status:
            g.status = new_status


    def propagate_event_perception(
        self,
        event_id: str,
        event_type: str,
        date_str: str,
        primary_agent_ids: List[int],
        location: str = "campus",
        details: str = "",
    ) -> Dict[str, int]:
        """Propagates bounded memories with strictly typed epistemic status.
        
        - Primary agents: CONFIRMED_FACT (importance 0.90)
        - Eyewitnesses / close friends: EYEWITNESS_ACCOUNT (importance 0.65)
        - Classmates / peers: UNSUBSTANTIATED_HEARSAY (importance 0.35)
        """
        counts = {"fact": 0, "witness": 0, "hearsay": 0}


        for aid in primary_agent_ids:
            if aid in self.states:
                mem = AgentMemory(
                    memory_id=f"MEM-{aid}-{event_id[:16]}-FACT",
                    agent_id=aid,
                    source_event_id=event_id,
                    simulated_date=date_str,
                    memory_type=event_type,
                    summary=f"Directly involved in {event_type.replace('_', ' ')} at {location}. {details}".strip(),
                    importance=0.92,
                    epistemic_status=EpistemicStatus.CONFIRMED_FACT,
                    confidence=1.0,
                    tags=[event_type, "primary_experience"],
                )
                self.add_memory(mem)
                # Spike stress proxy
                self.states[aid].stress_proxy = float(min(100.0, self.states[aid].stress_proxy + 25.0))
                counts["fact"] += 1


        witness_ids: Set[int] = set()
        for aid in primary_agent_ids:
            for fid, rel in self.relationships.get(aid, {}).items():
                if rel.relation_type == RelationshipType.CLOSE_FRIEND and fid not in primary_agent_ids:
                    witness_ids.add(fid)

        for wid in list(witness_ids)[:10]: # Bounded to prevent explosion
            mem = AgentMemory(
                memory_id=f"MEM-{wid}-{event_id[:16]}-WITNESS",
                agent_id=wid,
                source_event_id=event_id,
                simulated_date=date_str,
                memory_type=event_type,
                summary=f"Witnessed aftermath or was personally notified regarding {event_type.replace('_', ' ')}.",
                importance=0.65,
                epistemic_status=EpistemicStatus.EYEWITNESS_ACCOUNT,
                confidence=0.85,
                tags=[event_type, "witness"],
            )
            self.add_memory(mem)
            self.states[wid].stress_proxy = float(min(100.0, self.states[wid].stress_proxy + 10.0))
            counts["witness"] += 1


        if primary_agent_ids:
            first_aid = primary_agent_ids[0]
            for cid, rel in self.relationships.get(first_aid, {}).items():
                if rel.relation_type == RelationshipType.CLASSMATE and cid not in primary_agent_ids and cid not in witness_ids:
                    mem = AgentMemory(
                        memory_id=f"MEM-{cid}-{event_id[:16]}-HEARSAY",
                        agent_id=cid,
                        source_event_id=event_id,
                        simulated_date=date_str,
                        memory_type=event_type,
                        summary=f"Heard hallway talk regarding an altercation involving classmates at {location}.",
                        importance=0.35,
                        epistemic_status=EpistemicStatus.UNSUBSTANTIATED_HEARSAY,
                        confidence=0.50,
                        tags=[event_type, "hearsay"],
                    )
                    self.add_memory(mem)
                    counts["hearsay"] += 1

        return counts


    def step_daily_states(
        self,
        date_str: str,
        is_school_open: bool,
        present_agent_ids: Set[int],
        uncovered_classes: Set[Tuple[str, str]],
    ) -> Dict[str, float]:
        """Performs efficient batch updates of Level 1 cognitive variables across the population."""
        if not is_school_open or not self.states:
            return {"mean_engagement": 0.75, "mean_stress": 20.0, "mean_confidence": 0.70}

        stresses = []
        engagements = []
        confidences = []

        for aid, cs in self.states.items():
            cs.last_activated_date = date_str

            # Stress recovery towards baseline (20.0)
            if cs.stress_proxy > 20.0:
                cs.stress_proxy = float(max(20.0, cs.stress_proxy - 2.5))

            # Engagement adjustment
            if cs.role == "student":
                if aid in present_agent_ids:
                    cs.engagement = float(min(1.0, cs.engagement + 0.005))
                else:
                    cs.engagement = float(max(0.3, cs.engagement - 0.02))

            # Check if student's class experienced uncovered periods
            # Penalty to academic confidence and engagement
            if cs.role == "student":
                cls = self.agent_class.get(aid)
                if cls:
                    g, s = cls
                    if (g, s) in uncovered_classes or (g.replace(" ", ""), s) in uncovered_classes:
                        cs.academic_confidence = float(max(0.2, cs.academic_confidence - 0.03))
                        cs.stress_proxy = float(min(100.0, cs.stress_proxy + 4.0))

            stresses.append(cs.stress_proxy)
            engagements.append(cs.engagement)
            confidences.append(cs.academic_confidence)

        return {
            "mean_engagement": round(float(np.mean(engagements)), 3),
            "mean_stress": round(float(np.mean(stresses)), 1),
            "mean_confidence": round(float(np.mean(confidences)), 3),
            "total_agents": len(self.states),
            "active_goals_count": len([g for g in self.goals.values() if g.status == GoalStatus.ACTIVE]),
        }

    def get_agent_summary(self, agent_id: int) -> Dict[str, Any]:
        """Provides an inspectable summary of an agent's cognitive state."""
        cs = self.states.get(agent_id)
        if not cs:
            return {}

        active_goal = self.get_active_goal(agent_id)
        mems = self.retrieve_memories(agent_id, limit=6)
        rels = [r.to_dict() for r in self.relationships.get(agent_id, {}).values()]

        return {
            "cognitive_state": cs.to_dict(),
            "active_goal": active_goal.to_dict() if active_goal else None,
            "recent_memories": [m.to_dict() for m in mems],
            "relationships": rels[:8],
        }
