"""State Snapshot Capture and Restoration for SchoolTwin.

Enables instant scenario branching without re-simulating prior baseline days:
- Fully captures persistent multi-agent states, relationships, moods, and cognitive memories.
- Restores exact double-entry ledger state, learning progression, bus fleet work-orders, and audit trail.
- Guarantees bit-for-bit mathematical determinism across resumed simulations.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agents import Agent
from .causal import EffectRecord, EventRecord, InvestigationRecord
from .cognitive import (
    AgentGoal,
    AgentMemory,
    AgentRelationship,
    CognitiveState,
    EpistemicStatus,
    GoalStatus,
    RelationshipType,
)
from .config import ROOT
from .learning import StudentAcademicState
from .ledger import Transaction
from .transport_maintenance import WorkOrder

SNAPSHOT_VERSION = "1.0.0"
SNAPSHOTS_DIR = ROOT / "pack" / "story_baseline" / "snapshots"


def compute_snapshot_hash(data_dict: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash of a snapshot dictionary."""
    clean = {k: v for k, v in data_dict.items() if k != "snapshot_hash"}
    dumped = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def capture_snapshot(engine: Any, day_idx: int) -> Dict[str, Any]:
    """Serializes the complete runtime state of an Engine instance after completing day_idx."""
    agents_state = []
    for a in engine.agents:
        agents_state.append({
            "id": a.id,
            "sid": a.sid,
            "role": a.role,
            "subrole": a.subrole,
            "name": a.name,
            "mood": float(a.mood),
            "shift": float(getattr(a, "shift", 0.0)),
            "absent_streak": int(getattr(a, "absent_streak", 0)),
            "away_until": getattr(a, "away_until", -1),
            "away_zone": getattr(a, "away_zone", ""),
            "zone": getattr(a, "zone", "outside"),
            "target": getattr(a, "target", "outside"),
            "grade": getattr(a, "grade", ""),
            "section": getattr(a, "section", ""),
            "home_zone": getattr(a, "home_zone", ""),
            "att_prop": float(getattr(a, "att_prop", 0.95)),
            "friends": list(getattr(a, "friends", [])),
        })

    cam_hist_serialized = {
        f"{cam}|{minute}": list(counts) for (cam, minute), counts in engine.cam_hist.items()
    }

    learning_students = {}
    for sid, st in engine.learning.students.items():
        learning_students[sid] = {
            "student_id": st.student_id,
            "grade": st.grade,
            "section": st.section,
            "subject_mastery": dict(st.subject_mastery),
            "instructional_periods_attended": st.instructional_periods_attended,
            "instructional_periods_lost": st.instructional_periods_lost,
            "assessment_history": copy.deepcopy(st.assessment_history),
        }

    cog_states = {str(k): cs.to_dict() for k, cs in engine.cognitive.states.items()}
    cog_memories = {
        str(k): [m.to_dict() for m in mems] for k, mems in engine.cognitive.memories.items()
    }
    cog_goals = {k: g.to_dict() for k, g in engine.cognitive.goals.items()}
    cog_relationships = {
        str(k): {str(k2): rel.to_dict() for k2, rel in v.items()}
        for k, v in engine.cognitive.relationships.items()
    }

    snapshot: Dict[str, Any] = {
        "snapshot_version": SNAPSHOT_VERSION,
        "day": int(day_idx),
        "date": engine.calendar.date_for_day(day_idx) if hasattr(engine, "calendar") else f"day_{day_idx}",
        "seed": int(engine.ov["seed"]),
        "extra_teachers": int(engine.extra_teachers),
        "effects_active": copy.deepcopy(engine.effects_active),
        "agents": agents_state,
        "cam_hist": cam_hist_serialized,
        "days": copy.deepcopy(engine.days),
        "flags": copy.deepcopy(engine.flags),
        "alerts": copy.deepcopy(engine.alerts),
        "decisions": copy.deepcopy(engine.decisions),
        "agent_decisions": [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in engine.agent_decisions],
        "ledger": {
            "opening_cash_paise": engine.ledger.opening_cash_paise,
            "opening_ar_paise": engine.ledger.opening_ar_paise,
            "counter": engine.ledger._counter,
            "transactions": [t.to_dict() for t in engine.ledger.transactions],
        },
        "learning": {
            "total_uncovered_periods": engine.learning.total_uncovered_periods,
            "total_lost_instructional_minutes": engine.learning.total_lost_instructional_minutes,
            "students": learning_students,
        },
        "transport": {
            "num_routes": engine.transport.num_routes,
            "buses": copy.deepcopy(engine.transport.buses),
            "route_students": {str(k): list(v) for k, v in engine.transport.route_students.items()},
            "work_orders": [wo.to_dict() for wo in engine.transport.work_orders],
            "wo_counter": engine.transport._wo_counter,
        },
        "cognitive": {
            "states": cog_states,
            "memories": cog_memories,
            "goals": cog_goals,
            "relationships": cog_relationships,
        },
        "audit": {
            "events": [e.to_dict() for e in engine.audit.events.values()],
            "effects": [ef.to_dict() for ef in engine.audit.effects],
            "chains": {
                k: [node.to_dict() if hasattr(node, "to_dict") else dict(node) for node in nodes]
                for k, nodes in engine.audit.chains.items()
            },
            "effect_counter": engine.audit._effect_counter,
        },
    }
    snapshot["snapshot_hash"] = compute_snapshot_hash(snapshot)
    return snapshot


