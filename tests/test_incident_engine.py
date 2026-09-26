"""
Unit Tests for Spatial Incident Detection Engine.
"""

import time
import pytest
from src.core.detector import Detection
from src.core.incident_engine import IncidentEngine
from src.core.tracker import SpatialTracker
from src.core.zone_manager import FlowVector, TrafficZone, ZoneManager


def test_zone_manager_point_containment():
    zm = ZoneManager()
    zone = TrafficZone(
        zone_id="test_zone",
        name="Test Zone",
        zone_type="lane",
        polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
        expected_flow=FlowVector(dx=0.0, dy=1.0),
    )
    zm.add_zone(zone)

    assert zone.contains_point((50, 50)) is True
    assert zone.contains_point((200, 200)) is False
    assert len(zm.get_zones_for_point((50, 50))) == 1


def test_wrong_way_incident_detection():
    incident_eng = IncidentEngine()
    incident_eng.suppression_cooldown_sec = 0.0  # disable suppression for testing
    tracker = SpatialTracker()
    zm = ZoneManager()

    # Southbound lane: expected flow is down (dy = 1.0)
    south_lane = TrafficZone(
        zone_id="south_lane",
        name="Southbound Lane",
        zone_type="lane",
        polygon=[(0, 0), (200, 0), (200, 800), (0, 800)],
        expected_flow=FlowVector(dx=0.0, dy=1.0),
    )
    zm.add_zone(south_lane)

    # Simulate car moving UP (y decreasing from 500 to 390)
    triggered_alerts = []
    for step in range(18):
        y = 500 - step * 6
        det = Detection(bbox=(50.0, float(y), 110.0, float(y + 60)), confidence=0.9, class_id=2, class_name="car")
        tracked = tracker.update([det])
        alerts = incident_eng.analyze_frame(
            frame_idx=step,
            detections=tracked,
            tracker=tracker,
            zone_manager=zm,
            fps=30.0,
        )
        triggered_alerts.extend(alerts)

    # Should detect wrong way alert
    wrong_way_alerts = [a for a in triggered_alerts if a.incident_type == "WRONG_WAY"]
    assert len(wrong_way_alerts) > 0
    assert wrong_way_alerts[0].severity == "CRITICAL"


def test_stalled_vehicle_detection():
    incident_eng = IncidentEngine(config={"incidents": {"stalled_vehicle": {"duration_seconds": 0.2}}})
    incident_eng.suppression_cooldown_sec = 0.0
    tracker = SpatialTracker()
    zm = ZoneManager()

    lane = TrafficZone(
        zone_id="lane_1",
        name="Main Lane",
        zone_type="lane",
        polygon=[(0, 0), (300, 0), (300, 300), (0, 300)],
    )
    zm.add_zone(lane)

    # Vehicle stationary at (100, 100) for 15 frames at 30 fps (0.5s > 0.2s threshold)
    triggered_alerts = []
    for step in range(15):
        det = Detection(bbox=(100.0, 100.0, 160.0, 160.0), confidence=0.9, class_id=2, class_name="car")
        tracked = tracker.update([det])
        alerts = incident_eng.analyze_frame(
            frame_idx=step,
            detections=tracked,
            tracker=tracker,
            zone_manager=zm,
            fps=30.0,
        )
        triggered_alerts.extend(alerts)

    stalled_alerts = [a for a in triggered_alerts if a.incident_type == "STALLED_VEHICLE"]
    assert len(stalled_alerts) > 0
    assert stalled_alerts[0].severity == "WARNING"
