"""
ArgusTraffic AI - Typed Enterprise Configuration Schema
Provides strongly-typed, validated Pydantic settings models for all platform subsystems.
Guarantees zero hardcoded magic numbers across the architecture.
"""

from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DetectorSettings(BaseModel):
    model_name: str = Field(default="yolov8n.pt", description="Pre-trained weights or model checkpoint path")
    confidence_threshold: float = Field(default=0.35, ge=0.01, le=1.0, description="Minimum detection confidence")
    iou_threshold: float = Field(default=0.45, ge=0.01, le=1.0, description="Non-maximum suppression IoU threshold")
    target_classes: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 5, 7], description="COCO IDs to track")
    device: str = Field(default="auto", description="Execution target (auto, cpu, cuda, mps)")
    half_precision: bool = Field(default=True, description="Enable FP16 acceleration on supported GPUs")
    input_size: int = Field(default=640, ge=320, le=1920, description="Square input resolution for inference")


class TrackerSettings(BaseModel):
    max_lost_frames: int = Field(default=30, ge=1, le=300, description="Frames to maintain track state without hits")
    iou_threshold: float = Field(default=0.30, ge=0.01, le=1.0, description="Spatial matching threshold")
    min_hits: int = Field(default=3, ge=1, le=30, description="Hits required before track is confirmed")
    velocity_ema_alpha: float = Field(default=0.40, ge=0.01, le=1.0, description="Smoothing factor for velocity")
    max_history_len: int = Field(default=60, ge=10, le=500, description="Centroid trajectory breadcrumb retention")


class WrongWaySettings(BaseModel):
    enabled: bool = True
    angle_threshold_deg: float = Field(default=120.0, ge=30.0, le=180.0, description="Deviation angle to trigger alert")
    min_speed_px_per_sec: float = Field(default=15.0, ge=1.0, description="Minimum speed to evaluate trajectory")
    cooldown_seconds: float = Field(default=10.0, ge=1.0, description="Alert suppression cooldown window")


class CollisionSettings(BaseModel):
    enabled: bool = True
    iou_overlap_threshold: float = Field(default=0.18, ge=0.05, le=0.90, description="Bounding box intersection ratio")
    speed_drop_ratio: float = Field(default=0.60, ge=0.10, le=0.95, description="Deceleration drop threshold")
    cooldown_seconds: float = Field(default=15.0, ge=1.0, description="Alert suppression cooldown window")


class StalledVehicleSettings(BaseModel):
    enabled: bool = True
    max_stationary_speed_px_per_sec: float = Field(default=5.0, ge=0.0, description="Speed threshold for stationary state")
    duration_threshold_seconds: float = Field(default=3.0, ge=0.5, le=60.0, description="Time stalled before triggering")
    cooldown_seconds: float = Field(default=20.0, ge=1.0, description="Alert suppression cooldown window")


class PedestrianHazardSettings(BaseModel):
    enabled: bool = True
    ttc_threshold_seconds: float = Field(default=1.8, ge=0.1, le=10.0, description="Time-to-collision hazard threshold")
    proximity_buffer_px: float = Field(default=80.0, ge=10.0, le=500.0, description="Vehicle-to-pedestrian safety zone")
    cooldown_seconds: float = Field(default=8.0, ge=1.0, description="Alert suppression cooldown window")


class IncidentRulesSettings(BaseModel):
    wrong_way: WrongWaySettings = Field(default_factory=WrongWaySettings)
    collision: CollisionSettings = Field(default_factory=CollisionSettings)
    stalled_vehicle: StalledVehicleSettings = Field(default_factory=StalledVehicleSettings)
    pedestrian_hazard: PedestrianHazardSettings = Field(default_factory=PedestrianHazardSettings)


class RiskEngineSettings(BaseModel):
    enabled: bool = True
    critical_ttc_seconds: float = Field(default=1.5, description="TTC under which risk is deemed CRITICAL")
    high_ttc_seconds: float = Field(default=2.5, description="TTC under which risk is deemed HIGH")
    medium_ttc_seconds: float = Field(default=4.0, description="TTC under which risk is deemed MEDIUM")
    weight_ttc: float = 0.40
    weight_relative_speed: float = 0.25
    weight_proximity: float = 0.20
    weight_vulnerable_road_user: float = 0.15


class ANPRSettings(BaseModel):
    enabled: bool = True
    confidence_threshold: float = 0.40
    enable_masking_in_audit: bool = Field(default=True, description="Privacy compliance: mask license plates in logs")
    retention_days: int = Field(default=30, ge=1, le=365, description="Data retention period before automated purge")


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])


class SecuritySettings(BaseModel):
    jwt_secret: str = Field(default="argus-traffic-enterprise-secret-key-change-in-production")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    admin_default_username: str = "admin"
    admin_default_password: str = "argus_admin_2026"


class PlatformConfig(BaseModel):
    version: str = "1.2.0"
    environment: str = "production"
    detector: DetectorSettings = Field(default_factory=DetectorSettings)
    tracker: TrackerSettings = Field(default_factory=TrackerSettings)
    incidents: IncidentRulesSettings = Field(default_factory=IncidentRulesSettings)
    risk: RiskEngineSettings = Field(default_factory=RiskEngineSettings)
    anpr: ANPRSettings = Field(default_factory=ANPRSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)


# Global Config Loader Utility
_ACTIVE_CONFIG: Optional[PlatformConfig] = None


def get_platform_config() -> PlatformConfig:
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is None:
        _ACTIVE_CONFIG = PlatformConfig()
    return _ACTIVE_CONFIG


def set_platform_config(config: PlatformConfig) -> None:
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config
