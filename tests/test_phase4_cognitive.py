"""Comprehensive Phase 4 Test Suite for Cognitive State, Lightweight Agents,
Persistent Memory, Sparse Relationships, and Optional Local LLM Reasoning.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from schooltwin.agent_decision import (
    ActionValidator,
    ApprovalTier,
    RuleBasedReasoner,
    SUPPORTED_ACTIONS,
)
from schooltwin.cognitive import (
    AgentDecision,
    AgentGoal,
    AgentMemory,
    AgentRelationship,
    CognitiveState,
    EpistemicStatus,
    GoalStatus,
    RelationshipType,
)
from schooltwin.cognitive_manager import CognitivePopulationManager
from schooltwin.decide import Principal
from schooltwin.engine import Engine
from schooltwin.ollama_reasoner import (
    compute_request_hash,
    OllamaReasoner,
)


class MockAgent:
    def __init__(self, aid: int, role: str, sid: str, grade: str = "Class 8", section: str = "A", route: str = "BUS-R03", subrole: str = ""):
        self.id = aid
        self.role = role
        self.sid = sid
        self.grade = grade
        self.section = section
        self.route = route
        self.subrole = subrole
        self.acad = 72.0
        self.disc_risk = 0.15
        self.mood = 65.0
        self.friends = []


class TestPhase4CognitiveArchitecture(unittest.TestCase):
    def setUp(self):
        self.manager = CognitivePopulationManager(seed=20261014)
        # Create mock cohort: 20 students, 3 teachers, 1 principal
        self.mock_agents = []
        for i in range(1, 21):
            sec = "A" if i <= 10 else "B"
            a = MockAgent(i, "student", f"STU-{i:04d}", grade="Class 8", section=sec, route="BUS-R03" if i % 2 == 0 else "BUS-R05")
            if i == 2:
                a.friends = [3, 4]
            self.mock_agents.append(a)

        self.mock_agents.append(MockAgent(21, "teacher", "STF-001", subrole="Science"))
        self.mock_agents.append(MockAgent(22, "teacher", "STF-002", subrole="Math"))
        self.mock_agents.append(MockAgent(23, "principal", "STF-000", subrole="principal"))

        self.manager.initialize_population(self.mock_agents)


    def test_level1_individual_state_initialization(self):
        self.assertEqual(len(self.manager.states), 23)

        # Check student state
        cs_stu = self.manager.states[1]
        self.assertEqual(cs_stu.role, "student")
        self.assertTrue(0.0 <= cs_stu.engagement <= 1.0)
        self.assertTrue(0.0 <= cs_stu.academic_confidence <= 1.0)
        self.assertTrue(0.0 <= cs_stu.stress_proxy <= 100.0)
        self.assertIsNotNone(cs_stu.current_goal_id)

        # Check teacher state
        cs_tea = self.manager.states[21]
        self.assertEqual(cs_tea.role, "teacher")
        self.assertIsNotNone(cs_tea.current_goal_id)

        # Check principal state
        cs_prin = self.manager.states[23]
        self.assertEqual(cs_prin.role, "principal")
        self.assertIn("MGMT", cs_prin.current_goal_id)


    def test_sparse_relationship_graph(self):
        # Verify student 1 has relationships within Section A
        rels_1 = self.manager.relationships[1]
        self.assertTrue(len(rels_1) > 0)
        self.assertLessEqual(len(rels_1), 10, "Relationships must remain sparse, not all-to-all")
        self.assertTrue(all(r.relation_type in (RelationshipType.CLASSMATE, RelationshipType.CLOSE_FRIEND) for r in rels_1.values()))

        # Verify close friends link for student 2
        rels_2 = self.manager.relationships[2]
        self.assertIn(3, rels_2)
        self.assertEqual(rels_2[3].relation_type, RelationshipType.CLOSE_FRIEND)
        self.assertEqual(rels_2[3].affinity, 0.88)

        # Verify staff coworker links
        rels_prin = self.manager.relationships[23]
        self.assertTrue(any(r.relation_type == RelationshipType.COWORKER for r in rels_prin.values()))


    def test_epistemic_memory_and_bounded_eviction(self):
        aid = 1
        # Add 15 memories with varying importances (limit is 12)
        for i in range(1, 16):
            mem = AgentMemory(
                memory_id=f"MEM-{aid}-{i:02d}",
                agent_id=aid,
                source_event_id=f"EV-{i:02d}",
                simulated_date="2026-01-10",
                memory_type="routine",
                summary=f"Routine memory {i}",
                importance=0.1 * (i % 5 + 1), # values 0.1 to 0.5
                epistemic_status=EpistemicStatus.EYEWITNESS_ACCOUNT,
            )
            self.manager.add_memory(mem)

        # Check bounded retention limit
        mems = self.manager.memories[aid]
        self.assertEqual(len(mems), self.manager.MAX_MEMORIES_PER_AGENT)

        # Add a high-importance memory (0.95)
        critical_mem = AgentMemory(
            memory_id=f"MEM-{aid}-CRITICAL",
            agent_id=aid,
            source_event_id="EV-CRITICAL",
            simulated_date="2026-01-15",
            memory_type="serious_student_fight",
            summary="Directly witnessed serious physical altercation on playground.",
            importance=0.95,
            epistemic_status=EpistemicStatus.CONFIRMED_FACT,
        )
        self.manager.add_memory(critical_mem)

        # Verify high-importance memory is preserved and retrieved first
        top_mems = self.manager.retrieve_memories(aid, limit=3)
        self.assertEqual(top_mems[0].memory_id, f"MEM-{aid}-CRITICAL")
        self.assertEqual(top_mems[0].epistemic_status, EpistemicStatus.CONFIRMED_FACT)


    def test_event_perception_propagation(self):
        # Trigger altercation involving students 1 and 2
        counts = self.manager.propagate_event_perception(
            event_id="EV-FIGHT-DAY07",
            event_type="serious_student_fight",
            date_str="2026-01-07",
            primary_agent_ids=[1, 2],
            location="playground",
            details="Three-way altercation near goalposts",
        )

        self.assertEqual(counts["fact"], 2, "Both primary participants must receive CONFIRMED_FACT")
        self.assertGreater(counts["witness"], 0, "Close friends must receive EYEWITNESS_ACCOUNT")
        self.assertGreater(counts["hearsay"], 0, "Classmates must receive UNSUBSTANTIATED_HEARSAY")

        # Verify participant memory
        mems_1 = self.manager.retrieve_memories(1, query_type="serious_student_fight")
        self.assertEqual(len(mems_1), 1)
        self.assertEqual(mems_1[0].epistemic_status, EpistemicStatus.CONFIRMED_FACT)
        self.assertEqual(mems_1[0].importance, 0.92)

        # Verify friend memory (student 3 was a friend of student 2)
        mems_3 = self.manager.retrieve_memories(3, query_type="serious_student_fight")
        self.assertEqual(len(mems_3), 1)
        self.assertEqual(mems_3[0].epistemic_status, EpistemicStatus.EYEWITNESS_ACCOUNT)


    def test_action_validation_and_approval_tiers(self):
        # 1. Valid student action
        valid, errs, tier = ActionValidator.validate_action(
            agent_id=1,
            agent_role="student",
            action_name="seek_academic_help",
            params={"subject": "Math", "target_teacher_or_peer": "Teacher"},
        )
        self.assertTrue(valid)
        self.assertEqual(len(errs), 0)
        self.assertEqual(tier, ApprovalTier.LOW_IMPACT)

        # 2. Unauthorized action (student trying to dispatch bus backup)
        valid_bad, errs_bad, _ = ActionValidator.validate_action(
            agent_id=1,
            agent_role="student",
            action_name="dispatch_bus_backup",
            params={"route_number": 3, "backup_bus_id": "BUS-01"},
        )
        self.assertFalse(valid_bad)
        self.assertTrue(any("not authorized" in e for e in errs_bad))

        # 3. Missing required parameters
        valid_missing, errs_missing, _ = ActionValidator.validate_action(
            agent_id=1,
            agent_role="student",
            action_name="seek_academic_help",
            params={"subject": "Math"}, # missing target_teacher_or_peer
        )
        self.assertFalse(valid_missing)
        self.assertTrue(any("Missing required parameter" in e for e in errs_missing))

        # 4. Unknown / Hallucinated action
        valid_unknown, errs_unknown, tier_unknown = ActionValidator.validate_action(
            agent_id=1,
            agent_role="student",
            action_name="hack_attendance_database",
            params={},
        )
        self.assertFalse(valid_unknown)
        self.assertEqual(tier_unknown, ApprovalTier.PROHIBITED)


    def test_principal_4tier_authorization(self):
        class MockStory:
            def __init__(self):
                self.decisions = []
                self.alerts = []

        prin = Principal(MockStory(), autonomy="low_risk_auto")

        # 1. Low impact alert -> auto approved
        alert_bus = {"rule_code": "bus_breakdown", "date": "2026-01-15", "evidence": {"route": 3}}
        dec_bus = prin.propose(alert_bus, {"attendance_rate": 0.94})
        self.assertEqual(dec_bus["approval_tier"], ApprovalTier.LOW_IMPACT.value)
        self.assertEqual(dec_bus["status"], "implemented_audited")

        # 2. High impact alert (fee increase) -> proposed_awaiting_approval
        alert_fee = {"rule_code": "fee_policy_revision", "date": "2026-01-10", "evidence": {"delta_pct": 10.0}}
        dec_fee = prin.propose(alert_fee, {"cash_inr": 3500000})
        self.assertEqual(dec_fee["approval_tier"], ApprovalTier.HIGH_IMPACT.value)
        self.assertEqual(dec_fee["status"], "proposed_awaiting_approval")


    def test_ollama_circuit_breaker_and_rule_fallback(self):
        # Initialize reasoner with enabled=True but pointing to unreachable mock port
        reasoner = OllamaReasoner(enabled=True, timeout_seconds=0.1)

        # Force failure count to 3
        reasoner.record_failure()
        reasoner.record_failure()
        reasoner.record_failure()

        # Circuit breaker should now be OPEN
        self.assertFalse(reasoner.is_available(), "Circuit breaker must be open after 3 consecutive failures")

        # Calling reason_agent_decision while circuit is open must transparently fall back
        cs = self.manager.states[1]
        dec = reasoner.reason_agent_decision(
            agent_id=1,
            role="student",
            state=cs,
            active_goal=self.manager.get_active_goal(1),
            recent_memories=[],
            date_str="2026-01-10",
            trigger_context="Routine class period",
        )
        self.assertEqual(dec.provenance, "fallback_rule")
        self.assertIn(dec.action_name, SUPPORTED_ACTIONS)


    def test_decision_trace_replay(self):
        reasoner = OllamaReasoner(enabled=False) # Offline mode

        cs = self.manager.states[1]
        dec1 = reasoner.reason_agent_decision(
            agent_id=1,
            role="student",
            state=cs,
            active_goal=self.manager.get_active_goal(1),
            recent_memories=[],
            date_str="2026-01-10",
            trigger_context="Exam prep period",
        )
        self.assertEqual(dec1.provenance, "fallback_rule")

        # Export trace
        trace = reasoner.export_trace()
        self.assertTrue(len(trace) > 0)

        # Second reasoner loaded with trace
        replay_reasoner = OllamaReasoner(enabled=True)
        replay_reasoner.load_trace(trace)

        dec2 = replay_reasoner.reason_agent_decision(
            agent_id=1,
            role="student",
            state=cs,
            active_goal=self.manager.get_active_goal(1),
            recent_memories=[],
            date_str="2026-01-10",
            trigger_context="Exam prep period",
        )
        self.assertEqual(dec2.provenance, "replayed_trace")
        self.assertEqual(dec1.action_name, dec2.action_name)
        self.assertEqual(replay_reasoner.replayed_calls, 1)


    @patch("urllib.request.urlopen")
    def test_ollama_mocked_structured_decision(self, mock_urlopen):
        # Mock valid Ollama JSON response
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_json_content = json.dumps({
            "action_name": "seek_academic_help",
            "parameters": {"subject": "Mathematics", "target_teacher_or_peer": "Teacher"},
            "rationale": "Requesting remedial help after difficulty on algebra problem set.",
            "uncertainty": 0.15,
        })
        mock_resp.read.return_value = json.dumps({"response": mock_json_content}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        reasoner = OllamaReasoner(enabled=True, timeout_seconds=1.0)
        # Patch is_ollama_available to True
        with patch("schooltwin.ollama_reasoner.is_ollama_available", return_value=True):
            cs = self.manager.states[1]
            dec = reasoner.reason_agent_decision(
                agent_id=1,
                role="student",
                state=cs,
                active_goal=self.manager.get_active_goal(1),
                recent_memories=[],
                date_str="2026-01-12",
                trigger_context="Algebra class confusion",
            )
            self.assertEqual(dec.provenance, f"ollama_{reasoner.model}")
            self.assertEqual(dec.action_name, "seek_academic_help")
            self.assertEqual(dec.approval_tier, ApprovalTier.LOW_IMPACT)


    def test_simulation_integration_with_cognitive_population(self):
        ov = {
            "name": "test_phase4_sim",
            "seed": 20261014,
            "end_day": 13,
            "mode": "generate",
            "events": {
                "use_story_events": True,
                "disable": [],
                "add": [
                    {
                        "type": "serious_student_fight",
                        "day": 12,
                        "date": "2026-01-12",
                        "student_ids": ["STU-0012", "STU-0015", "STU-0021"],
                        "location": "playground",
                        "severity": "high",
                    }
                ],
                "random": {"per_month": 0, "types": []},
            },
            "policies": {},
            "patches": [],
        }

        eng = Engine(ov)
        eng.run()

        # Verify cognitive population exists and has state
        self.assertEqual(len(eng.cognitive.states), len(eng.agents))
        self.assertTrue(len(eng.days) >= 3)

        # Verify cognitive daily metrics in day result
        d1 = eng.days[1]
        self.assertIn("cognitive", d1)
        self.assertIn("mean_engagement", d1["cognitive"])
        self.assertIn("mean_stress", d1["cognitive"])

        # Verify participant received memory
        p_aid = eng.cognitive.agent_sid_to_id["STU-0012"]
        mems = eng.cognitive.retrieve_memories(p_aid)
        self.assertTrue(any(m.epistemic_status == EpistemicStatus.CONFIRMED_FACT for m in mems))


    def test_cognitive_determinism(self):
        ov1 = {
            "name": "det_cog_1",
            "seed": 777123,
            "end_day": 3,
            "mode": "generate",
            "events": {"add": [], "disable": []},
            "policies": {},
            "patches": [],
        }
        ov2 = {
            "name": "det_cog_2",
            "seed": 777123,
            "end_day": 3,
            "mode": "generate",
            "events": {"add": [], "disable": []},
            "policies": {},
            "patches": [],
        }

        eng1 = Engine(ov1)
        eng2 = Engine(ov2)
        eng1.run()
        eng2.run()

        # Engagement and stress bit-for-bit identical
        d_end1 = eng1.days[-1]["cognitive"]
        d_end2 = eng2.days[-1]["cognitive"]
        self.assertEqual(d_end1["mean_engagement"], d_end2["mean_engagement"])
        self.assertEqual(d_end1["mean_stress"], d_end2["mean_stress"])

        # Agent state samples identical
        cs1 = eng1.cognitive.states[5]
        cs2 = eng2.cognitive.states[5]
        self.assertEqual(cs1.engagement, cs2.engagement)
        self.assertEqual(cs1.stress_proxy, cs2.stress_proxy)


    def test_live_ollama_integration_if_service_online(self):
        from schooltwin.nlp import is_ollama_available
        if not is_ollama_available():
            self.skipTest("Local Ollama service not running; skipping live network check")

        reasoner = OllamaReasoner(model="qwen3.5:4b", enabled=True, timeout_seconds=8.0)
        cs = self.manager.states[1]
        dec = reasoner.reason_agent_decision(
            agent_id=1,
            role="student",
            state=cs,
            active_goal=self.manager.get_active_goal(1),
            recent_memories=[],
            date_str="2026-01-15",
            trigger_context="Choosing after-school academic activity",
        )

        self.assertIsNotNone(dec)
        self.assertIn(dec.action_name, SUPPORTED_ACTIONS)
        self.assertIn(dec.provenance, ("ollama_qwen3.5:4b", "fallback_rule"))
        self.assertTrue(len(dec.rationale) > 0)


if __name__ == "__main__":
    unittest.main()

