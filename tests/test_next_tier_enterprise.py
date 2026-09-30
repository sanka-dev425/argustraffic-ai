"""
ArgusTraffic AI - Next-Tier Enterprise Subsystem Verification Suite
Tests for:
1. Camera Optical Anti-Tamper & Lens Obstruction AI (Spray Paint, Defocus, Laser Dazzling)
2. Air-Gapped Machine-Fingerprint Licensing Engine (HMAC-SHA256 Signatures, Hardware Locking)
3. Continuous Merkle Ledger Integrity Sentinel (Automated Cryptographic SQLite Audit)
4. Offline PWA Manifest & Field Dispatch Service Worker Serving
5. Integration REST API Endpoints
"""

import base64
import datetime
import json
import os
from pathlib import Path
import sqlite3
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import app, app_state
from src.core.auth_rbac import Role, SecurityAuthManager
from src.core.optical_tamper_detector import (
    OpticalTamperDetector,
    TamperDiagnostics,
    TamperState,
)
from src.core.license_manager import (
    LicenseCertificate,
    LicenseManager,
    LicenseTier,
)
from src.core.ledger_sentinel import (
    ContinuousLedgerSentinel,
    LedgerAuditReport,
)


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def auth_header():
    auth = SecurityAuthManager()
    res = auth.authenticate("admin", "ArgusAdmin2026!")
    token = res["token"] if res else ""
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Optical Anti-Tamper & Lens Obstruction AI Tests
# ==============================================================================
class TestOpticalTamperDetector:
    def test_healthy_clear_frame(self):
        detector = OpticalTamperDetector()
        # Create a textured frame with rich variance (clear scene)
        frame = np.random.randint(20, 230, (480, 640, 3), dtype=np.uint8)
        # Add edges/patterns
        for i in range(0, 480, 20):
            frame[i:i+10, :] = 255 - frame[i:i+10, :]

        diag = detector.analyze_frame(frame, camera_id="CAM-TEST-01")
        assert diag.camera_id == "CAM-TEST-01"
        assert diag.state == TamperState.CLEAR
        assert not diag.is_tampered
        assert diag.blur_score > 35.0

    def test_occlusion_spray_paint(self):
        detector = OpticalTamperDetector(min_entropy_threshold=3.2)
        # Flat black/gray frame simulating opaque spray paint or covered lens
        frame = np.full((480, 640, 3), 40, dtype=np.uint8)
        diag = detector.analyze_frame(frame, camera_id="CAM-TEST-SPRAY")
        assert diag.state == TamperState.OCCLUDED
        assert diag.is_tampered
        assert "spray" in diag.message.lower() or "obstructed" in diag.message.lower() or "occluded" in diag.message.lower()

    def test_defocus_blur(self):
        import cv2
        detector = OpticalTamperDetector(min_blur_threshold=30.0)
        # Generate random image and apply severe Gaussian blur (simulating defocus)
        raw = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        blurred = cv2.GaussianBlur(raw, (51, 51), 30.0)
        diag = detector.analyze_frame(blurred, camera_id="CAM-TEST-BLUR")
        assert diag.state in (TamperState.DEFOCUSED, TamperState.OCCLUDED)
        assert diag.is_tampered

    def test_laser_blinding_saturation(self):
        detector = OpticalTamperDetector(max_saturation_ratio=0.25)
        # Frame with over 50% saturated bright white pixels (laser / direct flashlight dazzle)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[100:400, 100:600] = 255 # Large saturated area
        diag = detector.analyze_frame(frame, camera_id="CAM-TEST-LASER")
        assert diag.state == TamperState.BLINDED
        assert diag.is_tampered
        assert diag.saturation_ratio > 0.25