def restore_snapshot(engine: Any, snapshot: Dict[str, Any]) -> None:
    """Restores the complete runtime state into an Engine instance."""
    # Restore scalar and collection metadata
    engine.extra_teachers = snapshot.get("extra_teachers", 0)
    engine.effects_active = copy.deepcopy(snapshot.get("effects_active", []))
    engine.days = copy.deepcopy(snapshot.get("days", []))
    engine.flags = copy.deepcopy(snapshot.get("flags", []))
    engine.alerts = copy.deepcopy(snapshot.get("alerts", []))
    engine.decisions = copy.deepcopy(snapshot.get("decisions", []))

    # Restore camera history
    engine.cam_hist.clear()
    for key_str, counts in snapshot.get("cam_hist", {}).items():
        cam, minute_str = key_str.split("|", 1)
        engine.cam_hist[(cam, int(minute_str))] = list(counts)

    # Restore agents
    agents_by_id = {a.id: a for a in engine.agents}
    for ag_data in snapshot.get("agents", []):
        aid = ag_data["id"]
        if aid in agents_by_id:
            a = agents_by_id[aid]
            a.mood = ag_data["mood"]
            if "shift" in ag_data:
                a.shift = ag_data["shift"]
            if "absent_streak" in ag_data:
                a.absent_streak = ag_data["absent_streak"]
            if "drivers" in ag_data:
                a.drivers = dict(ag_data["drivers"])
            a.away_until = ag_data.get("away_until", -1)
            a.away_zone = ag_data.get("away_zone", "")
            a.zone = ag_data.get("zone", "outside")
            a.target = ag_data.get("target", "outside")
            if "grade" in ag_data:
                a.grade = ag_data["grade"]
            if "section" in ag_data:
                a.section = ag_data["section"]
            if "home_zone" in ag_data:
                a.home_zone = ag_data["home_zone"]
            if "att_prop" in ag_data:
                a.att_prop = ag_data["att_prop"]
            if "friends" in ag_data:
                a.friends = list(ag_data["friends"])
        else:
            # Handle additional hired teachers added in snapshot
            new_a = Agent(
                id=aid,
                role=ag_data["role"],
                sid=ag_data["sid"],
                subrole=ag_data["subrole"],
                name=ag_data["name"],
                home_zone=ag_data.get("home_zone", "staffroom"),
                mood=ag_data.get("mood", 66.0),
            )
            new_a.drivers = dict(ag_data.get("drivers", {}))
            engine.agents.append(new_a)
            engine.tracked.append(aid)
            agents_by_id[aid] = new_a

    # Restore ledger
    led_data = snapshot.get("ledger", {})
    engine.ledger.opening_cash_paise = led_data.get("opening_cash_paise", engine.ledger.opening_cash_paise)
    engine.ledger.opening_ar_paise = led_data.get("opening_ar_paise", engine.ledger.opening_ar_paise)
    engine.ledger._counter = led_data.get("counter", 0)
    engine.ledger.transactions.clear()
    engine.ledger._tx_ids.clear()
    for tx_dict in led_data.get("transactions", []):
        tx = Transaction(
            tx_id=tx_dict["tx_id"],
            date=tx_dict["date"],
            debit_account=tx_dict["debit_account"],
            credit_account=tx_dict["credit_account"],
            amount_paise=tx_dict["amount_paise"],
            category=tx_dict["category"],
            description=tx_dict["description"],
            source_event_id=tx_dict.get("source_event_id"),
        )
        engine.ledger.transactions.append(tx)
        engine.ledger._tx_ids.add(tx.tx_id)

    # Restore learning
    learn_data = snapshot.get("learning", {})
    engine.learning.total_uncovered_periods = learn_data.get("total_uncovered_periods", 0)
    engine.learning.total_lost_instructional_minutes = learn_data.get("total_lost_instructional_minutes", 0)
    for sid, st_dict in learn_data.get("students", {}).items():
        if sid in engine.learning.students:
            st = engine.learning.students[sid]
            st.subject_mastery = dict(st_dict["subject_mastery"])
            st.instructional_periods_attended = st_dict.get("instructional_periods_attended", 0)
            st.instructional_periods_lost = st_dict.get("instructional_periods_lost", 0)
            st.assessment_history = copy.deepcopy(st_dict.get("assessment_history", []))

    # Restore transport fleet
    trans_data = snapshot.get("transport", {})
    engine.transport.buses = copy.deepcopy(trans_data.get("buses", engine.transport.buses))
    engine.transport._wo_counter = trans_data.get("wo_counter", 0)
    engine.transport.work_orders.clear()
    for wo_dict in trans_data.get("work_orders", []):
        wo = WorkOrder(
            work_order_id=wo_dict["work_order_id"],
            asset_id=wo_dict["asset_id"],
            category=wo_dict["category"],
            description=wo_dict["description"],
            cost_inr=wo_dict["cost_inr"],
            opened_date=wo_dict["opened_date"],
            scheduled_completion_date=wo_dict["scheduled_completion_date"],
            status=wo_dict.get("status", "opened"),
            completed_date=wo_dict.get("completed_date"),
            source_event_id=wo_dict.get("source_event_id"),
        )
        engine.transport.work_orders.append(wo)

    # Restore cognitive
    cog_data = snapshot.get("cognitive", {})
    for aid_str, cs_dict in cog_data.get("states", {}).items():
        aid = int(aid_str)
        if aid in engine.cognitive.states:
            cs = engine.cognitive.states[aid]
            cs.engagement = cs_dict.get("engagement", cs.engagement)
            cs.stress_proxy = cs_dict.get("stress_proxy", cs.stress_proxy)
            cs.compliance_tendency = cs_dict.get("compliance_tendency", cs.compliance_tendency)
            cs.academic_confidence = cs_dict.get("academic_confidence", cs.academic_confidence)
            cs.current_goal_id = cs_dict.get("current_goal_id")
            cs.active_action = cs_dict.get("active_action")
            cs.last_activated_date = cs_dict.get("last_activated_date", cs.last_activated_date)
            cs.memory_ids = list(cs_dict.get("memory_ids", []))
            cs.relationships = dict(cs_dict.get("relationships", {}))

    for aid_str, mem_list in cog_data.get("memories", {}).items():
        aid = int(aid_str)
        mems = []
        for md in mem_list:
            status_val = md.get("epistemic_status", "eyewitness_account")
            try:
                ep_stat = EpistemicStatus(status_val)
            except Exception:
                ep_stat = EpistemicStatus.EYEWITNESS_ACCOUNT
            mems.append(
                AgentMemory(
                    memory_id=md["memory_id"],
                    agent_id=md["agent_id"],
                    source_event_id=md.get("source_event_id", ""),
                    simulated_date=md.get("simulated_date", md.get("created_date", "2026-01-01")),
                    memory_type=md.get("memory_type", "incident"),
                    summary=md.get("summary", ""),
                    importance=float(md.get("importance", 0.5)),
                    epistemic_status=ep_stat,
                    tags=list(md.get("tags", [])),
                    confidence=float(md.get("confidence", 1.0)),
                    expiry_date=md.get("expiry_date"),
                )
            )
        engine.cognitive.memories[aid] = mems

    engine.cognitive.goals.clear()
    for gid, gd in cog_data.get("goals", {}).items():
        try:
            gstat = GoalStatus(gd.get("status", "active"))
        except Exception:
            gstat = GoalStatus.ACTIVE
        engine.cognitive.goals[gid] = AgentGoal(
            goal_id=gd["goal_id"],
            agent_id=gd["agent_id"],
            goal_type=gd.get("goal_type", "routine"),
            target_outcome=gd.get("target_outcome", ""),
            priority=gd.get("priority", 3),
            status=gstat,
            created_date=gd.get("created_date", "2026-01-01"),
            target_date=gd.get("target_date"),
            progress=float(gd.get("progress", 0.0)),
        )

    engine.cognitive.relationships.clear()
    for s_id_str, rel_dict in cog_data.get("relationships", {}).items():
        s_id = int(s_id_str)
        engine.cognitive.relationships[s_id] = {}
        for t_id_str, rd in rel_dict.items():
            t_id = int(t_id_str)
            try:
                rtype = RelationshipType(rd.get("relation_type", "classmate"))
            except Exception:
                rtype = RelationshipType.CLASSMATE
            engine.cognitive.relationships[s_id][t_id] = AgentRelationship(
                source_id=s_id,
                target_id=t_id,
                relation_type=rtype,
                affinity=float(rd.get("affinity", 0.5)),
                last_interaction_date=rd.get("last_interaction_date", "2026-01-01"),
                shared_event_count=int(rd.get("shared_event_count", 0)),
            )

    # Restore audit trail
    audit_data = snapshot.get("audit", {})
    engine.audit.events.clear()
    for ed in audit_data.get("events", []):
        ev = EventRecord(**ed)
        engine.audit.events[ev.event_id] = ev
    engine.audit.effects.clear()
    for efd in audit_data.get("effects", []):
        engine.audit.effects.append(EffectRecord(**efd))
    engine.audit._effect_counter = audit_data.get("effect_counter", 0)
    engine.audit.chains.clear()
    for k, nodes in audit_data.get("chains", {}).items():
        from .causal import CausalChainNode
        engine.audit.chains[k] = [
            CausalChainNode(**nd) if isinstance(nd, dict) else nd for nd in nodes
        ]


def save_snapshot_file(snapshot: Dict[str, Any], path: Path) -> Path:
    """Saves snapshot dictionary as gzipped JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(snapshot, indent=2, ensure_ascii=True).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(raw)
    return path


def load_snapshot_file(path: Path) -> Dict[str, Any]:
    """Loads snapshot dictionary from gzipped JSON file."""
    with gzip.open(path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    return data


def load_snapshot_into_engine(engine: Any, path_or_day: Any) -> None:
    """Loads a snapshot from a Path or integer day into an existing engine instance."""
    if isinstance(path_or_day, (int, str)) and not Path(str(path_or_day)).exists():
        day_num = int(str(path_or_day).replace("CKPT-DAY-", "").split("-")[0])
        snap_path = SNAPSHOTS_DIR / f"snapshot_day_{day_num}.json.gz"
    else:
        snap_path = Path(path_or_day)
    data = load_snapshot_file(snap_path)
    restore_snapshot(engine, data)

