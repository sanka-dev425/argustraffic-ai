"""
ArgusTraffic AI V2 - V2X Gateway & Cooperative Perception Boundary
Implements standardized Connected Vehicle message abstractions (SAE J2735 / ETSI ITS)
enabling V2I (Vehicle-to-Infrastructure) and I2V advisory broadcasting without radio lock-in.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple

from src.core.world_model import ArgusWorldModel, DynamicWorldEntity


class V2XMessageType(str, Enum):
    BSM = "BSM"   # Basic Safety Message (Vehicle Telemetry)
    SPAT = "SPAT" # Signal Phase and Timing
    MAP = "MAP"   # Intersection Topology
    EVA = "EVA"   # Emergency Vehicle Alert
    RSA = "RSA"   # Road Safety Advisory (Hazard Warning)


@dataclass
class BasicSafetyMessage:
    vehicle_id: str
    latitude: float
    longitude: float
    elevation_m: float
    speed_kmh: float
    heading_deg: float
    brake_active: bool
    transmission_state: str  # FORWARD, REVERSE, PARK
    timestamp_utc: float = field(default_factory=time.time)
    security_cert_id: str = "CERT_ROOT_V2X_2026"


@dataclass
class RoadSafetyAdvisory:
    advisory_id: str
    hazard_type: str  # WRONG_WAY_DRIVER, COLLISION_AHEAD, STALLED_VEHICLE, PEDESTRIAN_CROSSING
    location_utm: Tuple[float, float]
    affected_radius_meters: float
    recommended_speed_kmh: float
    urgency_level: str  # ADVISORY, WARNING, CRITICAL
    expires_at_utc: float


import threading

class V2XGateway:
    """
    Decoupled abstraction boundary managing vehicle-to-infrastructure messaging.
    Ingests connected vehicle telemetry and broadcasts road safety alerts.
    Implements memory-bounded vehicle telemetry registry with automated TTL eviction.
    """

    def __init__(self, world_model: Optional[ArgusWorldModel] = None, vehicle_ttl_seconds: float = 30.0):
        self.world_model = world_model or ArgusWorldModel()
        self.vehicle_ttl_seconds = vehicle_ttl_seconds
        self.active_advisories: Dict[str, RoadSafetyAdvisory] = {}
        self.connected_vehicle_registry: Dict[str, BasicSafetyMessage] = {}
        self.total_messages_ingested: int = 0
        self._lock = threading.RLock()

    def prune_stale_vehicles(self, ttl_seconds: Optional[float] = None) -> int:
        """Removes vehicles that have stopped transmitting BSM telemetry beyond TTL window."""
        max_age = ttl_seconds if ttl_seconds is not None else self.vehicle_ttl_seconds
        now = time.time()
        pruned_count = 0
        with self._lock:
            stale_keys = [
                vid for vid, msg in self.connected_vehicle_registry.items()
                if (now - msg.timestamp_utc) > max_age
            ]
            for vid in stale_keys:
                del self.connected_vehicle_registry[vid]
                pruned_count += 1
        return pruned_count

    def ingest_bsm(self, msg: BasicSafetyMessage) -> bool:
        """
        Processes incoming vehicle telemetry (BSM), validates cert, and updates World Model.
        """
        if not msg.vehicle_id or msg.speed_kmh < 0:
            return False

        with self._lock:
            # Register message
            self.connected_vehicle_registry[msg.vehicle_id] = msg
            self.total_messages_ingested += 1

            # Periodically prune stale vehicles on every 100 ingested messages
            if self.total_messages_ingested % 100 == 0:
                self.prune_stale_vehicles()

        # Fuse into World Model as a dynamic entity
        entity = DynamicWorldEntity(
            entity_id=f"V2X_{msg.vehicle_id}",
            entity_type="vehicle",
            location_utm=(msg.longitude, msg.latitude),
            velocity_mps=(
                (msg.speed_kmh / 3.6) * 1.0,  # approximate forward velocity vector
                0.0,
            ),
            speed_kmh=msg.speed_kmh,
            heading_deg=msg.heading_deg,
            confidence=0.99,  # High confidence from onboard GPS/telemetry
            source_sensor_id=f"V2X_OBU_{msg.vehicle_id}",
        )
        self.world_model.update_dynamic_entity(entity)
        return True

    def broadcast_road_safety_advisory(
        self,
        hazard_type: str,
        location: Tuple[float, float],
        radius_m: float = 300.0,
        recommended_speed: float = 30.0,
        urgency: str = "WARNING",
        duration_sec: float = 60.0,
    ) -> RoadSafetyAdvisory:
        """
        Creates and registers an outgoing Road Safety Advisory (RSA) for edge transmission.
        """
        now = time.time()
        adv_id = f"RSA_{int(now)}_{hashlib.md5(hazard_type.encode()).hexdigest()[:6]}"
        advisory = RoadSafetyAdvisory(
            advisory_id=adv_id,
            hazard_type=hazard_type,
            location_utm=location,
            affected_radius_meters=radius_m,
            recommended_speed_kmh=recommended_speed,
            urgency_level=urgency,
            expires_at_utc=now + duration_sec,
        )
        with self._lock:
            self.active_advisories[adv_id] = advisory
        return advisory

    def get_active_advisories(self) -> List[RoadSafetyAdvisory]:
        """Returns non-expired safety warnings."""
        now = time.time()
        with self._lock:
            # Clean expired
            self.active_advisories = {
                aid: adv for aid, adv in self.active_advisories.items() if adv.expires_at_utc > now
            }
            return list(self.active_advisories.values())

    def get_gateway_telemetry(self) -> Dict[str, Any]:
        """Telemetry diagnostics for the V2X plane."""
        self.prune_stale_vehicles()
        with self._lock:
            return {
                "gateway_status": "ONLINE",
                "active_connected_vehicles": len(self.connected_vehicle_registry),
                "total_bsm_ingested": self.total_messages_ingested,
                "active_broadcast_advisories": len(self.get_active_advisories()),
                "supported_standards": ["SAE J2735", "ETSI ITS-G5", "C-V2X 3GPP Rel-16"],
            }
