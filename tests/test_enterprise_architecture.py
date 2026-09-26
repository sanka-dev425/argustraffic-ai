"""
Unit & Integration Tests for Enterprise Architecture, Protocols, Config & Risk Engine.
"""

import pytest
import numpy as np

from src.core.interfaces import (
    BoundingBox,
    Detection,
    TrackedObject,
    RiskAssessment,
    RiskLevel,
    IncidentType,
    IncidentSeverity,
    ObjectCategory,
)
from src.core.config_schema import (
    PlatformConfig,
    DetectorSettings,
    TrackerSettings,
    IncidentRulesSettings,
    RiskEngineSettings,
    get_platform_config,
)
from src.core.risk_engine import SpatialRiskEngine


def test_bounding_box_geometry_and_iou():
    box1 = BoundingBox(x1=0.0, y1=0.0, x2=100.0, y2=100.0)
    box2 = BoundingBox(x1=50.0, y1=50.0, x2=150.0, y2=150.0)
    box3 = BoundingBox(x1=200.0, y1=200.0, x2=300.0, y2=300.0)

    assert box1.width == 100.0
    assert box1.height == 100.0
    assert box1.area == 10000.0
    assert box1.center == (50.0, 50.0)

    # Overlapping boxes IoU
    iou_12 = box1.iou(box2)
    assert 0.14 < iou_12 < 0.15  # 2500 / 17500 ≈ 0.1428

    # Non-overlapping boxes IoU
    assert box1.iou(box3) == 0.0


def test_platform_config_validation():
    config = get_platform_config()
    assert config.version == "1.2.0"
    assert config.detector.confidence_threshold == 0.35
    assert config.tracker.velocity_ema_alpha == 0.40
    assert config.incidents.wrong_way.angle_threshold_deg == 120.0
    assert config.risk.enabled is True

    # Validate custom settings
    custom = PlatformConfig(
        environment="staging",
        detector=DetectorSettings(confidence_threshold=0.50),
    )
    assert custom.environment == "staging"
    assert custom.detector.confidence_threshold == 0.50


def test_spatial_risk_engine_pairwise_ttc():
    risk_engine = SpatialRiskEngine()

    # Create two converging vehicles on collision course
    # Vehicle 1 moving right: (x=100, vx=10)
    # Vehicle 2 moving left: (x=300, vx=-10)
    t1 = TrackedObject(
        track_id=1,
        class_name="car",
        bbox=(80.0, 180.0, 120.0, 220.0),
        centroid=(100.0, 200.0),
        velocity=(10.0, 0.0),
        speed_px_per_sec=300.0,
        heading_deg=0.0,
        age=20,
        hits=10,
        lost_frames=0,
        confidence=0.95,
    )

    t2 = TrackedObject(
        track_id=2,
        class_name="car",
        bbox=(280.0, 180.0, 320.0, 220.0),
        centroid=(300.0, 200.0),
        velocity=(-10.0, 0.0),
        speed_px_per_sec=300.0,
        heading_deg=180.0,
        age=20,
        hits=10,
        lost_frames=0,
        confidence=0.92,
    )

    assessments = risk_engine.assess_risk(tracks=[t1, t2], frame_time=1000.0)

    assert len(assessments) > 0
    highest_risk = assessments[0]
    assert highest_risk.risk_score > 0.4
    assert highest_risk.time_to_collision_sec is not None
    assert highest_risk.time_to_collision_sec < 1.0
    assert 1 in highest_risk.involved_track_ids
    assert 2 in highest_risk.involved_track_ids


def test_spatial_risk_engine_pedestrian_vulnerability():
    risk_engine = SpatialRiskEngine()

    # Pedestrian close to moving car
    ped = TrackedObject(
        track_id=10,
        class_name=ObjectCategory.PEDESTRIAN,
        bbox=(140.0, 190.0, 160.0, 230.0),
        centroid=(150.0, 210.0),
        velocity=(0.0, 0.5),
        speed_px_per_sec=15.0,
        heading_deg=90.0,
        age=15,
        hits=10,
        lost_frames=0,
        confidence=0.90,
    )

    car = TrackedObject(
        track_id=20,
        class_name=ObjectCategory.CAR,
        bbox=(100.0, 190.0, 140.0, 230.0),
        centroid=(120.0, 210.0),
        velocity=(5.0, 0.0),
        speed_px_per_sec=150.0,
        heading_deg=0.0,
        age=20,
        hits=15,
        lost_frames=0,
        confidence=0.96,
    )

    assessments = risk_engine.assess_risk(tracks=[ped, car], frame_time=1000.0)
    assert len(assessments) > 0
    assert any("Vulnerable Road User" in factor for factor in assessments[0].contributing_factors)
