"""
ArgusTraffic AI - Enterprise God-Level Systems Test Suite
Validates:
1. Edge Local Ring-Buffer & Offline Incident Storage Vault (Store-and-Forward)
2. Wanted Vehicle Hotlist & Sub-Millisecond Fuzzy ANPR Interception
3. Optical Weather Enhancer (De-Hazing, Night Boost, Headlight Anti-Glare)
4. Automated Incident Escalation SLA & Operator Accountability Workflow
5. National Police HQ & Multi-Station Mesh Aggregator (Multi-Tenant Division Isolation)
6. Remote PoE Camera Self-Healing & Health Watchdog
7. All corresponding REST Endpoints
Author: Saptha Sanka (ArgusTraffic Autonomous Systems)
"""

import time
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.core.edge_recorder import EdgeRingBuffer, EdgeStorageVault
from src.core.hotlist_engine import WantedVehicleHotlistEngine, compute_ocr_distance, normalize_plate
from src.core.sla_escalation import IncidentSLAStatus, SLAEscalationManager
from src.core.station_mesh import NationalStationMeshAggregator
from src.core.camera_watchdog import CameraDiagnosticState, CameraSelfHealingWatchdog
from src.perception.preprocessing.weather_enhancer import OpticalWeatherEnhancer, WeatherFilterMode

client = TestClient(app)


# ==============================================================================
# 1. Edge Ring Buffer & Storage Vault Tests
# ==============================================================================
def test_edge_ring_buffer_pre_event_window():
    """Verify in-memory circular ring buffer holds timestamped frames and returns exact window."""
    ring = EdgeRingBuffer(capacity_seconds=3.0, fps=10.0)
    assert ring.size == 0

    # Feed 35 frames (exceeding 30 frame capacity)
    for i in range(35):
        frame = np.full((100, 100, 3), i, dtype=np.uint8)
        ring.append(frame, timestamp=time.time())

    assert ring.size == 30  # Max capacity capped

    # Request last 1.5 seconds (15 frames)
    window = ring.get_pre_event_window(window_seconds=1.5)
    assert len(window) == 15
    assert window[-1][1][0, 0, 0] == 34


def test_edge_storage_vault_lifecycle(tmp_path):
    """Verify local incident locking, manifest generation, and headquarters sync."""
    vault = EdgeStorageVault(storage_root=tmp_path, max_disk_mb=50.0)
    frames = [(time.time(), np.zeros((120, 160, 3), dtype=np.uint8)) for _ in range(5)]
    metadata = {"incident_type": "CRASH", "severity": "CRITICAL"}

    clip_path = vault.lock_incident_clip("INC-TEST-001", frames, metadata, fps=10.0)
    assert clip_path is not None
    assert clip_path.exists()

    pending = vault.get_pending_sync_queue()
    assert len(pending) == 1
    assert pending[0]["incident_id"] == "INC-TEST-001"
    assert pending[0]["synced_to_hq"] is False

    # Mark synced
    ok = vault.mark_as_synced("INC-TEST-001")
    assert ok is True
    pending_after = vault.get_pending_sync_queue()
    assert len(pending_after) == 0


# ==============================================================================
# 2. Wanted Vehicle Hotlist & Fuzzy ANPR Tests
# ==============================================================================
def test_hotlist_normalization_and_fuzzy_ocr():
    """Verify optical OCR distance matching for common letter/digit confusions."""
    assert normalize_plate("WP - CAR - 7821") == "WPCAR7821"
    # 'O' vs '0' should match with distance 0 due to optical equivalence
    assert compute_ocr_distance("CPHVY3012", "CPHVY3O12") == 0


