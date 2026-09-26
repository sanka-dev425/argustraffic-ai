"""
ArgusTraffic AI V2 - City & Corridor World Model
Represents the dynamic spatial ontology of the transportation network:
Camera -> Lane -> Approach -> Intersection -> Corridor -> District -> City.
Maintains persistent world entities with explicit uncertainty and lifecycle tracking.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import time
from typing import Any, Dict, List, Optional, Tuple


class LaneMovement(str, Enum):
    STRAIGHT = "STRAIGHT"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    U_TURN = "U_TURN"
    MERGE = "MERGE"
    EXIT = "EXIT"


class TrafficState(str, Enum):
    FREE_FLOW = "FREE_FLOW"
    STABLE = "STABLE"
    SLOW = "SLOW"
    CONGESTED = "CONGESTED"
    STOP_AND_GO = "STOP_AND_GO"
    GRIDLOCK = "GRIDLOCK"


class SignalPhase(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    FLASHING_YELLOW = "FLASHING_YELLOW"
    ALL_RED = "ALL_RED"


@dataclass
class LaneEntity:
    lane_id: str
    lane_index: int
    approach_id: str
    movement_type: LaneMovement
    speed_limit_kmh: float = 60.0
    capacity_vph: float = 1800.0  # vehicles per hour capacity
    current_occupancy_ratio: float = 0.0  # 0.0 to 1.0
    current_queue_length_m: float = 0.0
    active_vehicle_count: int = 0
    is_blocked: bool = False


@dataclass
class IntersectionEntity:
    intersection_id: str
    name: str
    latitude: float
    longitude: float
    lanes: Dict[str, LaneEntity] = field(default_factory=dict)
    active_signal_phase: SignalPhase = SignalPhase.GREEN
    cycle_length_sec: float = 90.0
    saturation_ratio: float = 0.0  # volume/capacity ratio
    connected_camera_ids: List[str] = field(default_factory=list)


@dataclass
class CorridorEntity:
    corridor_id: str
    name: str
    intersection_ids: List[str] = field(default_factory=list)
    total_length_km: float = 2.5
    average_travel_time_sec: float = 180.0
    free_flow_travel_time_sec: float = 150.0
    overall_traffic_state: TrafficState = TrafficState.FREE_FLOW
    congestion_index: float = 0.0  # 0.0 (empty) to 1.0 (gridlock)


@dataclass
class DynamicWorldEntity:
    entity_id: str
    entity_type: str  # vehicle, pedestrian, bicycle, emergency
    location_utm: Tuple[float, float]  # (easting, northing) or (x, y)
    velocity_mps: Tuple[float, float]  # (vx, vy) in meters/sec
    speed_kmh: float
    heading_deg: float
    current_lane_id: Optional[str] = None
    current_corridor_id: Optional[str] = None
    confidence: float = 0.95
    source_sensor_id: str = "CAM_EDGE_01"
    last_updated_utc: float = field(default_factory=time.time)


class ArgusWorldModel:
    """
    Central in-memory situational awareness graph representing the physical transportation network.
    Maintains hierarchical state across cameras, lanes, intersections, corridors, and dynamic agents.
    """

    def __init__(self, city_name: str = "Metropolis-1"):
        self.city_name = city_name
        self.corridors: Dict[str, CorridorEntity] = {}
        self.intersections: Dict[str, IntersectionEntity] = {}
        self.lanes: Dict[str, LaneEntity] = {}
        self.dynamic_entities: Dict[str, DynamicWorldEntity] = {}
        self._initialize_default_topology()

    def _initialize_default_topology(self) -> None:
        """Bootstraps a reference municipal corridor topology."""
        # 1. Create Lanes for Junction 1
        l1 = LaneEntity(
            lane_id="LANE_J1_NB_1",
            lane_index=1,
            approach_id="APP_J1_NB",
            movement_type=LaneMovement.STRAIGHT,
            speed_limit_kmh=60.0,
        )
        l2 = LaneEntity(
            lane_id="LANE_J1_NB_2",
            lane_index=2,
            approach_id="APP_J1_NB",
            movement_type=LaneMovement.LEFT,
            speed_limit_kmh=60.0,
        )
        self.lanes[l1.lane_id] = l1
        self.lanes[l2.lane_id] = l2

        # 2. Create Intersection
        j1 = IntersectionEntity(
            intersection_id="INT_JUNCTION_01",
            name="Grand Central & 5th Avenue",
            latitude=40.7527,
            longitude=-73.9772,
            lanes={l1.lane_id: l1, l2.lane_id: l2},
            connected_camera_ids=["CAM_J1_NORTH", "CAM_J1_SOUTH"],
        )
        self.intersections[j1.intersection_id] = j1

        # 3. Create Main Arterial Corridor
        c1 = CorridorEntity(
            corridor_id="CORRIDOR_GRAND_CENTRAL",
            name="Grand Central Arterial Express",
            intersection_ids=[j1.intersection_id],
            total_length_km=3.2,
        )
        self.corridors[c1.corridor_id] = c1

    def update_dynamic_entity(self, entity: DynamicWorldEntity) -> None:
        """Upserts a real-time object state into the world model."""
        self.dynamic_entities[entity.entity_id] = entity

    def update_lane_metrics(
        self, lane_id: str, vehicle_count: int, queue_meters: float, is_blocked: bool = False
    ) -> Optional[LaneEntity]:
        """Updates real-time lane occupancy and blockage state."""
        lane = self.lanes.get(lane_id)
        if not lane:
            return None

        lane.active_vehicle_count = vehicle_count
        lane.current_queue_length_m = queue_meters
        lane.is_blocked = is_blocked
        # Calculate instantaneous occupancy ratio
        lane.current_occupancy_ratio = min(1.0, max(0.0, (queue_meters / 150.0)))
        return lane

    def evaluate_corridor_state(self, corridor_id: str) -> TrafficState:
        """
        Synthesizes lane and intersection states to determine corridor health.
        """
        corridor = self.corridors.get(corridor_id)
        if not corridor:
            return TrafficState.FREE_FLOW

        # Aggregate lane occupancies along the corridor
        relevant_lanes = [
            lane
            for int_id in corridor.intersection_ids
            if int_id in self.intersections
            for lane in self.intersections[int_id].lanes.values()
        ]

        if not relevant_lanes:
            return TrafficState.FREE_FLOW

        avg_occupancy = sum(l.current_occupancy_ratio for l in relevant_lanes) / len(relevant_lanes)
        any_blocked = any(l.is_blocked for l in relevant_lanes)

        if any_blocked or avg_occupancy >= 0.85:
            state = TrafficState.GRIDLOCK
            congestion = 1.0
        elif avg_occupancy >= 0.65:
            state = TrafficState.CONGESTED
            congestion = 0.8
        elif avg_occupancy >= 0.40:
            state = TrafficState.SLOW
            congestion = 0.5
        elif avg_occupancy >= 0.20:
            state = TrafficState.STABLE
            congestion = 0.25
        else:
            state = TrafficState.FREE_FLOW
            congestion = 0.05

        corridor.overall_traffic_state = state
        corridor.congestion_index = congestion
        corridor.average_travel_time_sec = corridor.free_flow_travel_time_sec * (1.0 + congestion * 2.0)
        return state

    def get_world_summary(self) -> Dict[str, Any]:
        """Returns snapshot of current city world model."""
        return {
            "city": self.city_name,
            "corridors_count": len(self.corridors),
            "intersections_count": len(self.intersections),
            "lanes_count": len(self.lanes),
            "active_dynamic_entities": len(self.dynamic_entities),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
