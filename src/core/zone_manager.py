"""
ArgusTraffic AI - Spatial Zone and Lane Geometry Manager
Enables polygonal geofencing, directional flow vectors, crosswalk zones,
and exclusion boxes for intelligent traffic rule evaluation.
"""

from dataclasses import dataclass, field
import json
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class FlowVector:
    dx: float  # Direction vector X
    dy: float  # Direction vector Y

    @property
    def angle_deg(self) -> float:
        """Returns direction in degrees [0, 360)."""
        angle = math.degrees(math.atan2(self.dy, self.dx))
        return (angle + 360) % 360

    @property
    def magnitude(self) -> float:
        return math.hypot(self.dx, self.dy)


@dataclass
class TrafficZone:
    zone_id: str
    name: str
    zone_type: str  # 'lane', 'crosswalk', 'no_stopping', 'danger'
    polygon: List[Tuple[float, float]]  # List of (x, y) vertices
    expected_flow: Optional[FlowVector] = None  # Expected travel vector if lane
    speed_limit_px: float = 35.0

    def contains_point(self, pt: Tuple[float, float]) -> bool:
        """Determines if a point (x, y) lies inside this polygon."""
        if len(self.polygon) < 3:
            return False
        pts = np.array(self.polygon, dtype=np.int32)
        return cv2.pointPolygonTest(pts, (float(pt[0]), float(pt[1])), False) >= 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "zone_type": self.zone_type,
            "polygon": self.polygon,
            "expected_flow": (
                {"dx": self.expected_flow.dx, "dy": self.expected_flow.dy, "angle_deg": self.expected_flow.angle_deg}
                if self.expected_flow
                else None
            ),
            "speed_limit_px": self.speed_limit_px,
        }


class ZoneManager:
    """Manages geometric road zones, lane configurations, and flow rules."""

    def __init__(self):
        self.zones: Dict[str, TrafficZone] = {}

    def add_zone(self, zone: TrafficZone) -> None:
        self.zones[zone.zone_id] = zone

    def remove_zone(self, zone_id: str) -> bool:
        if zone_id in self.zones:
            del self.zones[zone_id]
            return True
        return False

    def get_zones_for_point(self, pt: Tuple[float, float]) -> List[TrafficZone]:
        """Finds all zones containing the specified coordinates."""
        return [zone for zone in self.zones.values() if zone.contains_point(pt)]

    def create_default_traffic_zones(self, frame_width: int = 1280, frame_height: int = 720) -> None:
        """Generates standard dual-lane highway and crosswalk geometry for default scenes."""
        w, h = frame_width, frame_height

        # Lane 1 (Downwards / Southbound flow)
        lane_south = TrafficZone(
            zone_id="lane_southbound",
            name="Southbound Lane",
            zone_type="lane",
            polygon=[
                (w * 0.15, 0),
                (w * 0.48, 0),
                (w * 0.48, h),
                (w * 0.15, h),
            ],
            expected_flow=FlowVector(dx=0.0, dy=1.0),  # Flow pointing down
        )

        # Lane 2 (Upwards / Northbound flow)
        lane_north = TrafficZone(
            zone_id="lane_northbound",
            name="Northbound Lane",
            zone_type="lane",
            polygon=[
                (w * 0.52, 0),
                (w * 0.85, 0),
                (w * 0.85, h),
                (w * 0.52, h),
            ],
            expected_flow=FlowVector(dx=0.0, dy=-1.0),  # Flow pointing up
        )

        # Central Crosswalk
        crosswalk = TrafficZone(
            zone_id="crosswalk_central",
            name="Mid-Block Crosswalk",
            zone_type="crosswalk",
            polygon=[
                (w * 0.10, h * 0.45),
                (w * 0.90, h * 0.45),
                (w * 0.90, h * 0.55),
                (w * 0.10, h * 0.55),
            ],
        )

        self.add_zone(lane_south)
        self.add_zone(lane_north)
        self.add_zone(crosswalk)

    def to_json(self) -> str:
        return json.dumps([z.to_dict() for z in self.zones.values()], indent=2)

    def load_from_json(self, json_str: str) -> None:
        data = json.loads(json_str)
        self.zones.clear()
        for item in data:
            flow = None
            if item.get("expected_flow"):
                flow = FlowVector(dx=item["expected_flow"]["dx"], dy=item["expected_flow"]["dy"])
            zone = TrafficZone(
                zone_id=item["zone_id"],
                name=item["name"],
                zone_type=item["zone_type"],
                polygon=[(float(p[0]), float(p[1])) for p in item["polygon"]],
                expected_flow=flow,
                speed_limit_px=item.get("speed_limit_px", 35.0),
            )
            self.add_zone(zone)