# ==============================================================================
# 2. Air-Gapped Machine-Fingerprint Licensing Tests
# ==============================================================================
class TestLicenseManager:
    def test_machine_fingerprint_generation(self):
        fp = LicenseManager.get_machine_fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 32
        assert fp == fp.upper()

    def test_license_generation_and_verification(self, tmp_path):
        lic_file = tmp_path / "test_license.lic"
        mgr = LicenseManager(license_path=lic_file)

        # Generate genuine token
        token = mgr.generate_license_token(
            customer_name="Colombo Traffic Command",
            tier=LicenseTier.GOVERNMENT,
            max_cameras=128,
            validity_days=30,
        )
        assert token.startswith("ARGUS_")

        # Verify genuine token
        valid, msg, cert = mgr.verify_license_token(token)
        assert valid
        assert cert is not None
        assert cert.customer_name == "Colombo Traffic Command"
        assert cert.tier == LicenseTier.GOVERNMENT.value
        assert cert.max_cameras == 128

    def test_tampered_license_signature_rejection(self, tmp_path):
        lic_file = tmp_path / "test_license.lic"
        mgr = LicenseManager(license_path=lic_file)

        token = mgr.generate_license_token(customer_name="Legit Dept", validity_days=10)
        raw_b64 = token.replace("ARGUS_", "")
        payload = json.loads(base64.b64decode(raw_b64).decode("utf-8"))

        # Modify payload without re-signing
        payload["max_cameras"] = 9999
        tampered_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        tampered_token = f"ARGUS_{tampered_b64}"

        valid, msg, cert = mgr.verify_license_token(tampered_token)
        assert not valid
        assert "Cryptographic signature validation failed" in msg

    def test_hardware_locked_license(self, tmp_path):
        lic_file = tmp_path / "test_license.lic"
        mgr = LicenseManager(license_path=lic_file)

        # Generate bound to current machine
        current_fp = mgr.get_machine_fingerprint()
        token_match = mgr.generate_license_token(
            customer_name="Bound Corp",
            bind_machine_fingerprint=current_fp,
        )
        valid, _, _ = mgr.verify_license_token(token_match)
        assert valid

        # Generate bound to alien machine
        token_alien = mgr.generate_license_token(
            customer_name="Alien Server Corp",
            bind_machine_fingerprint="DEADBEEF000011112222333344445555",
        )
        valid_alien, msg_alien, _ = mgr.verify_license_token(token_alien)
        assert not valid_alien
        assert "Hardware binding mismatch" in msg_alien

    def test_license_installation_and_status(self, tmp_path):
        lic_file = tmp_path / "installed_license.lic"
        mgr = LicenseManager(license_path=lic_file)

        token = mgr.generate_license_token(
            customer_name="Kandy Regional Operations",
            tier=LicenseTier.ENTERPRISE,
            max_cameras=32,
            validity_days=90,
        )
        success, msg = mgr.install_license(token)
        assert success
        assert lic_file.exists()

        status = mgr.get_license_status()
        assert status["is_valid"]
        assert status["customer_name"] == "Kandy Regional Operations"
        assert status["max_cameras"] == 32
        assert status["days_remaining"] >= 89


