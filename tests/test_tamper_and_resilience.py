"""
ArgusTraffic AI - Field Resilience & Tampering Watchdog Test Suite
Validates database WAL mode persistence and optical camera anti-tampering heuristics.
"""

import sqlite3
import numpy as np
import pytest
from pathlib import Path
import tempfile

from src.core.incident_db import IncidentDatabase
from src.core.auth_rbac import SecurityAuthManager
from src.core.detector import apply_clahe_enhancement, check_optical_tampering, TrafficDetector


def test_incident_database_wal_mode():
    """Verify that IncidentDatabase enables WAL mode and synchronous=NORMAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_incidents.db"
        db = IncidentDatabase(db_path=db_file)
        
        conn = db._get_connection()
        try:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
            assert mode.lower() == "wal", f"Expected WAL mode, got {mode}"
            assert sync in (1, "1", "NORMAL", "normal")
        finally:
            conn.close()


def test_auth_rbac_wal_mode():
    """Verify that SecurityAuthManager enables WAL mode and synchronous=NORMAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_users.db"
        auth = SecurityAuthManager(db_path=db_file)
        
        conn = auth._get_connection()
        try:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
            assert mode.lower() == "wal", f"Expected WAL mode, got {mode}"
            assert sync in (1, "1", "NORMAL", "normal")
        finally:
            conn.close()


def test_clahe_enhancement():
    """Verify that CLAHE enhancement preserves shape and adjusts contrast."""
    # Create dark frame with some subtle gradient
    frame = np.full((120, 160, 3), 30, dtype=np.uint8)
    frame[40:80, 50:110] = 60
    
    enhanced = apply_clahe_enhancement(frame, clip_limit=3.0)
    assert enhanced.shape == frame.shape
    assert enhanced.dtype == np.uint8
    # Average luminance of the central region should be enhanced
    assert np.mean(enhanced[40:80, 50:110]) >= np.mean(frame[40:80, 50:110])


def test_clahe_empty_frame():
    """Verify CLAHE gracefully handles empty or None frames."""
    assert apply_clahe_enhancement(None) is None
    empty = np.array([], dtype=np.uint8)
    assert apply_clahe_enhancement(empty).size == 0


def test_tamper_detection_blackout():
    """Test camera lens blackout or covered sensor detection."""
    blackout_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    res = check_optical_tampering(blackout_frame)
    assert res["tampered"] is True
    assert res["reason"] == "lens_covered_or_blackout"


def test_tamper_detection_blinding_glare():
    """Test camera blinded by direct high-beam / laser glare."""
    glare_frame = np.full((100, 100, 3), 250, dtype=np.uint8)
    res = check_optical_tampering(glare_frame)
    assert res["tampered"] is True
    assert res["reason"] == "blinding_glare_or_laser"


def test_tamper_detection_spray_paint_blur():
    """Test camera sprayed with paint or severely defocussed/frosted."""
    # Uniform smooth gray frame has very low Laplacian variance
    spray_frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    res = check_optical_tampering(spray_frame)
    assert res["tampered"] is True
    assert res["reason"] == "lens_spray_or_severe_defocus"


def test_tamper_detection_nominal_scene():
    """Test camera viewing normal scene with rich edges and moderate illumination."""
    # Create textured checkerboard pattern with sharp edges
    scene = np.zeros((200, 200, 3), dtype=np.uint8)
    scene[::20, :] = 180
    scene[:, ::20] = 180
    scene[50:150, 50:150] = 120
    
    res = check_optical_tampering(scene)
    assert res["tampered"] is False
    assert res["reason"] == "nominal"
    assert res["variance"] > 12.0


def test_traffic_detector_with_clahe():
    """Verify TrafficDetector works seamlessly with enable_clahe=True."""
    detector = TrafficDetector(enable_clahe=True)
    frame = np.full((240, 320, 3), 50, dtype=np.uint8)
    detections, inference_time = detector.detect(frame)
    assert isinstance(detections, list)
    assert inference_time >= 0.0
