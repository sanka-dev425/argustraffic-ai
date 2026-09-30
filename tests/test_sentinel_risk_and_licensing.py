"""
ArgusTraffic AI - Sentinel, CPA Risk, and Licensing Verification Test Suite
Verifies:
1. ContinuousLedgerSentinel correctly audits incidents.db with alert_id primary keys.
2. LicenseManager 72-hour operational emergency grace period.
3. SpatialRiskEngine Closest Point of Approach (CPA) on orthogonal 90-degree intersection collision courses.
"""

import datetime
import os
import sqlite3
import tempfile
import time
import pytest


from src.core.interfaces import ObjectCategory, RiskLevel, TrackedObject
from src.core.ledger_sentinel import ContinuousLedgerSentinel
from src.core.license_manager import LicenseManager, LicenseTier
from src.core.risk_engine import SpatialRiskEngine


def test_continuous_ledger_sentinel_with_incidents_db(tmp_path):
    db_path = tmp_path / "incidents.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE incidents (
            alert_id TEXT PRIMARY KEY,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            timestamp REAL NOT NULL,
            formatted_time TEXT NOT NULL,
            description TEXT NOT NULL,
            location_x REAL,
            location_y REAL,
            involved_tracks TEXT,
            zone_id TEXT,
            metadata_json TEXT,
            snapshot_path TEXT,
            license_plate TEXT,
            speed_kmh REAL
        )
    """)
    # Insert 3 incident records
    for i in range(1, 4):
        conn.execute("""
            INSERT INTO incidents (alert_id, incident_type, severity, timestamp, formatted_time, description, location_x, location_y)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (f"INC-TEST-00{i}", "WRONG_WAY", "CRITICAL", 1000.0 + i, "2026-09-30", "Vehicle on shoulder", 100.0 * i, 200.0 * i))
    conn.commit()
    conn.close()

    sentinel = ContinuousLedgerSentinel(db_path=str(db_path))
    report = sentinel.run_integrity_audit(auditor_identity="TEST_AUDITOR")

    assert report.status == "VERIFIED_IMMUTABLE"
    assert report.is_compromised is False
    assert report.total_records_audited == 3
    assert len(report.current_merkle_root) == 64


def test_license_manager_emergency_grace_period(tmp_path):
    lic_path = tmp_path / "test.lic"
    lm = LicenseManager(license_path=str(lic_path))

    # Generate an expired license (expired 1 day ago, well within 3-day 72h grace period)
    now = datetime.datetime.now(datetime.timezone.utc)
    token = lm.generate_license_token(
        customer_name="Emergency Police Command",
        tier=LicenseTier.ENTERPRISE,
        max_cameras=32,
        validity_days=-1, # Expired yesterday
        bind_machine_fingerprint=lm.get_machine_fingerprint(),
    )

    valid, msg, cert = lm.verify_license_token(token)
    assert valid is True # ALLOWED UNDER 72-HOUR GRACE!
    assert "grace period" in msg.lower()
    assert cert is not None
    assert cert.customer_name == "Emergency Police Command"

    # Generate a license expired 10 days ago (outside 72h grace window)
    expired_token = lm.generate_license_token(
        customer_name="Old Command",
        tier=LicenseTier.ENTERPRISE,
        validity_days=-10,
        bind_machine_fingerprint=lm.get_machine_fingerprint(),
    )
    exp_valid, exp_msg, _ = lm.verify_license_token(expired_token)
    assert exp_valid is False # Denied beyond 72h
    assert "lapsed" in exp_msg.lower() or "expired" in exp_msg.lower()


def test_spatial_risk_engine_orthogonal_intersection_cpa():
    engine = SpatialRiskEngine()

    # Two vehicles crossing perpendicularly at an intersection:
    # Vehicle 1 moving East along Y=300 (from X=200 towards X=500 at 10 px/frame) -> reaches X=400 at t=20 frames
    # Vehicle 2 moving North along X=400 (from Y=500 towards Y=100 at -10 px/frame) -> reaches Y=300 at t=20 frames
    # Collision point: (400, 300) at t=20 frames (approx 0.67 seconds)
    t1 = TrackedObject(
        track_id=1,
        class_name=ObjectCategory.CAR.value,
        bbox=(180.0, 280.0, 220.0, 320.0),
        centroid=(200.0, 300.0),
        velocity=(10.0, 0.0),
        speed_px_per_sec=300.0,
        heading_deg=0.0,
        age=10,
        hits=10,
        lost_frames=0,
        history=[(200.0, 300.0)],
        confidence=0.95,
    )

    t2 = TrackedObject(
        track_id=2,
        class_name=ObjectCategory.CAR.value,
        bbox=(380.0, 480.0, 420.0, 520.0),
        centroid=(400.0, 500.0),
        velocity=(0.0, -10.0),
        speed_px_per_sec=300.0,
        heading_deg=270.0,
        age=10,
        hits=10,
        lost_frames=0,
        history=[(400.0, 500.0)],
        confidence=0.95,
    )

    assessments = engine.assess_risk([t1, t2])
    assert len(assessments) >= 1
    top_risk = assessments[0]
    assert top_risk.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
    assert any("TTC" in f or "Critical" in f for f in top_risk.contributing_factors)

