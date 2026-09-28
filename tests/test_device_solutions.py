"""
ArgusTraffic AI - Device Fleet & Stream Optimization Test Suite
Validates:
- StreamRelayProxy single ingestion & dual-stream multiplexing
- FOVDriftDetector optical landmark baseline & displacement alerts
- ThermalAdaptiveScheduler dynamic motion gating & thermal throttling
- NTPTimeSyncGuard microsecond timestamp alignment for legal admissibility
- API device fleet status endpoints
"""

import time
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.core.device_manager import (
    StreamRelayProxy,
    FOVDriftDetector,
    ThermalAdaptiveScheduler,
    NTPTimeSyncGuard,
)

client = TestClient(app)


def test_stream_relay_proxy_multiplexing():
    """Verify single-ingestion stream multiplexer and bandwidth preservation."""
    proxy = StreamRelayProxy(
        camera_id="CAM-KANDY-01",
        rtsp_url="rtsp://192.168.1.100:554/live/ch0",
        sub_stream_url="rtsp://192.168.1.100:554/live/sub0",
    )
    assert proxy.active_subscribers == 0
    assert proxy.bandwidth_saved_mbps == 0.0

    # 4 workstation viewers connect
    sub1 = proxy.subscribe()
    sub2 = proxy.subscribe()
    sub3 = proxy.subscribe()
    assert proxy.active_subscribers == 3
    # 2 extra viewers saved from hitting camera hardware = 2 * 6.0 Mbps = 12.0 Mbps saved
    assert proxy.bandwidth_saved_mbps == 12.0

    # Publish frames
    main_frame = np.full((1080, 1920, 3), 200, dtype=np.uint8)
    sub_frame = np.full((360, 640, 3), 100, dtype=np.uint8)
    proxy.publish_frame(main_frame, is_main_stream=True)
    proxy.publish_frame(sub_frame, is_main_stream=False)

    ui_frame = proxy.get_broadcast_frame(for_ui_display=True)
    ai_frame = proxy.get_broadcast_frame(for_ui_display=False)

    assert ui_frame.shape == (360, 640, 3)
    assert ai_frame.shape == (1080, 1920, 3)

    telem = proxy.get_telemetry()
    assert telem["status"] == "ONLINE"
    assert telem["dual_stream_active"] is True
    assert telem["active_subscribers"] == 3


def test_fov_drift_detector_baseline_and_displacement():
    """Verify camera physical displacement watchdog using textured synthetic landmarks."""
    detector = FOVDriftDetector(shift_threshold_px=20.0)
    assert detector.is_calibrated is False

    # Create rich textured scene with grid landmarks
    base_frame = np.zeros((300, 400, 3), dtype=np.uint8)
    base_frame[::30, :] = 255
    base_frame[:, ::30] = 255
    base_frame[60:180, 80:240] = 180

    calibrated = detector.set_baseline(base_frame)
    assert calibrated is True
    assert detector.is_calibrated is True

    # Check nominal frame (same view)
    res_nominal = detector.check_drift(base_frame)
    assert res_nominal["displaced"] is False
    assert res_nominal["status"] == "NOMINAL"
    assert res_nominal["drift_px"] < 5.0

    # Displaced frame: shift scene by 45 pixels to simulate camera tilted by wind/impact
    shifted_frame = np.roll(base_frame, 45, axis=1)
    res_displaced = detector.check_drift(shifted_frame)
    assert res_displaced["displaced"] is True
    assert res_displaced["status"] == "DISPLACED_ALERT"
    assert res_displaced["drift_px"] > 20.0


def test_thermal_adaptive_scheduler_motion_gating():
    """Verify dynamic motion gating and emergency thermal throttling."""
    scheduler = ThermalAdaptiveScheduler(target_fps=30.0, idle_fps=3.0, motion_threshold=10.0)

    static_frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    # First frame always processes
    assert scheduler.should_process_frame(static_frame, edge_temp_celsius=50.0) is True

    # Consecutive identical frames represent an empty midnight corridor -> frames should be gated
    decimated_runs = [scheduler.should_process_frame(static_frame, edge_temp_celsius=50.0) for _ in range(9)]
    # Out of 9 static frames with 10:1 stride, only 1 should process
    assert sum(decimated_runs) <= 1

    # Active motion (vehicle entering scene)
    motion_frame = static_frame.copy()
    motion_frame[50:180, 50:200] = 255  # Vehicle patch
    assert scheduler.should_process_frame(motion_frame, edge_temp_celsius=50.0) is True

    # Thermal emergency (> 82 C)
    thermal_runs = [scheduler.should_process_frame(motion_frame, edge_temp_celsius=88.0) for _ in range(12)]
    # Under thermal throttle, forces 1 out of 6 frames (only 2 out of 12)
    assert sum(thermal_runs) == 2


def test_ntp_time_sync_guard():
    """Verify camera timestamp drift monitoring for legal court admissibility."""
    guard = NTPTimeSyncGuard(max_allowed_drift_sec=2.0)
    now = time.time()

    # Synchronized camera (drift = 0.15s)
    res_valid = guard.check_alignment(camera_timestamp=now - 0.15, system_time=now)
    assert res_valid["aligned"] is True
    assert res_valid["court_admissible"] is True
    assert res_valid["status"] == "SYNCHRONIZED"

    # Out of sync camera (drift = 6.5s)
    res_invalid = guard.check_alignment(camera_timestamp=now - 6.5, system_time=now)
    assert res_invalid["aligned"] is False
    assert res_invalid["court_admissible"] is False
    assert res_invalid["status"] == "CLOCK_DRIFT_EXCEEDED"


def test_api_device_endpoints():
    """Verify REST endpoints for relay status, drift, thermal, and time-sync."""
    # 1. Relay status
    r1 = client.get("/api/v1/devices/relay/status")
    assert r1.status_code == 200
    assert r1.json()["status"] == "OPERATIONAL"

    # 2. Drift status
    r2 = client.get("/api/v1/devices/drift/status")
    assert r2.status_code == 200
    assert r2.json()["fleet_status"] == "CALIBRATED_NOMINAL"

    # 3. Thermal status
    r3 = client.get("/api/v1/devices/thermal/status")
    assert r3.status_code == 200
    assert "edge_temperature_celsius" in r3.json()

    # 4. Time-sync status
    r4 = client.get("/api/v1/devices/time-sync/status")
    assert r4.status_code == 200
    assert r4.json()["sync_status"] == "SYNCHRONIZED"
