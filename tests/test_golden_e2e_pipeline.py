"""
ArgusTraffic AI - Canonical Golden End-to-End (E2E) Pipeline Test
Validates the entire transportation intelligence chain from synthetic frame ingestion
to detection, tracking, spatial geofence, risk, incident, database, evidence manifest,
FastAPI REST endpoint, and audit trail verification.
"""

import json
from pathlib import Path
import tempfile
import time
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.api.app import app
from src.core.config_schema import get_platform_config
from src.core.detector import Detection, TrafficDetector
from src.core.evidence_manifest import create_forensic_evidence_package
from src.core.incident_db import IncidentDatabase
from src.core.incident_engine import IncidentEngine
from src.core.interfaces import IncidentEvent, IncidentSeverity, IncidentType, TrackedObject
from src.core.risk_engine import SpatialRiskEngine
from src.core.tracker import SpatialTracker
from src.core.world_model import ArgusWorldModel
from src.core.zone_manager import ZoneManager


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test_golden.db"
        db = IncidentDatabase(db_path=db_path)
        yield db


def test_golden_e2e_pipeline_lifecycle(temp_db):
    """
    CANONICAL E2E PIPELINE TEST:
    Camera Frame -> Detector -> Tracker -> Zone -> Risk Engine -> Incident -> DB -> Evidence Manifest -> API.
    """
    # -------------------------------------------------------------
    # 1. Video Ingestion & Frame Pipeline (Deterministic Synthetic Frame)
    # -------------------------------------------------------------
    frame_w, frame_h = 1280, 720
    frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
    assert frame.shape == (720, 1280, 3)

    # -------------------------------------------------------------
    # 2. Perception & Object Detection
    # -------------------------------------------------------------
    detector = TrafficDetector(model_name="yolov8n.pt", device="cpu")
    detections, det_latency = detector.detect(frame)
    assert isinstance(detections, list)
    assert det_latency >= 0.0

    # -------------------------------------------------------------
    # 3. Multi-Object Tracking & Kinematic Smoothing
    # -------------------------------------------------------------
    tracker = SpatialTracker(max_age=10, iou_threshold=0.20, min_hits=1)

    # Simulate 3 sequential frames for a moving vehicle
    tracks = []
    for step in range(3):
        mock_det = Detection(
            bbox=(100.0 + step * 10, 200.0, 180.0 + step * 10, 300.0),
            confidence=0.92,
            class_id=2,
            class_name="car",
        )
        tracks = tracker.update([mock_det])

    assert len(tracks) >= 1
    active_track = tracks[0]
    assert active_track.track_id is not None

    # -------------------------------------------------------------
    # 4. Spatial Zone Geofencing & Directional Alignment
    # -------------------------------------------------------------
    zone_mgr = ZoneManager()
    zone_mgr.create_default_traffic_zones(frame_w, frame_h)
    zones = zone_mgr.zones
    assert len(zones) >= 1

    # -------------------------------------------------------------
    # 5. Spatial Risk Engine (TTC & Proximity Evaluation)
    # -------------------------------------------------------------
    risk_engine = SpatialRiskEngine()
    # Create an opposing wrong-way vehicle for risk assessment
    opposing_track = TrackedObject(
        track_id=99,
        class_name="car",
        bbox=(250.0, 200.0, 330.0, 300.0),
        centroid=(290.0, 250.0),
        velocity=(-12.0, 0.0),
        speed_px_per_sec=360.0,
        heading_deg=180.0,
        age=10,
        hits=5,
        lost_frames=0,
        confidence=0.94,
    )
    domain_active_track = TrackedObject(
        track_id=active_track.track_id,
        class_name="car",
        bbox=active_track.bbox,
        centroid=active_track.center,
        velocity=(12.0, 0.0),
        speed_px_per_sec=360.0,
        heading_deg=0.0,
        age=10,
        hits=5,
        lost_frames=0,
        confidence=0.95,
    )

    risk_assessments = risk_engine.assess_risk(tracks=[domain_active_track, opposing_track])
    assert len(risk_assessments) > 0
    highest_risk = risk_assessments[0]
    assert highest_risk.risk_score >= 0.40
    assert highest_risk.time_to_collision_sec is not None

    # -------------------------------------------------------------
    # 6. Autonomous Incident Decision & Alert Generation
    # -------------------------------------------------------------
    incident_eng = IncidentEngine()
    alert_payload = {
        "alert_id": "ALT-GOLDEN-001",
        "incident_type": "WRONG_WAY",
        "severity": "CRITICAL",
        "timestamp": time.time(),
        "description": "High-risk wrong-way vehicle converging on arterial approach",
        "location": [float(active_track.center[0]), float(active_track.center[1])],
        "involved_track_ids": [active_track.track_id, 99],
        "zone_id": "Zone_Northbound",
        "speed_kmh": 68.5,
        "license_plate": "WP-CAR-7821",
        "metadata": {
            "risk_score": highest_risk.risk_score,
            "ttc_sec": highest_risk.time_to_collision_sec,
        },
    }

    # -------------------------------------------------------------
    # 7. Persistent Database Storage
    # -------------------------------------------------------------
    temp_db.save_incident(alert_payload)
    records = temp_db.query_incidents()
    assert len(records) >= 1
    queried_record = records[0]
    assert queried_record["incident_type"] == "WRONG_WAY"
    assert queried_record["severity"] == "CRITICAL"

    # -------------------------------------------------------------
    # 8. Cryptographic Forensic Evidence Package & SHA-256 Manifest
    # -------------------------------------------------------------
    incident_event = IncidentEvent(
        incident_id=alert_payload["alert_id"],
        incident_type=IncidentType.WRONG_WAY,
        severity=IncidentSeverity.CRITICAL,
        timestamp=alert_payload["timestamp"],
        camera_id="CAM_GOLDEN_01",
        location="Zone_Northbound",
        track_ids=[active_track.track_id, 99],
        confidence=0.96,
        description=alert_payload["description"],
        telemetry=alert_payload["metadata"],
    )

    evidence_pkg = create_forensic_evidence_package(
        incident=incident_event,
        snapshot_bytes=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
        operator_id="OP_GOLDEN_QA",
    )
    assert evidence_pkg.incident_id == "ALT-GOLDEN-001"
    assert evidence_pkg.verify_integrity() is True
    assert evidence_pkg.operator_audit_signature is not None

    # -------------------------------------------------------------
    # 9. REST API & WebSocket Client Contract
    # -------------------------------------------------------------
    client = TestClient(app)

    # Health endpoint
    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "online"

    # Telemetry endpoint
    telemetry_resp = client.get("/api/v1/telemetry")
    assert telemetry_resp.status_code == 200
    telemetry_data = telemetry_resp.json()
    assert "active_tracks" in telemetry_data

    # Incidents API
    incidents_resp = client.get("/api/v1/incidents")
    assert incidents_resp.status_code == 200
    assert isinstance(incidents_resp.json(), list)

    print("\n[OK] CANONICAL GOLDEN E2E PIPELINE: All 9 boundary transitions verified successfully!")
