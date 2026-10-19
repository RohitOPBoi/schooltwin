"""Focused Reproduction and Verification Tests for Codebase Audit & Repairs.

Reproduces:
1. Ollama reasoner crash on state=None / Principal reasoning.
2. Route number parsing and bus breakdown formatting (string '3', 'BUS-R03').
3. Teacher resignation parameter resolution (tname when params={'name': '...'}).
4. Scenario validation with canonical 'teacher_resignation_notice' in EVENT_CATALOG.
5. O(1) class lookup in CognitivePopulationManager.
"""
import unittest

from schooltwin.agent_decision import ActionValidator, SUPPORTED_ACTIONS
from schooltwin.causal_handlers import CausalHandlerRegistry
from schooltwin.causal import CausalAuditTrail, EventRecord
from schooltwin.cognitive import CognitiveState
from schooltwin.cognitive_manager import CognitivePopulationManager
from schooltwin.decide import Principal
from schooltwin.ledger import FinancialLedger
from schooltwin.learning import LearningModel
from schooltwin.ollama_reasoner import OllamaReasoner
from schooltwin.schema import EVENT_CATALOG, validate_scenario
from schooltwin.story import Story
from schooltwin.transport_maintenance import TransportMaintenanceManager


class TestAuditBugReproduction(unittest.TestCase):

    def test_reproduce_ollama_reasoner_none_state(self):
        """Defect 1: reason_agent_decision should not crash when state is None or for Principal."""
        reasoner = OllamaReasoner(enabled=True)
        # Previously crashed with AttributeError: 'NoneType' object has no attribute 'stress_proxy'
        dec = reasoner.reason_agent_decision(
            agent_id=0,
            role="principal",
            state=None,
            active_goal=None,
            recent_memories=[],
            date_str="2026-01-15",
            trigger_context="Alert: heat_utility_pressure",
        )
        self.assertIsNotNone(dec)
        self.assertEqual(dec.agent_role, "principal")

    def test_reproduce_route_number_robustness(self):
        """Defect 2: String route numbers like '3' or 'BUS-R03' must not crash format strings or int conversion."""
        audit = CausalAuditTrail()
        ledger = FinancialLedger()
        learning = LearningModel()
        transport = TransportMaintenanceManager(12)
        registry = CausalHandlerRegistry(audit, ledger, learning, transport)

        # String '3'
        ev1 = EventRecord(
            event_id="EV-BUS-STR",
            event_type="bus_breakdown",
            effective_date="2026-02-10",
            params={"route_number": "3", "repair_cost_inr": 12000},
        )
        res1 = registry.handle_bus_breakdown(ev1, "2026-02-10")
        self.assertEqual(res1["route_number"], 3)

        # String 'BUS-R05'
        ev2 = EventRecord(
            event_id="EV-BUS-CODE",
            event_type="bus_breakdown",
            effective_date="2026-02-10",
            params={"route_number": "BUS-R05", "repair_cost_inr": 12000},
        )
        res2 = registry.handle_bus_breakdown(ev2, "2026-02-10")
        self.assertEqual(res2["route_number"], 5)

    def test_reproduce_teacher_resignation_notice_in_schema(self):
        """Defect 4: validate_scenario must accept 'teacher_resignation_notice' as a valid event type."""
        self.assertIn("teacher_resignation_notice", EVENT_CATALOG)
        scen_data = {
            "name": "resignation_scenario",
            "events": [
                {
                    "type": "teacher_resignation_notice",
                    "date": "2026-02-10",
                    "severity": "medium",
                    "params": {"name": "Ritu Kapoor"},
                }
            ],
        }
        is_valid, errors = validate_scenario(scen_data)
        self.assertTrue(is_valid, f"Validation failed with errors: {errors}")

    def test_teacher_resignation_name_resolution(self):
        """Defect 3: Resignation handler and engine departure must resolve name when params={'name': '...'}."""
        audit = CausalAuditTrail()
        ledger = FinancialLedger()
        learning = LearningModel()
        transport = TransportMaintenanceManager(12)
        registry = CausalHandlerRegistry(audit, ledger, learning, transport)

        ev = EventRecord(
            event_id="EV-RESIGN-POOJA",
            event_type="teacher_resignation_notice",
            effective_date="2026-02-01",
            params={"name": "Pooja Sharma", "effective_date": "2026-02-15"},
        )
        info = registry.handle_teacher_resignation(ev, "2026-02-01")
        self.assertEqual(info["teacher_name"], "Pooja Sharma")
        self.assertIn("Pooja Sharma", registry.active_resignations)

        class MockTeacher:
            def __init__(self, name):
                self.name = name
                self.exit_date = None

        teachers = [MockTeacher("Pooja Sharma"), MockTeacher("Ritu Kapoor")]
        departed = registry.evaluate_resignation_departure("Pooja Sharma", "2026-02-15", teachers)
        self.assertTrue(departed)
        self.assertEqual(teachers[0].exit_date, "2026-02-15")
        self.assertIsNone(teachers[1].exit_date)

    def test_cognitive_population_agent_class_o1_lookup(self):
        """Defect 5: CognitivePopulationManager must provide O(1) agent_class lookup without iterating rosters."""
        import numpy as np
        from schooltwin.agents import create_population
        from schooltwin.world import World
        from schooltwin.engine import read_yaml
        mgr = CognitivePopulationManager()
        story = Story()
        world = World(read_yaml("map"), story.rooms())
        rng = np.random.default_rng(42)
        agents = create_population(story, world, read_yaml("behavior"), rng)
        mgr.initialize_population(agents, story)

        self.assertGreater(len(mgr.agent_class), 1000)
        # Verify student 1 has matching class in agent_class
        stu1 = next(a for a in agents if a.role == "student")
        cls = mgr.agent_class.get(stu1.id)
        self.assertIsNotNone(cls)
        self.assertEqual(cls, (stu1.grade, stu1.section))

    def test_serve_docs_routing(self):
        """Defect 7: Local server must route /docs to docs/index.html without 404."""
        import urllib.request
        try:
            resp = urllib.request.urlopen("http://127.0.0.1:8765/docs", timeout=2.0)
            self.assertEqual(resp.status, 200)
            body = resp.read()
            self.assertIn(b"SchoolTwin", body)
        except urllib.error.URLError:
            self.skipTest("Local server not running on port 8765")


if __name__ == "__main__":
    unittest.main()
