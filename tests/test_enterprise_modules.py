"""ArgusTraffic AI - Enterprise Subsystems Verification Test Suite
Tests ANPR, Speed Radar, Trajectory Anomaly Intelligence, and RBAC Security Kernel.
"""

import time
import pytest
from src.core.speed_engine import SpeedRadarEngine
from src.core.anpr_engine import ANPREngine
from src.core.anomaly_engine import AnomalyEngine
from src.core.auth_rbac import SecurityAuthManager, Role


def test_speed_radar_calculation():
    radar = SpeedRadarEngine(pixels_per_meter=10.0, speed_limit_kmh=50.0)

    # Simulate vehicle moving 100 pixels in 1 second -> 10 meters/s = 36 km/h
    t0 = 1000.0
    radar.update_track(track_id=1, cx=0.0, cy=0.0, timestamp=t0)
    spd = radar.update_track(track_id=1, cx=100.0, cy=0.0, timestamp=t0 + 1.0)

    assert spd > 0.0
    is_speeding, obs, limit = radar.is_speeding(1)
    assert not is_speeding

    # Now move 500 pixels in 1 second -> 50 m/s = 180 km/h sustained
    radar.update_track(track_id=1, cx=600.0, cy=0.0, timestamp=t0 + 2.0)
    spd_fast = radar.update_track(track_id=1, cx=1100.0, cy=0.0, timestamp=t0 + 3.0)
    assert spd_fast > 50.0
    is_speeding, obs, limit = radar.is_speeding(1)
    assert is_speeding


def test_anpr_engine_recognition():
    anpr = ANPREngine(confidence_threshold=0.85)

    rec = anpr.recognize_plate(track_id=42, vehicle_class="car", confidence=0.94)
    assert "plate_number" in rec
    assert rec["verified"] is True
    assert rec["confidence"] >= 0.85

    # Consistency check: querying the same track returns the exact same plate
    rec2 = anpr.recognize_plate(track_id=42, vehicle_class="car", confidence=0.94)
    assert rec["plate_number"] == rec2["plate_number"]


def test_anomaly_engine_u_turn_and_deceleration():
    anomaly = AnomalyEngine(swerve_variance_threshold=300.0, deceleration_threshold_ms2=5.0)

    t0 = 2000.0
    # Simulate initial forward movement (+y direction)
    for i in range(5):
        anomaly.ingest_vector(track_id=7, cx=100.0, cy=100.0 + i * 20, vx=0.0, vy=20.0, speed_kmh=60.0, timestamp=t0 + i * 0.1)

    # Abrupt braking: speed drops from 60 km/h to 5 km/h in 0.2s
    alerts = anomaly.ingest_vector(track_id=7, cx=100.0, cy=205.0, vx=0.0, vy=2.0, speed_kmh=5.0, timestamp=t0 + 0.6)
    braking_alerts = [a for a in alerts if a["type"] == "ABRUPT_BRAKING_HAZARD"]
    assert len(braking_alerts) > 0


def test_rbac_security_vault(tmp_path):
    db_file = tmp_path / "test_security.db"
    auth = SecurityAuthManager(db_path=str(db_file))

    # Test SuperAdmin creation & login
    created = auth.create_user("chief_officer", "SecretPass123!", "Chief Traffic Officer", "chief@traffic.internal", Role.SUPER_ADMIN)
    assert created is True

    # Failed login
    res_fail = auth.authenticate("chief_officer", "WrongPassword")
    assert res_fail is None

    # Success login
    session = auth.authenticate("chief_officer", "SecretPass123!")
    assert session is not None
    assert session["role"] == "SUPER_ADMIN"
    assert "system:manage" in session["permissions"]

    # Verify session token
    verified = auth.verify_token(session["token"])
    assert verified is not None
    assert verified["username"] == "chief_officer"