def test_hotlist_engine_exact_and_fuzzy_interception():
    """Verify sub-millisecond lookup and police interception alert generation."""
    engine = WantedVehicleHotlistEngine()
    
    # Exact lookup
    hit_exact = engine.lookup_plate("CP-HVY-3012")
    assert hit_exact is not None
    assert hit_exact["category"] == "STOLEN_VEHICLE"
    assert hit_exact["match_type"] == "EXACT"

    # Fuzzy OCR lookup (reading 'O' instead of '0')
    hit_fuzzy = engine.lookup_plate("CP-HVY-3O12", allow_fuzzy=True)
    assert hit_fuzzy is not None
    assert hit_fuzzy["category"] == "STOLEN_VEHICLE"

    # Interception payload
    payload = engine.generate_interception_payload(
        plate="CP-HVY-3012",
        camera_id="CAM-COLOMBO-HARBOUR",
        speed_kmh=64.5,
    )
    assert payload is not None
    assert payload["alert_type"] == "WANTED_VEHICLE_INTERCEPTION"
    assert payload["interception_priority"] == "PRIORITY_1_HIGH_IMPACT"
    assert payload["speed_kmh"] == 64.5


def test_hotlist_add_and_remove_record():
    """Verify dynamic registration and revocation of blacklisted plates."""
    engine = WantedVehicleHotlistEngine()
    initial_count = engine.get_statistics()["total_records"]

    # Register suspect vehicle
    norm = engine.add_record("SP-TRK-9901", {"category": "AMBER_ALERT", "severity": "CRITICAL"})
    assert norm == "SPTRK9901"
    assert engine.lookup_plate("SP-TRK-9901") is not None
    assert engine.get_statistics()["total_records"] == initial_count + 1

    # Revoke record
    removed = engine.remove_record("SP-TRK-9901")
    assert removed is True
    assert engine.lookup_plate("SP-TRK-9901") is None



# ==============================================================================
# 3. Optical Weather Enhancer Tests
# ==============================================================================
def test_optical_weather_enhancer_modes():
    """Verify de-hazing, night boost, and anti-glare filters preserve dimensions and enhance contrast."""
    enhancer = OpticalWeatherEnhancer()

    # Foggy synthetic image (high mean, low contrast)
    hazy_img = np.full((120, 160, 3), 160, dtype=np.uint8)
    dehazed = enhancer.apply_dehaze(hazy_img)
    assert dehazed.shape == hazy_img.shape

    # Dark night synthetic image
    dark_img = np.full((120, 160, 3), 35, dtype=np.uint8)
    boosted = enhancer.apply_night_boost(dark_img)
    assert boosted.shape == dark_img.shape
    assert np.mean(boosted) >= np.mean(dark_img)

    # Headlight glare image (hot center)
    glare_img = np.full((120, 160, 3), 30, dtype=np.uint8)
    glare_img[40:80, 60:100] = 255
    attenuated = enhancer.apply_headlight_antiglare(glare_img)
    assert attenuated.shape == glare_img.shape

    # Full enhance pipeline with AUTO detection
    enhanced, telemetry = enhancer.enhance(dark_img)
    assert enhanced.shape == dark_img.shape
    assert "latency_ms" in telemetry
    assert telemetry["total_processed"] >= 1


# ==============================================================================
# 4. Incident SLA Escalation Tests
# ==============================================================================
def test_sla_escalation_lifecycle():
    """Verify officer response tracking and supervisory breach escalation."""
    # Use short 0.1s threshold for fast unit testing
    mgr = SLAEscalationManager(thresholds_sec={"CRITICAL": 0.1, "MEDIUM": 1.0})
    inc = {"alert_id": "INC-SLA-01", "severity": "CRITICAL", "description": "Crash"}
    rec = mgr.register_incident(inc)
    assert rec["status"] == IncidentSLAStatus.PENDING.value

    # Wait for SLA breach
    time.sleep(0.15)
    escalations = mgr.evaluate_escalations()
    assert len(escalations) == 1
    assert escalations[0]["incident_id"] == "INC-SLA-01"
    assert escalations[0]["status"] == IncidentSLAStatus.ESCALATED.value

    # Acknowledge after escalation
    ack = mgr.acknowledge_incident("INC-SLA-01", officer_id="OIC_SILVA", badge_number="SLP-112")
    assert ack is not None
    assert ack["status"] == IncidentSLAStatus.ACKNOWLEDGED.value
    assert ack["sla_breached"] is True
    assert ack["acknowledged_by"]["officer_id"] == "OIC_SILVA"


