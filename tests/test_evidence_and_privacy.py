"""
Unit & Integration Tests for Cryptographic Evidence Manifests, ANPR Privacy, and Executive Reports.
"""

import time
import pytest

from src.core.interfaces import IncidentEvent, IncidentSeverity, IncidentType
from src.core.evidence_manifest import create_forensic_evidence_package, compute_sha256_bytes
from src.core.evidence_report import generate_forensic_html_report, generate_executive_traffic_report
from src.core.anpr_engine import ANPREngine
from src.core.config_schema import ANPRSettings


def test_evidence_manifest_creation_and_verification():
    incident = IncidentEvent(
        incident_id="INC-2026-TEST-001",
        incident_type=IncidentType.WRONG_WAY,
        severity=IncidentSeverity.CRITICAL,
        timestamp=1700000000.0,
        camera_id="CAM_NORTH_01",
        location="Arterial Highway Junction 4",
        track_ids=[101],
        confidence=0.96,
        description="Vehicle traveling against designated traffic flow",
        telemetry={"velocity": (-22.5, 0.0), "heading_deg": 180.0},
    )

    fake_snapshot = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # Minimal JPEG header bytes
    fake_trajectory = {"points": [(100, 200), (90, 200), (80, 200)]}

    package = create_forensic_evidence_package(
        incident=incident,
        snapshot_bytes=fake_snapshot,
        trajectory_data=fake_trajectory,
        operator_id="DISPATCHER_42",
    )

    assert package.incident_id == "INC-2026-TEST-001"
    assert len(package.items) == 3  # telemetry.json, incident_snapshot.jpg, trajectory.json
    assert package.verify_integrity() is True
    assert package.operator_audit_signature is not None


def test_evidence_manifest_tamper_detection():
    incident = IncidentEvent(
        incident_id="INC-2026-TAMPER-002",
        incident_type=IncidentType.COLLISION,
        severity=IncidentSeverity.HIGH,
        timestamp=1700000000.0,
        camera_id="CAM_SOUTH_02",
        location="Intersection 7",
        track_ids=[201, 202],
        confidence=0.88,
        description="Collision detected between 2 vehicles",
    )

    package = create_forensic_evidence_package(incident=incident)
    assert package.verify_integrity() is True

    # Tamper with an item's hash
    package.items[0].sha256_hash = "tampered_fake_hash_value"
    assert package.verify_integrity() is False


def test_anpr_privacy_masking():
    engine = ANPREngine()
    masked = engine.mask_plate("WP-CAR-7821")
    assert masked.startswith("WP-C")
    assert masked.endswith("21")
    assert "*" in masked

    custom_masked = engine.mask_plate("ABC1234")
    assert custom_masked.startswith("AB")
    assert custom_masked.endswith("34")
    assert "*" in custom_masked


def test_anpr_ttl_expiration_purging():
    settings = ANPRSettings(retention_days=1, enable_masking_in_audit=True)
    engine = ANPREngine(settings=settings)

    rec = engine.recognize_plate(track_id=1, vehicle_class="car", confidence=0.92)
    assert rec["masked_plate"] is not None
    assert 1 in engine._plate_cache

    # Manually backdate timestamp by 2 days
    engine._plate_cache[1]["timestamp"] = time.time() - (2 * 86400)

    purged_count = engine.purge_expired_records()
    assert purged_count == 1
    assert 1 not in engine._plate_cache


def test_executive_and_forensic_reports():
    alert = {
        "alert_id": "ALT-2026-TEST-99",
        "incident_type": "WRONG_WAY",
        "severity": "CRITICAL",
        "timestamp": time.time(),
        "description": "High speed wrong-way vehicle detected",
        "location": [500.0, 300.0],
        "involved_track_ids": [42],
        "zone_id": "Southbound Lane",
        "metadata": {"speed_kmh": 85.2},
    }
    forensic_html = generate_forensic_html_report(alert)
    assert "ALT-2026-TEST-99" in forensic_html
    assert "SHA-256" in forensic_html
    assert "WRONG_WAY" in forensic_html

    exec_html = generate_executive_traffic_report(
        stats={"total_recorded": 10, "critical_count": 2, "warning_count": 3},
        recent_incidents=[alert],
        time_window="Last 24 Hours",
        officer_name="Commander Alex",
    )
    assert "EXECUTIVE TRAFFIC SAFETY AUDIT" in exec_html
    assert "Commander Alex" in exec_html
    assert "MERKLE CERTIFICATE" in exec_html
