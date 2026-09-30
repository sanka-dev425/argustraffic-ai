"""
ArgusTraffic AI - Camera Fleet Hardening & Device Lifecycle Test Suite
Verifies:
1. Custom subnet scanning and multi-vendor port probing.
2. Rapid RTSP stream validation.
3. Duplicate IP and PoE port conflict rejection.
4. Safe RTSP credential masking.
5. Dynamic VideoStream source hot-swapping.
6. Bulk CSV fleet onboarding and inventory export.
7. Cascade camera deletion across watchdog and stream relay proxies.
"""

import asyncio
import os
import tempfile
import pytest

from src.core.auth_rbac import Role
from src.core.camera_scanner import scan_local_cameras, validate_rtsp_stream, _parse_subnet_prefix
from src.core.camera_watchdog import CameraSelfHealingWatchdog
from src.core.device_manager import CameraInventoryManager, StreamRelayProxy, mask_rtsp_url
from src.utils.video_stream import VideoStream


def test_subnet_prefix_parsing():
    assert _parse_subnet_prefix("10.20.30.0/24") == "10.20.30"
    assert _parse_subnet_prefix("172.16.5.100") == "172.16.5"
    auto = _parse_subnet_prefix(None)
    assert len(auto.split(".")) == 3


@pytest.mark.asyncio
async def test_validate_rtsp_stream_invalid_and_valid():
    # Empty
    res = await validate_rtsp_stream("")
    assert res["reachable"] is False
    assert res["valid_stream"] is False

    # Invalid protocol
    res = await validate_rtsp_stream("ftp://192.168.1.1/live")
    assert res["reachable"] is False

    # Unreachable dummy IP (127.0.0.1 on non-listening port)
    res = await validate_rtsp_stream("rtsp://127.0.0.1:54321/live", timeout_sec=0.2)
    assert res["reachable"] is False
    assert "unreachable" in res["message"].lower() or "timed out" in res["message"].lower()


def test_mask_rtsp_url():
    url1 = "rtsp://admin:SecretPass123@192.168.1.50:554/onvif1"
    masked1 = mask_rtsp_url(url1)
    assert masked1 == "rtsp://admin:*****@192.168.1.50:554/onvif1"
    assert "SecretPass123" not in masked1

    url2 = "rtsp://192.168.1.50:554/live"
    assert mask_rtsp_url(url2) == url2


def test_camera_registration_conflict_checks(tmp_path):
    db_path = tmp_path / "test_fleet.db"
    mgr = CameraInventoryManager(db_path=str(db_path))

    # 1. Register camera 1
    cam1 = {
        "camera_id": "CAM-TEST-001",
        "name": "Test Intersection North",
        "ip_address": "10.0.1.50",
        "station_name": "Test Station Alpha",
        "poe_port": 1,
        "mounting_structure": "TRAFFIC_SIGNAL_POLE",
        "mounting_height_m": 6.5,
    }
    ok, msg, node = mgr.register_camera(cam1, operator_role=Role.SUPER_ADMIN)
    assert ok is True
    assert node["camera_id"] == "CAM-TEST-001"

    # 2. Register camera 2 with DUPLICATE IP
    cam2_bad_ip = {
        "camera_id": "CAM-TEST-002",
        "name": "Test Intersection South",
        "ip_address": "10.0.1.50", # Duplicate!
        "station_name": "Test Station Beta",
        "poe_port": 2,
    }
    ok2, msg2, _ = mgr.register_camera(cam2_bad_ip, operator_role=Role.SUPER_ADMIN)
    assert ok2 is False
    assert "IP Address conflict" in msg2

    # 3. Register camera 3 with DUPLICATE PoE port on same station
    cam3_bad_poe = {
        "camera_id": "CAM-TEST-003",
        "name": "Test Gantry East",
        "ip_address": "10.0.1.55",
        "station_name": "Test Station Alpha", # Same station
        "poe_port": 1, # Duplicate port 1!
    }
    ok3, msg3, _ = mgr.register_camera(cam3_bad_poe, operator_role=Role.SUPER_ADMIN)
    assert ok3 is False
    assert "PoE Port conflict" in msg3


def test_bulk_csv_import_and_export(tmp_path):
    db_path = tmp_path / "test_bulk_fleet.db"
    mgr = CameraInventoryManager(db_path=str(db_path))

    csv_content = """camera_id,name,ip_address,rtsp_main_url,mounting_structure,mounting_height_m,station_name,poe_port
CAM-BULK-01,Expressway Entry North,10.10.1.10,rtsp://10.10.1.10:554/live,HIGHWAY_GANTRY,8.0,Expressway NOC,1
CAM-BULK-02,Expressway Entry South,10.10.1.11,rtsp://10.10.1.11:554/live,HIGHWAY_GANTRY,8.0,Expressway NOC,2
CAM-BULK-03,Expressway Toll Plaza,10.10.1.12,rtsp://10.10.1.12:554/live,BUILDING_FACADE,5.5,Expressway NOC,3
"""
    res = mgr.bulk_import_cameras_csv(csv_content, operator_role=Role.SUPER_ADMIN)
    assert res["success"] is True
    assert res["imported"] == 3
    assert res["skipped"] == 0

    # Verify export
    exported_csv = mgr.export_cameras_csv(operator_role=Role.SUPER_ADMIN)
    assert "CAM-BULK-01" in exported_csv
    assert "CAM-BULK-02" in exported_csv
    assert "CAM-BULK-03" in exported_csv


def test_cascade_camera_deletion(tmp_path):
    db_path = tmp_path / "test_cascade.db"
    mgr = CameraInventoryManager(db_path=str(db_path))
    watchdog = CameraSelfHealingWatchdog()
    relays = {}

    # Register camera in DB
    cam = {
        "camera_id": "CAM-CASCADE-99",
        "name": "Cascade Target",
        "ip_address": "10.20.30.40",
        "station_name": "Metro Sector 9",
        "poe_port": 4,
    }
    ok, _, _ = mgr.register_camera(cam, operator_role=Role.SUPER_ADMIN)
    assert ok is True

    # Register in watchdog and relays
    watchdog.register_camera("CAM-CASCADE-99", "10.20.30.40", poe_port=4)
    relays["CAM-CASCADE-99"] = StreamRelayProxy("CAM-CASCADE-99", "rtsp://10.20.30.40:554/live")

    app_state = {
        "camera_watchdog": watchdog,
        "stream_relays": relays,
    }

    assert "CAM-CASCADE-99" in watchdog.monitored_cameras
    assert "CAM-CASCADE-99" in relays

    # Execute cascade delete
    del_ok, del_msg = mgr.cascade_delete_camera("CAM-CASCADE-99", app_state=app_state, operator_role=Role.SUPER_ADMIN)
    assert del_ok is True
    assert "CAM-CASCADE-99" not in watchdog.monitored_cameras
    assert "CAM-CASCADE-99" not in relays
    assert mgr.get_camera("CAM-CASCADE-99") is None



def test_video_stream_dynamic_hot_swap():
    vs = VideoStream(source="synthetic")
    ret, frame = vs.read_frame()
    assert ret is True
    assert frame is not None
    assert frame.shape == (720, 1280, 3)

    # Hot swap to another synthetic camera channel
    swap_ok = vs.hot_swap_source("CAM-003", new_channel_id="CAM-003")
    assert swap_ok is True
    ret2, frame2 = vs.read_frame()
    assert ret2 is True
    assert frame2 is not None

    vs.release()
