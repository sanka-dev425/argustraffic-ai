"""
ArgusTraffic AI - Production Hardening, Edge Resilience & Watchdog Test Suite
Validates:
1. Automated FIFO Disk Space Watchdog & Non-Destructive Storage Purging
2. Hardware Load Governor, GPU Throttling & VRAM Protection
3. RTSP Capture Socket Options & Exponential Backoff Reconnection
4. REST API endpoints for storage and compute governance
"""

import os
from pathlib import Path
import time
from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.core.storage_watchdog import StorageWatchdogManager, StorageHealthStatus
from src.core.hardware_governor import HardwareGovernor, GovernorState
from src.utils.video_stream import HardwareAcceleratedCapture, HardwareAccelerationBackend


@pytest.fixture
def client():
    return TestClient(app)


def test_storage_watchdog_status_and_purge(tmp_path):
    # Setup test data directory
    data_dir = tmp_path / "argus_test_data"
    snapshots_dir = data_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy database (must NEVER be deleted)
    db_file = data_dir / "protected_ledger.db"
    db_file.write_text("PRAGMA journal_mode=WAL;")

    # Create dummy snapshot files with staged timestamps
    snap1 = snapshots_dir / "snap_oldest.jpg"
    snap1.write_bytes(b"\xff\xd8\xff" + b"A" * 1024)
    # Set older mtime
    os.utime(str(snap1), (time.time() - 3600, time.time() - 3600))

    snap2 = snapshots_dir / "snap_newer.jpg"
    snap2.write_bytes(b"\xff\xd8\xff" + b"B" * 2048)

    mgr = StorageWatchdogManager(data_dir=data_dir)

    # 1. Inspect status
    status = mgr.get_storage_status()
    assert "status" in status
    assert status["total_managed_files"] >= 3
    assert status["app_data_bytes"] > 3000

    # 2. Dry run purge
    dry_res = mgr.execute_fifo_purge(max_target_used_pct=0.0, dry_run=True)
    assert dry_res["purge_executed"] is True
    assert dry_res["dry_run"] is True
    assert dry_res["files_pruned"] >= 2
    assert snap1.exists()  # File still exists on dry run

    # 3. Live purge
    live_res = mgr.execute_fifo_purge(max_target_used_pct=0.0, dry_run=False)
    assert live_res["purge_executed"] is True
    assert live_res["dry_run"] is False
    assert live_res["files_pruned"] >= 2
    assert not snap1.exists()
    assert not snap2.exists()
    # Ensure database was preserved
    assert db_file.exists()


def test_hardware_governor_adaptive_throttling():
    gov = HardwareGovernor()

    # Register streams
    gov.register_stream("CAM_NORTH_01", is_priority_zone=False)
    gov.register_stream("CAM_RADAR_02", is_priority_zone=True)

    # 1. Optimal state (100% processing)
    gov.set_system_load_factor(0.30)
    assert gov.state == GovernorState.OPTIMAL

    assert gov.should_process_frame("CAM_NORTH_01", frame_index=0) is True
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=1) is True
    assert gov.should_process_frame("CAM_RADAR_02", frame_index=0) is True
    assert gov.should_process_frame("CAM_RADAR_02", frame_index=1) is True

    # 2. High Load state (non-priority skips every 2nd frame)
    gov.set_system_load_factor(0.75)
    assert gov.state == GovernorState.HIGH_LOAD

    # Non-priority stream
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=0) is True
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=1) is False
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=2) is True

    # Priority hazard stream maintains 100%
    assert gov.should_process_frame("CAM_RADAR_02", frame_index=0) is True
    assert gov.should_process_frame("CAM_RADAR_02", frame_index=1) is True

    # 3. Critical Load state (high-pressure backpressure)
    gov.set_system_load_factor(0.95)
    assert gov.state == GovernorState.CRITICAL

    # Non-priority processes every 4th frame
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=0) is True
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=1) is False
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=2) is False
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=3) is False
    assert gov.should_process_frame("CAM_NORTH_01", frame_index=4) is True

    # Telemetry
    telemetry = gov.get_telemetry()
    assert telemetry["state"] == GovernorState.CRITICAL.value
    assert telemetry["total_frames_shed"] > 0
    assert "CAM_NORTH_01" in telemetry["stream_profiles"]


def test_rtsp_video_capture_exponential_backoff(monkeypatch):
    import cv2
    # Mock cv2.VideoCapture to return un-opened capture instantly
    class MockFailedCapture:
        def isOpened(self): return False
        def release(self): pass

    monkeypatch.setattr(cv2, "VideoCapture", lambda *args, **kwargs: MockFailedCapture())

    handler = HardwareAcceleratedCapture(source="rtsp://localhost:8554/live", channel_id="CH-TEST")
    assert handler.connection_status == "NO_SIGNAL"

    # Simulate reconnect attempts
    handler._attempt_reconnect()
    assert handler.reconnect_attempts == 1
    assert handler.reconnect_interval_sec >= 2.0

    handler._attempt_reconnect()
    assert handler.reconnect_attempts == 2
    assert handler.reconnect_interval_sec >= 3.0

    # Ensure socket timeout environment variable is set
    assert "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ
    assert "stimeout" in os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]


def test_storage_and_governor_api_endpoints(client):
    # 1. Storage Status
    resp = client.get("/api/v1/storage/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "percent_used" in data
    assert "total_gb" in data

    # 2. Storage Purge
    purge_resp = client.post(
        "/api/v1/storage/purge",
        json={"max_target_used_pct": 99.0, "dry_run": True},
    )
    assert purge_resp.status_code == 200

    # 3. Hardware Governor Status
    gov_resp = client.get("/api/v1/system/governor")
    assert gov_resp.status_code == 200
    gov_data = gov_resp.json()
    assert "state" in gov_data
    assert "load_factor" in gov_data

    # 4. Set Governor Load
    set_resp = client.post(
        "/api/v1/system/governor/load",
        json={"load_factor": 0.5},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["telemetry"]["load_factor"] == 0.5
