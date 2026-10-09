"""The 2D campus: zones with a rectangle, a capacity and (sometimes) an aggregate counter."""
from dataclasses import dataclass, field

from .story import grade_short, room_id

CAMERA_COVERAGE = 0.95        # a counter sees about this share of the people in its zone


@dataclass
class Zone:
    id: str
    floor: int
    type: str
    x: float
    y: float
    w: float
    h: float
    capacity: int
    camera_id: str = ""
    measure: str = "occupancy"
    blind_spot: bool = False
    secrecy: float = 0.0
    label: str = ""
    grade: str = ""
    section: str = ""

    @property
    def camera(self):
        return CAMERA_COVERAGE if self.camera_id else 0.0

    def sample_point(self, rng):
        return (self.x + 0.5 + rng.random() * max(self.w - 1, 0.1),
                self.y + 0.5 + rng.random() * max(self.h - 1, 0.1))


class World:
    def __init__(self, map_cfg, rooms):
        """rooms = [((grade, section), max_roll), ...] from the story."""
        self.floors = {int(k): v for k, v in map_cfg["floors"].items()}
        self.zones = {}
        for z in map_cfg["zones"]:
            x, y, w, h = z["rect"]
            self.zones[z["id"]] = Zone(id=z["id"], floor=z["floor"], type=z["type"], x=x, y=y, w=w, h=h,
                                       capacity=z.get("capacity", 50), camera_id=z.get("camera_id", ""),
                                       measure=z.get("measure", "occupancy"), blind_spot=z.get("blind_spot", False),
                                       secrecy=z.get("secrecy", 0.0), label=z.get("label", z["id"]))
        row, cams = map_cfg["classroom_row"], map_cfg.get("classroom_cameras", {})
        by_floor = {f: [] for f in self.floors}
        floor_of = {str(g): f for f, gs in map_cfg["classroom_floors"].items() for g in gs}
        for (grade, section), n in rooms:
            by_floor[int(floor_of[grade_short(grade)])].append((grade, section, n))
        for f, items in by_floor.items():
            slot = (row["x1"] - row["x0"]) / max(len(items), 1)
            for i, (grade, section, n) in enumerate(items):
                zid = room_id(grade, section)
                self.zones[zid] = Zone(id=zid, floor=f, type="classroom", x=row["x0"] + i * slot, y=row["y"],
                                       w=slot - 0.5, h=row["h"], capacity=int(n * 1.15) + 2,
                                       camera_id=cams.get(zid, ""), measure="occupancy",
                                       label=f"{grade_short(grade)}{section}", grade=grade, section=section)
        self.order = list(self.zones)                       # stable zone index for packs
        self.index = {z: i for i, z in enumerate(self.order)}

    def corridor_of(self, floor):
        return self.zones[f"corridor_{floor}"]

    def ids_of(self, ztype):
        return [z.id for z in self.zones.values() if z.type == ztype]

    def blind_spot_ids(self):
        return self.ids_of("blind_spot")

    def camera_zones(self):
        return [z for z in self.zones.values() if z.camera_id]
