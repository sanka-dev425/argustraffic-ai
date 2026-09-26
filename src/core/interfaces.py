"""
ArgusTraffic AI - Core Domain Interfaces & Protocols
Defines the foundational domain contracts, protocols, and data structures.
Adheres strictly to the Dependency Inversion Principle (DIP).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, Union
import numpy as np


class ObjectCategory(str, Enum):
    PEDESTRIAN = "pedestrian"
    BICYCLE = "bicycle"
    CAR = "car"
    MOTORCYCLE = "motorcycle"
    BUS = "bus"
    TRUCK = "truck"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


class IncidentType(str, Enum):
    WRONG_WAY = "WRONG_WAY"
    COLLISION = "COLLISION"
    STALLED_VEHICLE = "STALLED_VEHICLE"
    PEDESTRIAN_HAZARD = "PEDESTRIAN_HAZARD"
    EMERGENCY_CORRIDOR = "EMERGENCY_CORRIDOR"
    CONGESTION = "CONGESTION"
    SPEED_VIOLATION = "SPEED_VIOLATION"


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(str, Enum):
    NEGLIGIBLE = "NEGLIGIBLE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    def iou(self, other: BoundingBox) -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)

        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        intersection = iw * ih

        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0


@dataclass
class Detection:
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    confidence: float
    class_id: int
    class_name: str
    track_id: Optional[int] = None
    velocity: Optional[Tuple[float, float]] = None  # (vx, vy) px/frame

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


@dataclass
class TrackedObject:
    track_id: int
    class_name: str
    bbox: Tuple[float, float, float, float]
    centroid: Tuple[float, float]
    velocity: Tuple[float, float]  # (vx, vy) in px/frame
    speed_px_per_sec: float
    heading_deg: float
    age: int
    hits: int
    lost_frames: int
    history: List[Tuple[float, float]] = field(default_factory=list)
    license_plate: Optional[str] = None
    confidence: float = 1.0


@dataclass
class RiskAssessment:
    risk_level: RiskLevel
    risk_score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    time_to_collision_sec: Optional[float]
    involved_track_ids: List[int]
    primary_hazard: str
    contributing_factors: List[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class IncidentEvent:
    incident_id: str
    incident_type: IncidentType
    severity: IncidentSeverity
    timestamp: float
    camera_id: str
    location: str
    track_ids: List[int]
    confidence: float
    description: str
    telemetry: Dict[str, Any] = field(default_factory=dict)
    snapshot_path: Optional[str] = None
    evidence_hash: Optional[str] = None


# =====================================================================
# PROTOCOLS (Interfaces)
# =====================================================================

class DetectionEngine(Protocol):
    """Abstract protocol for computer vision object detectors (YOLO, RT-DETR, ONNX)."""

    def detect(self, frame: np.ndarray) -> Tuple[List[Detection], float]:
        """Runs detection on a single image frame, returning (detections, latency_ms)."""
        ...


class TrackingEngine(Protocol):
    """Abstract protocol for multi-object tracking engines."""

    def update(self, detections: List[Detection], frame_time: float) -> List[TrackedObject]:
        """Associates detections with active tracks and updates kinematic state."""
        ...

    def get_active_tracks(self) -> List[TrackedObject]:
        """Returns currently active and confirmed tracks."""
        ...


class RiskEngineProtocol(Protocol):
    """Abstract protocol for spatial kinematics and multi-signal risk estimation."""

    def assess_risk(
        self,
        tracks: List[TrackedObject],
        zones: Optional[Dict[str, Any]] = None,
        frame_time: Optional[float] = None
    ) -> List[RiskAssessment]:
        """Evaluates Time-to-Collision (TTC), proximity conflicts, and hazardous trajectory vectors."""
        ...


class IncidentEngineProtocol(Protocol):
    """Abstract protocol for rule-based and behavioral incident evaluation."""

    def evaluate(
        self,
        tracks: List[TrackedObject],
        frame: Optional[np.ndarray] = None,
        frame_time: Optional[float] = None,
    ) -> List[IncidentEvent]:
        """Evaluates track kinematics against municipal safety rules."""
        ...


class EventDispatcher(Protocol):
    """Abstract protocol for alerting and external webhook/MQTT notifications."""

    def dispatch(self, incident: IncidentEvent) -> bool:
        """Dispatches incident to configured downstream subscribers."""
        ...


class StorageEngine(Protocol):
    """Abstract protocol for persistent metadata and audit storage."""

    def save_incident(self, incident: IncidentEvent) -> bool:
        ...

    def get_incidents(self, limit: int = 100, offset: int = 0) -> List[IncidentEvent]:
        ...
