"""
ArgusTraffic AI - Advanced Fleet Operations Test Suite
Verifies:
1. 4-Point Homography perspective ground-plane speed calculation.
2. Webhook Dispatcher Exponential Backoff & Dead Letter Queue (DLQ) buffering.
3. Per-camera zone polygon persistence and reloading.
"""

import asyncio
import os
from pathlib import Path
import pytest

from src.core.dispatch import AlertDispatcher
from src.core.speed_engine import SpeedRadarEngine
from src.core.zone_manager import FlowVector, TrafficZone, ZoneManager


def test_speed_radar_homography_calibration():
    radar = SpeedRadarEngine(speed_limit_kmh=60.0)

    # 4-point trapezoid in image coordinates representing a 7.0m wide x 25.0m long road segment
    # (Tilted camera: top is narrower in pixel width due to perspective)
    src_quad = [
        (400.0, 150.0), # Top-Left
        (880.0, 150.0), # Top-Right (width = 480 px in image)
        (1100.0, 650.0),# Bottom-Right (width = 900 px in image)
        (200.0, 650.0), # Bottom-Left
    ]

    ok = radar.set_homography_calibration(
        source_quad=src_quad,
        physical_width_m=7.0,
        physical_length_m=25.0,
    )
    assert ok is True
    assert radar.homography_matrix is not None

    # Test projection of top-left and bottom-right
    wx1, wy1 = radar.project_point_to_world_meters(400.0, 150.0)
    assert abs(wx1 - 0.0) < 0.1
    assert abs(wy1 - 0.0) < 0.1

    wx2, wy2 = radar.project_point_to_world_meters(1100.0, 650.0)
    assert abs(wx2 - 7.0) < 0.1
    assert abs(wy2 - 25.0) < 0.1

    # Simulate vehicle traveling down the segment (25 meters in 1.0 second = 25 m/s = 90 km/h)
    radar.update_track(track_id=101, cx=400.0, cy=150.0, timestamp=100.0)
    speed = radar.update_track(track_id=101, cx=200.0, cy=650.0, timestamp=101.0)
    assert speed > 50.0 # Speed calculated using exact ground plane projection


@pytest.mark.asyncio
async def test_alert_dispatcher_dead_letter_queue():
    # Configure dispatcher with non-listening/failing webhook endpoint
    dispatcher = AlertDispatcher(webhook_url="http://127.0.0.1:59999/webhook/dead")
    dispatcher.start()

    alert_payload = {
        "alert_id": "ALERT-TEST-DLQ-01",
        "incident_type": "WRONG_WAY_DRIVING",
        "severity": "CRITICAL",
        "camera_id": "CAM-042",
    }

    # Dispatch directly
    success = await dispatcher._send_webhook(alert_payload)
    assert success is False
    assert dispatcher.total_failed >= 1

    # Verify DLQ buffering
    dlq = dispatcher.get_dead_letter_queue()
    assert len(dlq) >= 1
    assert dlq[0]["alert"]["alert_id"] == "ALERT-TEST-DLQ-01"
    assert dlq[0]["attempts"] == 3

    await dispatcher.stop()


def test_per_camera_persistent_zones(tmp_path):
    zm = ZoneManager(data_dir=str(tmp_path))

    # Add custom zone for CAM-101
    custom_zone = TrafficZone(
        zone_id="zone_restricted_cam101",
        name="CAM-101 Bus Lane",
        zone_type="lane",
        polygon=[(100.0, 100.0), (300.0, 100.0), (300.0, 400.0), (100.0, 400.0)],
        expected_flow=FlowVector(dx=0.0, dy=1.0),
        speed_limit_px=45.0,
    )

    zm.add_zone(custom_zone, camera_id="CAM-101")
    save_ok = zm.save_camera_zones("CAM-101")
    assert save_ok is True

    # Create new ZoneManager instance pointing to same directory
    zm2 = ZoneManager(data_dir=str(tmp_path))
    loaded = zm2.load_camera_zones("CAM-101")

    assert len(loaded) == 1
    assert loaded[0].zone_id == "zone_restricted_cam101"
    assert loaded[0].name == "CAM-101 Bus Lane"
    assert zm2.get_zones_for_point((200.0, 200.0), camera_id="CAM-101")[0].zone_id == "zone_restricted_cam101"