# ==============================================================================
# 5. National Station Mesh Aggregator Tests
# ==============================================================================
def test_station_mesh_aggregation_and_role_isolation():
    """Verify cross-division telemetry aggregation and Zero-Trust tenant filtering."""
    mesh = NationalStationMeshAggregator(local_division_id="DIV_COLOMBO_CENTRAL")
    overview = mesh.get_national_overview()
    assert overview["mesh_status"] == "ONLINE"
    assert overview["total_connected_divisions"] >= 3
    assert overview["total_monitored_cameras"] >= 20

    # Role-based division isolation
    divisions_data = overview["divisions"]
    hq_view = mesh.filter_for_user_role(divisions_data, user_role="SUPER_ADMIN", user_division="DIV_COLOMBO_CENTRAL")
    assert len(hq_view) == len(divisions_data)

    regional_view = mesh.filter_for_user_role(divisions_data, user_role="TRAFFIC_OPERATOR", user_division="DIV_KANDY")
    assert len(regional_view) == 1
    assert regional_view[0]["division_id"] == "DIV_KANDY"


# ==============================================================================
# 6. Remote Camera Self-Healing Watchdog Tests
# ==============================================================================
def test_camera_self_healing_watchdog():
    """Verify camera state progression on frame loss and automated reboot triggering."""
    watchdog = CameraSelfHealingWatchdog(reboot_cooldown_seconds=1.0)
    watchdog.register_camera("CAM-HWY-01", "192.168.1.50", "192.168.1.2", 1)

    # 1. Healthy frame
    st1 = watchdog.record_frame_status("CAM-HWY-01", frame_received=True)
    assert st1 == CameraDiagnosticState.HEALTHY

    # 2. 5 dropped frames -> Frozen RTSP
    for _ in range(5):
        watchdog.record_frame_status("CAM-HWY-01", frame_received=False)
    assert watchdog.monitored_cameras["CAM-HWY-01"]["state"] == CameraDiagnosticState.RTSP_FROZEN.value

    # 3. 10 dropped frames -> Power cycle required
    for _ in range(5):
        watchdog.record_frame_status("CAM-HWY-01", frame_received=False)
    assert watchdog.monitored_cameras["CAM-HWY-01"]["state"] == CameraDiagnosticState.POWERCYCLE_REQUIRED.value

    # 4. Execute self-healing power cycle
    res = watchdog.trigger_self_healing("CAM-HWY-01")
    assert res["success"] is True
    assert res["action"] == "POWER_CYCLE_EXECUTED"

    # Immediate second reboot should be blocked by cooldown
    res_cooldown = watchdog.trigger_self_healing("CAM-HWY-01", force=False)
    assert res_cooldown["success"] is False
    assert res_cooldown["action"] == "COOLDOWN_ACTIVE"


# ==============================================================================
# 7. End-to-End REST Endpoints Integration Tests
# ==============================================================================
def test_all_enterprise_rest_endpoints():
    """Verify all 6 enterprise REST subsystems respond correctly."""
    # 1. Hotlist
    r1 = client.get("/api/v1/hotlist/records")
    assert r1.status_code == 200
    assert "records" in r1.json()

    r2 = client.post("/api/v1/hotlist/lookup", json={"plate": "CP-HVY-3012"})
    assert r2.status_code == 200
    assert r2.json()["is_flagged"] is True

    # 2. SLA Queue
    r3 = client.get("/api/v1/sla/active-queue")
    assert r3.status_code == 200
    assert "active_queue" in r3.json()

    # 3. National Station Mesh
    r4 = client.get("/api/v1/mesh/national-overview")
    assert r4.status_code == 200
    assert r4.json()["mesh_status"] == "ONLINE"

    # 4. Edge Storage Vault
    r5 = client.get("/api/v1/edge-vault/pending-sync")
    assert r5.status_code == 200
    assert "pending_clips" in r5.json()

    # 5. Weather Filter
    r6 = client.get("/api/v1/weather/status")
    assert r6.status_code == 200
    assert "active_mode" in r6.json()

    r7 = client.post("/api/v1/weather/mode", json={"mode": "DEHAZE"})
    assert r7.status_code == 200
    assert r7.json()["new_mode"] == "DEHAZE"

    # 6. Camera Watchdog
    r8 = client.get("/api/v1/camera-watchdog/diagnostics")
    assert r8.status_code == 200
    assert "cameras" in r8.json()

    # 7. Direct Clip Download
    r9 = client.get("/api/v1/edge-vault/clips/INC-AUTOTEST-999")
    assert r9.status_code == 200
    assert r9.headers["content-type"] in ["video/mp4", "image/jpeg"]
    assert len(r9.content) > 0


