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


from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.utils.paths import get_data_dir


class ZoneManager:
    """Manages geometric road zones, lane configurations, and flow rules per camera channel."""

    def __init__(self, data_dir: Optional[Union[str, Path]] = None):
        self.zones: Dict[str, TrafficZone] = {}
        self.camera_zones: Dict[str, Dict[str, TrafficZone]] = {}
        self.data_dir = Path(data_dir) if data_dir else (get_data_dir() / "zones")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def add_zone(self, zone: TrafficZone, camera_id: Optional[str] = None) -> None:
        self.zones[zone.zone_id] = zone
        if camera_id:
            if camera_id not in self.camera_zones:
                self.camera_zones[camera_id] = {}
            self.camera_zones[camera_id][zone.zone_id] = zone

    def remove_zone(self, zone_id: str, camera_id: Optional[str] = None) -> bool:
        removed = False
        if zone_id in self.zones:
            del self.zones[zone_id]
            removed = True
        if camera_id and camera_id in self.camera_zones:
            if zone_id in self.camera_zones[camera_id]:
                del self.camera_zones[camera_id][zone_id]
                removed = True
        return removed

    def get_zones_for_point(self, pt: Tuple[float, float], camera_id: Optional[str] = None) -> List[TrafficZone]:
        """Finds all zones containing the specified coordinates for a given camera feed."""
        zone_dict = self.camera_zones.get(camera_id, self.zones) if camera_id else self.zones
        return [zone for zone in zone_dict.values() if zone.contains_point(pt)]

    def create_default_traffic_zones(self, frame_width: int = 1280, frame_height: int = 720, camera_id: Optional[str] = None) -> None:
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

        self.add_zone(lane_south, camera_id=camera_id)
        self.add_zone(lane_north, camera_id=camera_id)
        self.add_zone(crosswalk, camera_id=camera_id)

    def save_camera_zones(self, camera_id: str, zones: Optional[List[TrafficZone]] = None) -> bool:
        """Persists per-camera custom zone polygons to disk in JSON format."""
        target_zones = zones or list(self.camera_zones.get(camera_id, self.zones).values())
        payload = [z.to_dict() for z in target_zones]
        out_file = self.data_dir / f"{camera_id}_zones.json"
        try:
            out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            # Update cache
            self.camera_zones[camera_id] = {z.zone_id: z for z in target_zones}
            return True
        except Exception:
            return False

    def load_camera_zones(self, camera_id: str) -> List[TrafficZone]:
        """Loads per-camera custom zone polygons from disk if present."""
        out_file = self.data_dir / f"{camera_id}_zones.json"
        if not out_file.exists():
            return list(self.zones.values())

        try:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            loaded = []
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
                loaded.append(zone)
            self.camera_zones[camera_id] = {z.zone_id: z for z in loaded}
            return loaded
        except Exception:
            return list(self.zones.values())

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

