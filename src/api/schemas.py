"""
ArgusTraffic AI - API Pydantic Schemas
Defines request and response schemas for REST and WebSocket interfaces.
"""

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class DetectionItem(BaseModel):
    bbox: Tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str
    track_id: Optional[int] = None
    velocity: Optional[Tuple[float, float]] = None


class IncidentAlertItem(BaseModel):
    alert_id: str
    incident_type: str
    severity: str
    timestamp: float
    formatted_time: str
    description: str
    location: Tuple[float, float]
    involved_track_ids: List[int]
    zone_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FlowVectorSchema(BaseModel):
    dx: float
    dy: float
    angle_deg: Optional[float] = None


class ZoneSchema(BaseModel):
    zone_id: str
    name: str
    zone_type: str  # 'lane', 'crosswalk', 'no_stopping', 'danger'
    polygon: List[Tuple[float, float]]
    expected_flow: Optional[FlowVectorSchema] = None
    speed_limit_px: float = 35.0


class TelemetryResponse(BaseModel):
    status: str
    fps: float
    latency_ms: float
    active_tracks: int
    total_incidents_recorded: int
    device: str
    model: str


class ImageDetectionResponse(BaseModel):
    detections: List[DetectionItem]
    incidents: List[IncidentAlertItem]
    inference_time_ms: float
    total_time_ms: float