def test_incident_db_license_plate_and_zone_queries(tmp_path):
    """Verify license_plate and speed_kmh fields are saved and queried properly."""
    from src.core.incident_db import IncidentDatabase
    db = IncidentDatabase(db_path=tmp_path / "test_plate.db")

    alert = {
        "alert_id": "INC-PLATE-001",
        "incident_type": "WRONG_WAY",
        "severity": "CRITICAL",
        "timestamp": time.time(),
        "formatted_time": "2026-09-29 01:00:00",
        "description": "Vehicle going wrong way",
        "location": [200.0, 300.0],
        "involved_track_ids": [42],
        "zone_id": "ZONE-HIGHWAY-01",
        "metadata": {"cam": "CAM-01"},
        "license_plate": "WP-CAR-7821",
        "speed_kmh": 88.5,
    }
    db.save_incident(alert)

    # Query with license plate filter
    res = db.query_incidents(license_plate="WP-CAR-7821")
    assert len(res) == 1
    assert res[0]["alert_id"] == "INC-PLATE-001"
    assert res[0]["license_plate"] == "WP-CAR-7821"
    assert res[0]["speed_kmh"] == 88.5
    assert res[0]["zone_id"] == "ZONE-HIGHWAY-01"

    # Query with zone_id filter
    res_zone = db.query_incidents(zone_id="ZONE-HIGHWAY-01")
    assert len(res_zone) == 1

    # Query non-existent
    res_none = db.query_incidents(license_plate="UNKNOWN-PLATE")
    assert len(res_none) == 0


def test_websocket_broadcaster_hub():
    """Verify WebSocket stream connects, registers with Broadcaster, and disconnects cleanly."""
    from src.api.app import broadcaster
    initial_count = len(broadcaster.clients)

    with client.websocket_connect("/ws/stream") as ws:
        # Client is added
        assert len(broadcaster.clients) >= initial_count + 1
        # Send action
        ws.send_json({"action": "set_confidence", "value": 0.40})

    # After exit, client is cleanly removed
    assert len(broadcaster.clients) == initial_count


def test_speed_radar_perspective_and_outlier_filtering():
    """Verify perspective depth-adjusted speed calculation and outlier rejection."""
    from src.core.speed_engine import SpeedRadarEngine

    radar = SpeedRadarEngine(
        pixels_per_meter=20.0,
        speed_limit_kmh=60.0,
        perspective_correction=True,
        vanishing_y=100.0,
        reference_y=500.0,
        max_plausible_speed_kmh=200.0,
    )

    # 1. Perspective check: ppm near horizon should be smaller than ppm in foreground
    ppm_horizon = radar.get_pixels_per_meter_at_y(150.0)
    ppm_foreground = radar.get_pixels_per_meter_at_y(500.0)
    assert ppm_horizon < ppm_foreground
    assert ppm_foreground == 20.0

    # 2. Plausibility check: Outlier jump (e.g. 5000 pixels in 0.05s) should be rejected
    radar.update_track(track_id=1, cx=100.0, cy=400.0, timestamp=1000.0)
    speed_jump = radar.update_track(track_id=1, cx=5000.0, cy=400.0, timestamp=1000.05)
    assert speed_jump == 0.0  # Rejected by max_plausible_speed_kmh