# ==============================================================================
# 3. Continuous Merkle Ledger Sentinel Tests
# ==============================================================================
class TestContinuousLedgerSentinel:
    def test_audit_empty_database(self, tmp_path):
        db_path = tmp_path / "non_existent.db"
        sentinel = ContinuousLedgerSentinel(db_path=db_path)
        report = sentinel.run_integrity_audit(auditor_identity="TEST_RUNNER")
        assert report.status == "VERIFIED_IMMUTABLE"
        assert not report.is_compromised
        assert report.total_records_audited == 0
        assert isinstance(report.current_merkle_root, str)

    def test_audit_populated_sqlite_database(self, tmp_path):
        db_path = tmp_path / "test_incidents.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE incidents (
                incident_id TEXT PRIMARY KEY,
                incident_type TEXT,
                severity TEXT,
                timestamp TEXT,
                description TEXT,
                location_x REAL,
                location_y REAL
            )
        """)
        conn.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("INC-001", "WRONG_WAY", "CRITICAL", "2026-09-30T10:00:00Z", "Vehicle wrong way", 100.0, 200.0),
        )
        conn.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("INC-002", "STALLED_VEHICLE", "WARNING", "2026-09-30T10:05:00Z", "Vehicle stalled on shoulder", 150.0, 220.0),
        )
        conn.commit()
        conn.close()

        sentinel = ContinuousLedgerSentinel(db_path=db_path)
        report = sentinel.run_integrity_audit(auditor_identity="TEST_AUDITOR")
        assert report.status == "VERIFIED_IMMUTABLE"
        assert not report.is_compromised
        assert report.total_records_audited == 2
        assert len(report.current_merkle_root) == 64

        status_dict = sentinel.get_latest_audit_report()
        assert status_dict["total_records_audited"] == 2
        assert status_dict["status"] == "VERIFIED_IMMUTABLE"


# ==============================================================================
# 4. Offline PWA Manifest & Field Dispatch Service Worker Tests
# ==============================================================================
class TestPWAServiceWorker:
    def test_manifest_json_endpoint(self, test_client):
        res = test_client.get("/manifest.json")
        assert res.status_code == 200
        manifest = res.json()
        assert "ArgusTraffic" in manifest["name"]
        assert manifest["display"] == "standalone"
        assert len(manifest.get("icons", [])) > 0

    def test_service_worker_endpoint(self, test_client):
        res = test_client.get("/sw.js")
        assert res.status_code == 200
        assert "application/javascript" in res.headers.get("content-type", "")
        content = res.text
        assert "CACHE_NAME" in content
        assert "install" in content
        assert "fetch" in content
        assert "addEventListener" in content


# ==============================================================================
# 5. REST API Integration Endpoints Tests
# ==============================================================================
class TestNextTierAPIEndpoints:
    def test_license_status_api(self, test_client):
        res = test_client.get("/api/v1/license/status")
        assert res.status_code == 200
        data = res.json()
        assert "is_valid" in data
        assert "machine_fingerprint" in data
        assert "tier" in data

    def test_license_issue_and_install_api(self, test_client, auth_header):
        # 1. Issue
        issue_res = test_client.post(
            "/api/v1/license/issue",
            json={
                "customer_name": "Metro Police Department",
                "tier": "GOVERNMENT_DEFENSE_PERPETUAL",
                "max_cameras": 100,
                "validity_days": 180,
            },
            headers=auth_header,
        )
        assert issue_res.status_code == 200
        token = issue_res.json()["license_token"]
        assert token.startswith("ARGUS_")

        # 2. Install
        install_res = test_client.post(
            "/api/v1/license/install",
            json={"license_token": token},
            headers=auth_header,
        )
        assert install_res.status_code == 200
        assert install_res.json()["status"] == "SUCCESS"

    def test_ledger_sentinel_audit_api(self, test_client, auth_header):
        # Status
        status_res = test_client.get("/api/v1/ledger/sentinel/status")
        assert status_res.status_code == 200
        assert "current_merkle_root" in status_res.json()

        # Audit
        audit_res = test_client.post("/api/v1/ledger/sentinel/audit", headers=auth_header)
        assert audit_res.status_code == 200
        report = audit_res.json()
        assert "status" in report
        assert "current_merkle_root" in report

    def test_camera_tamper_diagnose_api(self, test_client):
        # Create a small dummy image in base64
        import cv2
        test_img = np.random.randint(50, 200, (100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", test_img)
        b64_str = base64.b64encode(buf).decode("utf-8")

        res = test_client.post(
            "/api/v1/cameras/tamper/diagnose",
            json={"camera_id": "CAM-API-01", "image_base64": b64_str},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["camera_id"] == "CAM-API-01"
        assert "state" in data
        assert "blur_score" in data
        assert "entropy_score" in data

    def test_camera_tamper_get_status_api(self, test_client):
        res = test_client.get("/api/v1/cameras/CAM-TEST-GET/tamper")
        assert res.status_code == 200
        data = res.json()
        assert data["camera_id"] == "CAM-TEST-GET"
        assert "is_tampered" in data
