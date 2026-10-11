"""Transport Fleet and Campus Facility Maintenance Management for SchoolTwin.

Maintains explicit vehicle and facility work-orders, availability transitions,
route-to-student assignments, and deterministic repair timelines.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class WorkOrder:
    work_order_id: str
    asset_id: str
    category: str  # transport, hvac, plumbing, electrical, grounds
    description: str
    cost_inr: int
    opened_date: str
    scheduled_completion_date: str
    status: str = "opened"  # opened, in_progress, completed
    completed_date: Optional[str] = None
    source_event_id: Optional[str] = None

    def complete(self, completion_date: str) -> None:
        self.status = "completed"
        self.completed_date = completion_date

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TransportMaintenanceManager:
    """Manages the 12-bus transport fleet, route mappings, and maintenance work orders."""

    def __init__(self, num_routes: int = 12):
        self.num_routes = num_routes
        self.buses: Dict[str, Dict[str, Any]] = {
            f"BUS-{r:02d}": {
                "bus_id": f"BUS-{r:02d}",
                "route_number": r,
                "status": "available",
                "capacity": 55,
                "breakdown_count": 0,
            }
            for r in range(1, num_routes + 1)
        }
        self.route_to_bus: Dict[int, str] = {r: f"BUS-{r:02d}" for r in range(1, num_routes + 1)}
        self.route_students: Dict[int, Set[str]] = {r: set() for r in range(1, num_routes + 1)}
        self.work_orders: List[WorkOrder] = []
        self._wo_counter: int = 0

    def register_student_route(self, student_id: str, route_number: int) -> None:
        if route_number in self.route_students:
            self.route_students[route_number].add(student_id)

    def trigger_bus_breakdown(
        self,
        route_number: int,
        date_str: str,
        repair_days: int = 2,
        cost_inr: int = 14500,
        source_event_id: Optional[str] = None,
        backup_buses_available: int = 0
    ) -> Dict[str, Any]:
        """Processes bus breakdown on a specific route."""
        bus_id = self.route_to_bus.get(route_number, f"BUS-{route_number:02d}")
        if bus_id in self.buses:
            self.buses[bus_id]["status"] = "in_repair" if backup_buses_available > 0 else "broken_down"
            self.buses[bus_id]["breakdown_count"] += 1

        self._wo_counter += 1
        wo_id = f"WO-{date_str}-{self._wo_counter:04d}"
        comp_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=repair_days)).strftime("%Y-%m-%d")

        wo = WorkOrder(
            work_order_id=wo_id,
            asset_id=bus_id,
            category="transport",
            description=f"Route {route_number} ({bus_id}) mechanical repair and maintenance",
            cost_inr=cost_inr,
            opened_date=date_str,
            scheduled_completion_date=comp_date,
            status="in_progress",
            source_event_id=source_event_id,
        )
        self.work_orders.append(wo)

        affected_students = list(self.route_students.get(route_number, set()))
        return {
            "bus_id": bus_id,
            "route_number": route_number,
            "work_order_id": wo_id,
            "repair_cost_inr": cost_inr,
            "scheduled_completion_date": comp_date,
            "affected_students_count": len(affected_students),
            "affected_student_ids": affected_students,
            "standby_deployed": backup_buses_available > 0,
        }

    def trigger_facility_work_order(
        self,
        asset_id: str,
        category: str,
        description: str,
        date_str: str,
        cost_inr: int,
        duration_days: int = 1,
        source_event_id: Optional[str] = None
    ) -> WorkOrder:
        """Registers a facility maintenance work order (e.g. water motor, fan, circuit)."""
        self._wo_counter += 1
        wo_id = f"WO-{date_str}-{self._wo_counter:04d}"
        comp_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=duration_days)).strftime("%Y-%m-%d")

        wo = WorkOrder(
            work_order_id=wo_id,
            asset_id=asset_id,
            category=category,
            description=description,
            cost_inr=cost_inr,
            opened_date=date_str,
            scheduled_completion_date=comp_date,
            status="in_progress",
            source_event_id=source_event_id,
        )
        self.work_orders.append(wo)
        return wo

    def step_day(self, current_date_str: str) -> None:
        """Checks and completes scheduled maintenance work orders whose completion date has arrived."""
        for wo in self.work_orders:
            if wo.status != "completed" and current_date_str >= wo.scheduled_completion_date:
                wo.complete(current_date_str)
                if wo.category == "transport" and wo.asset_id in self.buses:
                    self.buses[wo.asset_id]["status"] = "available"

    def get_transport_metrics(self) -> Dict[str, Any]:
        total = len(self.buses)
        avail = sum(1 for b in self.buses.values() if b["status"] == "available")
        broken = sum(1 for b in self.buses.values() if b["status"] in ("broken_down", "in_repair"))
        total_maint_cost = sum(wo.cost_inr for wo in self.work_orders)
        return {
            "fleet_size": total,
            "buses_available": avail,
            "buses_out_of_service": broken,
            "fleet_availability_pct": round(avail / max(total, 1) * 100.0, 1),
            "total_maintenance_work_orders": len(self.work_orders),
            "total_maintenance_expenditure_inr": total_maint_cost,
        }