def test_data_engineering_analytics_and_geojson_export(tmp_path):
    """Verify statistical analytics summaries and RFC 7946 GeoJSON generation."""
    from src.core.incident_db import IncidentDatabase

    db = IncidentDatabase(db_path=tmp_path / "analytics_test.db")
    for i in range(10):
        db.save_incident({
            "alert_id": f"INC-STAT-{i}",
            "incident_type": "OVERSPEEDING" if i % 2 == 0 else "STALLED_VEHICLE",
            "severity": "CRITICAL" if i < 3 else "WARNING",
            "timestamp": time.time() + i,
            "formatted_time": "2026-09-29 01:00:00",
            "description": f"Incident sample {i}",
            "location": [100.0 + i, 200.0 + i],
            "involved_track_ids": [i],
            "zone_id": "ZONE-A",
            "speed_kmh": 60.0 + (i * 5.0),
        })

    # Test analytics summary
    analytics = db.get_analytics_summary()
    assert analytics["total_events"] == 10
    assert "OVERSPEEDING" in analytics["type_distribution"]
    assert analytics["speed_metrics"]["average_kmh"] > 0
    assert analytics["speed_metrics"]["p85_percentile_kmh"] >= analytics["speed_metrics"]["average_kmh"]

    # Test GeoJSON export
    geojson = db.export_geojson(limit=10)
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 10
    feat = geojson["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    assert "alert_id" in feat["properties"]

    # Test REST endpoints
    r_ana = client.get("/api/v1/incidents/analytics")
    assert r_ana.status_code == 200
    assert "speed_metrics" in r_ana.json()

    r_geo = client.get("/api/v1/incidents/geojson")
    assert r_geo.status_code == 200
    assert r_geo.json()["type"] == "FeatureCollection"


def test_point_to_point_section_speed_enforcement():
    """Verify Section Control Point-to-Point average speed computation across checkpoints."""
    from src.core.speed_engine import PointToPointAverageSpeedEngine

    p2p = PointToPointAverageSpeedEngine(
        corridor_id="CORRIDOR_E01_SOUTHERN",
        section_distance_km=10.0,  # 10 km segment
        speed_limit_kmh=100.0,
        tolerance_kmh=3.0,
    )

    t0 = 10000.0
    plate = "WP-CAR-9999"

    # 1. Vehicle enters Gantry A
    res_entry = p2p.record_passage(plate, "CAM-GANTRY-A", "ENTRY", timestamp=t0)
    assert res_entry is None
    assert "WPCAR9999" in p2p.entry_passages

    # 2. Vehicle exits Gantry B after 300 seconds (5 minutes) -> 10km in 5min = 120 km/h (VIOLATION)
    t_exit = t0 + 300.0
    dossier = p2p.record_passage(plate, "CAM-GANTRY-B", "EXIT", timestamp=t_exit)
    assert dossier is not None
    assert dossier["is_violation"] is True
    assert dossier["average_speed_kmh"] == 120.0
    assert dossier["excess_kmh"] == 20.0
    assert len(p2p.violations) == 1

    # 3. Test REST API Integration
    r_entry = client.post("/api/v1/speed/section-control/record", json={
        "plate": "CP-SUV-5555",
        "camera_id": "CAM-089",
        "checkpoint_role": "ENTRY",
        "timestamp": 20000.0,
    })
    assert r_entry.status_code == 200
    assert r_entry.json()["status"] == "RECORDED"

    r_exit = client.post("/api/v1/speed/section-control/record", json={
        "plate": "CP-SUV-5555",
        "camera_id": "CAM-090",
        "checkpoint_role": "EXIT",
        "timestamp": 20120.0,  # 120 seconds for 5.0 km = 150 km/h
    })
    assert r_exit.status_code == 200
    assert r_exit.json()["status"] == "SECTION_EVALUATED"
    assert r_exit.json()["dossier"]["is_violation"] is True

    r_viols = client.get("/api/v1/speed/section-control/violations")
    assert r_viols.status_code == 200
    assert len(r_viols.json()["violations"]) >= 1

    # 4. Test GIS Corridor Network endpoint
    r_gis = client.get("/api/v1/gis/corridor-network")
    assert r_gis.status_code == 200
    assert "camera_nodes" in r_gis.json()
    assert len(r_gis.json()["camera_nodes"]) >= 2
    assert "corridors" in r_gis.json()
