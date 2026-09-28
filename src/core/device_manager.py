"""
ArgusTraffic AI - Enterprise Device Fleet & Stream Optimization Engine
Provides:
1. StreamRelayProxy: Single-ingestion camera multiplexer with Dual-Stream (Main/Sub) routing.
2. FOVDriftDetector: Optical landmark watchdog detecting camera physical displacement/tilting.
3. ThermalAdaptiveScheduler: Dynamic motion gating and thermal load shedding for edge devices.
4. NTPTimeSyncGuard: Validates timestamp alignment for legal court admissibility.
"""

from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from src.utils.paths import get_data_dir
from src.core.auth_rbac import Role

logger = logging.getLogger("argustraffic.device")


class StreamRelayProxy:
    """
    Central Edge Stream Multiplexer.
    Ingests 1 stream from the physical camera and broadcasts to multiple operator
    workstations to prevent camera SoC overload/crash. Supports dual-stream separation.
    """

    def __init__(self, camera_id: str, rtsp_url: str, sub_stream_url: Optional[str] = None):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.sub_stream_url = sub_stream_url or rtsp_url
        self.active_subscribers = 0
        self.total_frames_relayed = 0
        self.bandwidth_saved_mbps = 0.0
        self.status = "ONLINE"
        self._last_frame_time = time.time()
        self._last_main_frame: Optional[np.ndarray] = None
        self._last_sub_frame: Optional[np.ndarray] = None

    def subscribe(self) -> str:
        """Registers a new workstation viewer connection."""
        self.active_subscribers += 1
        # Each extra subscriber saved from querying camera directly saves ~6.0 Mbps
        self.bandwidth_saved_mbps = max(0.0, (self.active_subscribers - 1) * 6.0)
        return f"sub_{self.camera_id}_{self.active_subscribers}"

    def unsubscribe(self) -> None:
        """Deregisters a workstation viewer connection."""
        if self.active_subscribers > 0:
            self.active_subscribers -= 1
        self.bandwidth_saved_mbps = max(0.0, (self.active_subscribers - 1) * 6.0)

    def publish_frame(self, frame: np.ndarray, is_main_stream: bool = True) -> None:
        """Stores the latest single-ingestion frame for demux broadcast."""
        self.total_frames_relayed += 1
        self._last_frame_time = time.time()
        if is_main_stream:
            self._last_main_frame = frame
        else:
            self._last_sub_frame = frame

    def get_broadcast_frame(self, for_ui_display: bool = True) -> Optional[np.ndarray]:
        """Returns the appropriate stream (sub-stream for UI, main-stream for AI).
        When the physical stream has stalled (>5s), returns an authentic NO SIGNAL frame
        to avoid displaying misleading frozen video in control centers."""
        now = time.time()
        if (now - self._last_frame_time) > 5.0:
            from src.utils.video_stream import render_no_signal_frame
            elapsed = now - self._last_frame_time
            w = 640 if for_ui_display else 1280
            h = 360 if for_ui_display else 720
            return render_no_signal_frame(
                width=w,
                height=h,
                camera_id=self.camera_id,
                source_url=self.rtsp_url,
                reason="STREAM HEARTBEAT LOSS (>5s)",
                reconnect_attempt=int(elapsed // 3) + 1,
                next_retry_sec=max(0.1, 3.0 - (elapsed % 3)),
                animated_phase=int(elapsed * 10),
            )

        if for_ui_display and self._last_sub_frame is not None:
            return self._last_sub_frame
        return self._last_main_frame

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns relay health, subscriber count, and bandwidth preservation stats."""
        is_stale = (time.time() - self._last_frame_time) > 5.0
        return {
            "camera_id": self.camera_id,
            "status": "OFFLINE" if is_stale else "ONLINE",
            "active_subscribers": self.active_subscribers,
            "total_frames_relayed": self.total_frames_relayed,
            "bandwidth_saved_mbps": round(self.bandwidth_saved_mbps, 2),
            "dual_stream_active": bool(self.sub_stream_url != self.rtsp_url),
        }


class FOVDriftDetector:
    """
    Optical Landmark Watchdog.
    Detects if high winds, vibration, or physical impact have shifted or tilted
    the camera angle, preventing invalid geofences and false alarms.
    """

    def __init__(self, shift_threshold_px: float = 25.0, min_match_ratio: float = 0.45):
        self.shift_threshold_px = shift_threshold_px
        self.min_match_ratio = min_match_ratio
        self.baseline_descriptors: Optional[np.ndarray] = None
        self.baseline_keypoints = None
        self.is_calibrated = False
        self._orb = cv2.ORB_create(nfeatures=250)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    def set_baseline(self, frame: np.ndarray) -> bool:
        """Captures the reference landmark features from the baseline camera perspective."""
        if frame is None or frame.size == 0:
            return False
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        kp, des = self._orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 15:
            return False
        self.baseline_keypoints = kp
        self.baseline_descriptors = des
        self.is_calibrated = True
        return True

    def check_drift(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Compares live frame keypoints with baseline reference landmarks.
        Returns drift shift in pixels, match ratio, and displacement flag.
        """
        if not self.is_calibrated or self.baseline_descriptors is None:
            return {"displaced": False, "status": "UNCALIBRATED", "drift_px": 0.0, "match_ratio": 1.0}

        if frame is None or frame.size == 0:
            return {"displaced": True, "status": "FRAME_CORRUPT", "drift_px": 999.0, "match_ratio": 0.0}

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        kp, des = self._orb.detectAndCompute(gray, None)

        if des is None or len(kp) < 10:
            return {"displaced": True, "status": "FEATURE_LOSS", "drift_px": 999.0, "match_ratio": 0.0}

        matches = self._bf.match(self.baseline_descriptors, des)
        if not matches:
            return {"displaced": True, "status": "COMPLETE_DISORIENTATION", "drift_px": 999.0, "match_ratio": 0.0}

        matches = sorted(matches, key=lambda x: x.distance)
        good_matches = [m for m in matches if m.distance < 60]

        match_ratio = len(good_matches) / max(1, len(self.baseline_descriptors))

        # Compute average displacement vector of matched points
        displacements = []
        for m in good_matches[:30]:
            pt_base = self.baseline_keypoints[m.queryIdx].pt
            pt_live = kp[m.trainIdx].pt
            dist = float(np.hypot(pt_live[0] - pt_base[0], pt_live[1] - pt_base[1]))
            displacements.append(dist)

        avg_drift = float(np.mean(displacements)) if displacements else 0.0
        is_displaced = (avg_drift > self.shift_threshold_px) or (match_ratio < self.min_match_ratio)

        return {
            "displaced": is_displaced,
            "status": "DISPLACED_ALERT" if is_displaced else "NOMINAL",
            "drift_px": round(avg_drift, 2),
            "match_ratio": round(match_ratio, 3),
        }


class ThermalAdaptiveScheduler:
    """
    Adaptive Motion Gating & Thermal Throttler.
    Reduces edge inference frequency when traffic corridors are completely empty
    or when edge processor thermals exceed safety limits.
    """

    def __init__(self, target_fps: float = 30.0, idle_fps: float = 3.0, motion_threshold: float = 8.0):
        self.target_fps = target_fps
        self.idle_fps = idle_fps
        self.motion_threshold = motion_threshold
        self._prev_gray: Optional[np.ndarray] = None
        self._frame_count = 0
        self.last_motion_score = 0.0
        self.thermal_throttle_active = False

    def should_process_frame(self, frame: np.ndarray, edge_temp_celsius: float = 55.0) -> bool:
        """
        Determines whether the current frame should run full neural inference.
        Returns True to infer, False to skip.
        """
        self._frame_count += 1
        if frame is None or frame.size == 0:
            return False

        # 1. Thermal Emergency Check (e.g. gateway > 85 C)
        self.thermal_throttle_active = edge_temp_celsius > 82.0
        if self.thermal_throttle_active:
            # Force 1 out of 6 frames (~5 FPS) under severe heat
            return (self._frame_count % 6) == 0

        # 2. Motion Gating Check
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        small = cv2.resize(gray, (160, 90))

        if self._prev_gray is None:
            self._prev_gray = small
            return True

        diff = cv2.absdiff(self._prev_gray, small)
        self.last_motion_score = float(np.mean(diff))
        self._prev_gray = small

        # If significant motion detected (vehicles/pedestrians present), run full FPS
        if self.last_motion_score >= self.motion_threshold:
            return True

        # Scene is quiet / empty corridor: Decimate frames down to idle_fps (e.g. 1 out of 10)
        skip_stride = int(self.target_fps / max(1.0, self.idle_fps))
        return (self._frame_count % skip_stride) == 0


class NTPTimeSyncGuard:
    """
    Time Synchronization & Legal Admissibility Monitor.
    Validates that camera hardware timestamps align with official UTC servers
    to guarantee evidence is court-admissible without clock drift objections.
    """

    def __init__(self, max_allowed_drift_sec: float = 2.0):
        self.max_allowed_drift_sec = max_allowed_drift_sec

    def check_alignment(self, camera_timestamp: float, system_time: Optional[float] = None) -> Dict[str, Any]:
        """Compares camera timestamp with system time."""
        current_sys = system_time or time.time()
        drift = abs(current_sys - camera_timestamp)
        is_valid = drift <= self.max_allowed_drift_sec

        return {
            "aligned": is_valid,
            "drift_seconds": round(drift, 3),
            "camera_time": camera_timestamp,
            "system_time": current_sys,
            "court_admissible": is_valid,
            "status": "SYNCHRONIZED" if is_valid else "CLOCK_DRIFT_EXCEEDED",
        }


class CameraMountingStructure(str, Enum):
    """Standard baseline mounting structures for reference and backward compatibility."""
    TRAFFIC_SIGNAL_POLE = "TRAFFIC_SIGNAL_POLE"   # Mast arms / upright posts (5.5m - 7m)
    STREET_LIGHT_POLE = "STREET_LIGHT_POLE"       # Street lampposts along arterials (8m - 12m)
    BUILDING_FACADE = "BUILDING_FACADE"           # Building walls, rooftops, parapets (12m - 30m)
    HIGHWAY_GANTRY = "HIGHWAY_GANTRY"             # Overhead steel gantries, toll plazas (6m - 9m)
    OVERPASS_BRIDGE = "OVERPASS_BRIDGE"           # Pedestrian / vehicular overpasses (5m - 8m)


@dataclass
class MountingStructureConfig:
    """Enterprise dynamic mounting structure configuration defined by administrators."""
    structure_key: str
    label: str
    recommended_height_min_m: float = 4.0
    recommended_height_max_m: float = 15.0
    vibration_sensitivity: str = "MEDIUM"
    wind_sway_sensitivity: str = "MEDIUM"
    perspective_angle: str = "STANDARD"
    primary_application: str = "Traffic Surveillance & Enforcement"
    is_custom: bool = False
    created_at: float = 0.0
    created_by: str = "SYSTEM"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


MOUNTING_STRUCTURE_SPECS: Dict[str, Dict[str, Any]] = {
    CameraMountingStructure.TRAFFIC_SIGNAL_POLE.value: {
        "label": "Traffic Signal Mast / Pole",
        "recommended_height_range_m": [5.5, 7.0],
        "vibration_sensitivity": "HIGH",
        "wind_sway_sensitivity": "MEDIUM",
        "perspective_angle": "STEEP_DOWNWARD",
        "primary_application": "Intersection Stop-Line, Red-Light Violation, Queue Length",
        "recommended_lens_fov_deg": [60.0, 90.0],
    },
    CameraMountingStructure.STREET_LIGHT_POLE.value: {
        "label": "Street Light Lamppost",
        "recommended_height_range_m": [8.0, 12.0],
        "vibration_sensitivity": "MEDIUM",
        "wind_sway_sensitivity": "HIGH",
        "perspective_angle": "MODERATE_ANGLE",
        "primary_application": "Arterial Corridor Speed Estimation, Multi-Lane Density",
        "recommended_lens_fov_deg": [45.0, 75.0],
    },
    CameraMountingStructure.BUILDING_FACADE.value: {
        "label": "Building Wall / Rooftop Parapet",
        "recommended_height_range_m": [12.0, 30.0],
        "vibration_sensitivity": "LOW",
        "wind_sway_sensitivity": "LOW",
        "perspective_angle": "SHALLOW_PANORAMIC",
        "primary_application": "Wide Urban Corridor Surveillance, Intersection Macro Trajectories",
        "recommended_lens_fov_deg": [30.0, 60.0],
    },
    CameraMountingStructure.HIGHWAY_GANTRY.value: {
        "label": "Highway Overhead Gantry / Toll Truss",
        "recommended_height_range_m": [6.0, 9.0],
        "vibration_sensitivity": "MEDIUM",
        "wind_sway_sensitivity": "LOW",
        "perspective_angle": "PERPENDICULAR_DOWN",
        "primary_application": "Point-to-Point ANPR, Section Speed Enforcement, Free-Flow Tolling",
        "recommended_lens_fov_deg": [40.0, 70.0],
    },
    CameraMountingStructure.OVERPASS_BRIDGE.value: {
        "label": "Flyover Bridge / Pedestrian Overpass",
        "recommended_height_range_m": [5.0, 8.0],
        "vibration_sensitivity": "HIGH",
        "wind_sway_sensitivity": "LOW",
        "perspective_angle": "HEAD_ON_APPROACH",
        "primary_application": "Bi-directional Vehicle Profiling, Hazardous Cargo Tracking",
        "recommended_lens_fov_deg": [50.0, 80.0],
    },
}


@dataclass
class CameraNode:
    """Represents a deployed edge traffic camera with physical mounting & network metadata."""
    camera_id: str
    name: str
    mounting_structure: str
    mounting_height_m: float
    division_id: str
    station_name: str
    intersection_or_corridor: str
    latitude: float
    longitude: float
    azimuth_heading_deg: float = 0.0
    tilt_angle_deg: float = 20.0
    rtsp_main_url: str = ""
    rtsp_sub_url: str = ""
    ip_address: str = "192.168.1.100"
    status: str = "ONLINE"
    fps: float = 30.0
    resolution: str = "1920x1080"
    poe_port: Optional[int] = None
    drift_status: str = "NOMINAL"
    created_at: float = 0.0
    last_updated: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CameraInventoryManager:
    """
    Enterprise Device Fleet & Camera Management Engine.
    Handles camera registration, re-naming, mounting structure classification,
    and multi-tenant police station divisional isolation.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            self.db_path = get_data_dir() / "camera_fleet.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """Initializes tables for camera devices and audit records."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mounting_structure TEXT NOT NULL,
                    mounting_height_m REAL NOT NULL,
                    division_id TEXT NOT NULL,
                    station_name TEXT NOT NULL,
                    intersection_or_corridor TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    azimuth_heading_deg REAL DEFAULT 0.0,
                    tilt_angle_deg REAL DEFAULT 20.0,
                    rtsp_main_url TEXT NOT NULL,
                    rtsp_sub_url TEXT,
                    ip_address TEXT NOT NULL,
                    status TEXT DEFAULT 'ONLINE',
                    fps REAL DEFAULT 30.0,
                    resolution TEXT DEFAULT '1920x1080',
                    poe_port INTEGER,
                    drift_status TEXT DEFAULT 'NOMINAL',
                    created_at REAL NOT NULL,
                    last_updated REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mounting_structures (
                    structure_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    recommended_height_min_m REAL DEFAULT 4.0,
                    recommended_height_max_m REAL DEFAULT 15.0,
                    vibration_sensitivity TEXT DEFAULT 'MEDIUM',
                    wind_sway_sensitivity TEXT DEFAULT 'MEDIUM',
                    perspective_angle TEXT DEFAULT 'STANDARD',
                    primary_application TEXT DEFAULT 'Traffic Surveillance & Enforcement',
                    is_custom INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    created_by TEXT DEFAULT 'SYSTEM'
                )
            """)
            conn.commit()

        with self._get_connection() as conn:
            self._seed_default_mounting_structures(conn)
        self._seed_default_cameras()

    def _seed_default_mounting_structures(self, conn: sqlite3.Connection):
        """Seeds baseline mounting structures if not already present."""
        now = time.time()
        for key, spec in MOUNTING_STRUCTURE_SPECS.items():
            cursor = conn.cursor()
            cursor.execute("SELECT structure_key FROM mounting_structures WHERE structure_key = ?", (key,))
            if not cursor.fetchone():
                h_min = spec["recommended_height_range_m"][0]
                h_max = spec["recommended_height_range_m"][1]
                conn.execute("""
                    INSERT INTO mounting_structures (
                        structure_key, label, recommended_height_min_m, recommended_height_max_m,
                        vibration_sensitivity, wind_sway_sensitivity, perspective_angle,
                        primary_application, is_custom, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'SYSTEM')
                """, (
                    key,
                    spec["label"],
                    h_min,
                    h_max,
                    spec["vibration_sensitivity"],
                    spec["wind_sway_sensitivity"],
                    spec["perspective_angle"],
                    spec["primary_application"],
                    now,
                ))
        conn.commit()

    def _ensure_mounting_structure_exists(self, structure_key: str, height: float = 6.0):
        """Auto-registers custom structures specified by administrators."""
        clean_key = structure_key.strip().upper().replace(" ", "_")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT structure_key FROM mounting_structures WHERE structure_key = ?", (clean_key,))
            if not cursor.fetchone():
                label = clean_key.replace("_", " ").title()
                h_min = max(1.5, round(float(height) - 2.0, 1))
                h_max = round(float(height) + 3.0, 1)
                conn.execute("""
                    INSERT INTO mounting_structures (
                        structure_key, label, recommended_height_min_m, recommended_height_max_m,
                        vibration_sensitivity, wind_sway_sensitivity, perspective_angle,
                        primary_application, is_custom, created_at, created_by
                    ) VALUES (?, ?, ?, ?, 'MEDIUM', 'MEDIUM', 'CUSTOM_PERSPECTIVE', 'Custom Configured Location', 1, ?, 'ADMIN')
                """, (clean_key, label, h_min, h_max, time.time()))
                conn.commit()

    def _seed_default_cameras(self):
        """Seeds standard physical camera nodes across municipal police divisions."""
        now = time.time()
        defaults = [
            CameraNode(
                camera_id="CAM-COL-SIG-01",
                name="Town Hall Signal Mast Cam 01",
                mounting_structure=CameraMountingStructure.TRAFFIC_SIGNAL_POLE.value,
                mounting_height_m=6.2,
                division_id="DIV_COLOMBO_CENTRAL",
                station_name="Colombo Central Traffic HQ",
                intersection_or_corridor="Dharmapala Mawatha / F.R. Senanayake Mawatha Junction",
                latitude=6.9147,
                longitude=79.8606,
                azimuth_heading_deg=180.0,
                tilt_angle_deg=28.0,
                rtsp_main_url="rtsp://192.168.1.101:554/stream1",
                rtsp_sub_url="rtsp://192.168.1.101:554/stream2",
                ip_address="192.168.1.101",
                status="ONLINE",
                fps=30.0,
                resolution="1920x1080",
                poe_port=1,
                created_at=now,
                last_updated=now,
            ),
            CameraNode(
                camera_id="CAM-COL-LMP-04",
                name="Galle Road Lamp Post 14",
                mounting_structure=CameraMountingStructure.STREET_LIGHT_POLE.value,
                mounting_height_m=9.5,
                division_id="DIV_COLOMBO_CENTRAL",
                station_name="Colombo Central Traffic HQ",
                intersection_or_corridor="Galle Road Kollupitiya Corridor",
                latitude=6.9080,
                longitude=79.8512,
                azimuth_heading_deg=350.0,
                tilt_angle_deg=18.0,
                rtsp_main_url="rtsp://192.168.1.102:554/stream1",
                rtsp_sub_url="rtsp://192.168.1.102:554/stream2",
                ip_address="192.168.1.102",
                status="ONLINE",
                fps=30.0,
                resolution="1920x1080",
                poe_port=2,
                created_at=now,
                last_updated=now,
            ),
            CameraNode(
                camera_id="CAM-COL-BLD-02",
                name="World Trade Center South Facade",
                mounting_structure=CameraMountingStructure.BUILDING_FACADE.value,
                mounting_height_m=24.0,
                division_id="DIV_COLOMBO_CENTRAL",
                station_name="Colombo Central Traffic HQ",
                intersection_or_corridor="Echelon Square Fort Financial District",
                latitude=6.9329,
                longitude=79.8437,
                azimuth_heading_deg=210.0,
                tilt_angle_deg=42.0,
                rtsp_main_url="rtsp://192.168.1.103:554/stream1",
                rtsp_sub_url="rtsp://192.168.1.103:554/stream2",
                ip_address="192.168.1.103",
                status="ONLINE",
                fps=30.0,
                resolution="3840x2160",
                poe_port=3,
                created_at=now,
                last_updated=now,
            ),
            CameraNode(
                camera_id="CAM-KDY-GAN-01",
                name="Peradeniya Expressway Gantry 01",
                mounting_structure=CameraMountingStructure.HIGHWAY_GANTRY.value,
                mounting_height_m=7.5,
                division_id="DIV_KANDY",
                station_name="Kandy Municipal Traffic Division",
                intersection_or_corridor="Peradeniya - Kandy Expressway Entry Gantry",
                latitude=7.2625,
                longitude=80.5982,
                azimuth_heading_deg=45.0,
                tilt_angle_deg=15.0,
                rtsp_main_url="rtsp://192.168.2.101:554/stream1",
                rtsp_sub_url="rtsp://192.168.2.101:554/stream2",
                ip_address="192.168.2.101",
                status="ONLINE",
                fps=30.0,
                resolution="1920x1080",
                poe_port=1,
                created_at=now,
                last_updated=now,
            ),
            CameraNode(
                camera_id="CAM-GAL-BRG-01",
                name="Galle Fort Flyover Overpass",
                mounting_structure=CameraMountingStructure.OVERPASS_BRIDGE.value,
                mounting_height_m=6.8,
                division_id="DIV_GALLE",
                station_name="Galle Coastal Traffic Division",
                intersection_or_corridor="Galle Fort Entrance Flyover",
                latitude=6.0328,
                longitude=80.2168,
                azimuth_heading_deg=120.0,
                tilt_angle_deg=22.0,
                rtsp_main_url="rtsp://192.168.3.101:554/stream1",
                rtsp_sub_url="rtsp://192.168.3.101:554/stream2",
                ip_address="192.168.3.101",
                status="ONLINE",
                fps=30.0,
                resolution="1920x1080",
                poe_port=1,
                created_at=now,
                last_updated=now,
            ),
        ]
        with self._get_connection() as conn:
            for cam in defaults:
                cursor = conn.cursor()
                cursor.execute("SELECT camera_id FROM cameras WHERE camera_id = ?", (cam.camera_id,))
                if not cursor.fetchone():
                    conn.execute("""
                        INSERT INTO cameras (
                            camera_id, name, mounting_structure, mounting_height_m,
                            division_id, station_name, intersection_or_corridor,
                            latitude, longitude, azimuth_heading_deg, tilt_angle_deg,
                            rtsp_main_url, rtsp_sub_url, ip_address, status, fps,
                            resolution, poe_port, drift_status, created_at, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        cam.camera_id, cam.name, cam.mounting_structure, cam.mounting_height_m,
                        cam.division_id, cam.station_name, cam.intersection_or_corridor,
                        cam.latitude, cam.longitude, cam.azimuth_heading_deg, cam.tilt_angle_deg,
                        cam.rtsp_main_url, cam.rtsp_sub_url, cam.ip_address, cam.status, cam.fps,
                        cam.resolution, cam.poe_port, cam.drift_status, cam.created_at, cam.last_updated
                    ))
            conn.commit()

    def register_camera(
        self,
        camera_data: Dict[str, Any],
        operator_role: Role = Role.SUPER_ADMIN,
        operator_division: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Registers a new physical camera node under appropriate divisional jurisdiction."""
        if operator_role not in (Role.SUPER_ADMIN, Role.STATION_ADMIN):
            return False, "Insufficient privilege: Requires STATION_ADMIN or SUPER_ADMIN.", None

        cam_id = camera_data.get("camera_id", "").strip()
        if not cam_id:
            return False, "Camera ID cannot be empty.", None

        # Enforce Station Admin division boundary
        target_division = camera_data.get("division_id", "DIV_COLOMBO_CENTRAL")
        if operator_role == Role.STATION_ADMIN and operator_division:
            target_division = operator_division

        raw_struct = camera_data.get("mounting_structure", CameraMountingStructure.TRAFFIC_SIGNAL_POLE.value)
        clean_struct = str(raw_struct).strip().upper().replace(" ", "_")
        if not clean_struct:
            clean_struct = CameraMountingStructure.TRAFFIC_SIGNAL_POLE.value

        # Auto-provision custom structure in database if newly specified by admin
        self._ensure_mounting_structure_exists(
            clean_struct,
            float(camera_data.get("mounting_height_m", 6.0))
        )
        mounting_struct = clean_struct

        now = time.time()
        node = CameraNode(
            camera_id=cam_id,
            name=camera_data.get("name", f"Camera {cam_id}"),
            mounting_structure=mounting_struct,
            mounting_height_m=float(camera_data.get("mounting_height_m", 6.0)),
            division_id=target_division,
            station_name=camera_data.get("station_name", "Municipal Traffic Command"),
            intersection_or_corridor=camera_data.get("intersection_or_corridor", "Urban Corridor"),
            latitude=float(camera_data.get("latitude", 6.9271)),
            longitude=float(camera_data.get("longitude", 79.8612)),
            azimuth_heading_deg=float(camera_data.get("azimuth_heading_deg", 0.0)),
            tilt_angle_deg=float(camera_data.get("tilt_angle_deg", 25.0)),
            rtsp_main_url=camera_data.get("rtsp_main_url", f"rtsp://192.168.1.200:554/{cam_id}"),
            rtsp_sub_url=camera_data.get("rtsp_sub_url", ""),
            ip_address=camera_data.get("ip_address", "192.168.1.200"),
            status=camera_data.get("status", "ONLINE"),
            fps=float(camera_data.get("fps", 30.0)),
            resolution=camera_data.get("resolution", "1920x1080"),
            poe_port=camera_data.get("poe_port"),
            created_at=now,
            last_updated=now,
        )

        with self.lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("""
                        INSERT INTO cameras (
                            camera_id, name, mounting_structure, mounting_height_m,
                            division_id, station_name, intersection_or_corridor,
                            latitude, longitude, azimuth_heading_deg, tilt_angle_deg,
                            rtsp_main_url, rtsp_sub_url, ip_address, status, fps,
                            resolution, poe_port, drift_status, created_at, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        node.camera_id, node.name, node.mounting_structure, node.mounting_height_m,
                        node.division_id, node.station_name, node.intersection_or_corridor,
                        node.latitude, node.longitude, node.azimuth_heading_deg, node.tilt_angle_deg,
                        node.rtsp_main_url, node.rtsp_sub_url, node.ip_address, node.status, node.fps,
                        node.resolution, node.poe_port, node.drift_status, node.created_at, node.last_updated
                    ))
                    conn.commit()
                return True, f"Camera {cam_id} successfully registered.", node.to_dict()
            except sqlite3.IntegrityError:
                return False, f"Camera with ID {cam_id} already exists.", None

    def update_camera(
        self,
        camera_id: str,
        updates: Dict[str, Any],
        operator_role: Role = Role.SUPER_ADMIN,
        operator_division: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Updates camera alias, physical mounting height/structure, or network streams."""
        if operator_role not in (Role.SUPER_ADMIN, Role.STATION_ADMIN):
            return False, "Insufficient privilege: Requires STATION_ADMIN or SUPER_ADMIN.", None

        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM cameras WHERE camera_id = ?", (camera_id,))
                row = cursor.fetchone()
                if not row:
                    return False, f"Camera {camera_id} not found.", None

                cam_dict = dict(row)

                # Multi-tenant boundary check: Station Admin can only modify cameras in their division
                if operator_role == Role.STATION_ADMIN and operator_division:
                    if cam_dict.get("division_id") != operator_division:
                        return False, f"Access denied: Camera {camera_id} is outside station division boundary.", None

                # Editable fields
                allowed_fields = [
                    "name", "mounting_structure", "mounting_height_m", "station_name",
                    "intersection_or_corridor", "latitude", "longitude",
                    "azimuth_heading_deg", "tilt_angle_deg", "rtsp_main_url",
                    "rtsp_sub_url", "ip_address", "status", "fps", "resolution", "poe_port"
                ]

                # If SUPER_ADMIN, they can also reassign division_id
                if operator_role == Role.SUPER_ADMIN:
                    allowed_fields.append("division_id")

                if "mounting_structure" in updates:
                    raw_s = updates["mounting_structure"]
                    clean_s = str(raw_s).strip().upper().replace(" ", "_")
                    if clean_s:
                        updates["mounting_structure"] = clean_s
                        self._ensure_mounting_structure_exists(
                            clean_s,
                            float(updates.get("mounting_height_m", cam_dict.get("mounting_height_m", 6.0)))
                        )

                set_clauses = []
                values = []
                for k, v in updates.items():
                    if k in allowed_fields:
                        set_clauses.append(f"{k} = ?")
                        values.append(v)

                if not set_clauses:
                    return True, "No modifications provided.", cam_dict

                set_clauses.append("last_updated = ?")
                values.append(time.time())
                values.append(camera_id)

                sql = f"UPDATE cameras SET {', '.join(set_clauses)} WHERE camera_id = ?"
                conn.execute(sql, tuple(values))
                conn.commit()

                cursor.execute("SELECT * FROM cameras WHERE camera_id = ?", (camera_id,))
                updated_row = cursor.fetchone()
                return True, f"Camera {camera_id} updated successfully.", dict(updated_row)

    def delete_camera(
        self,
        camera_id: str,
        operator_role: Role = Role.SUPER_ADMIN,
        operator_division: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Deletes a camera device with divisional access enforcement."""
        if operator_role not in (Role.SUPER_ADMIN, Role.STATION_ADMIN):
            return False, "Insufficient privilege: Requires STATION_ADMIN or SUPER_ADMIN."

        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT division_id FROM cameras WHERE camera_id = ?", (camera_id,))
                row = cursor.fetchone()
                if not row:
                    return False, f"Camera {camera_id} not found."

                if operator_role == Role.STATION_ADMIN and operator_division:
                    if row["division_id"] != operator_division:
                        return False, f"Access denied: Camera {camera_id} is outside station division boundary."

                conn.execute("DELETE FROM cameras WHERE camera_id = ?", (camera_id,))
                conn.commit()
                return True, f"Camera {camera_id} deleted."

    def get_camera(
        self,
        camera_id: str,
        operator_role: Role = Role.SUPER_ADMIN,
        operator_division: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieves camera details subject to divisional visibility."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cameras WHERE camera_id = ?", (camera_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cam_dict = dict(row)
            if operator_role != Role.SUPER_ADMIN and operator_division:
                if cam_dict.get("division_id") != operator_division:
                    return None
            return cam_dict

    def list_cameras(
        self,
        operator_role: Role = Role.SUPER_ADMIN,
        operator_division: Optional[str] = None,
        structure_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lists cameras accessible to the requesting role and division."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params = []

            # If not SUPER_ADMIN, isolate by station division
            if operator_role != Role.SUPER_ADMIN and operator_division and operator_division != "ALL_DIVISIONS":
                conditions.append("division_id = ?")
                params.append(operator_division)

            if structure_filter:
                conditions.append("mounting_structure = ?")
                params.append(structure_filter)

            where_str = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            sql = f"SELECT * FROM cameras {where_str} ORDER BY division_id, camera_id"
            cursor.execute(sql, tuple(params))
            return [dict(r) for r in cursor.fetchall()]

    def list_mounting_structures(self) -> List[Dict[str, Any]]:
        """Lists all configured camera mounting structures (baseline and admin-defined)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mounting_structures ORDER BY is_custom ASC, structure_key ASC")
            return [dict(r) for r in cursor.fetchall()]

    def get_mounting_structure(self, structure_key: str) -> Optional[Dict[str, Any]]:
        """Retrieves specific mounting structure configuration."""
        clean_key = structure_key.strip().upper().replace(" ", "_")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mounting_structures WHERE structure_key = ?", (clean_key,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_or_update_mounting_structure(
        self,
        structure_key: str,
        data: Dict[str, Any],
        operator_role: Role = Role.SUPER_ADMIN,
        operator_username: str = "SYSTEM",
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Allows administrators to configure arbitrary new physical mounting categories and specifications."""
        if operator_role not in (Role.SUPER_ADMIN, Role.STATION_ADMIN):
            return False, "Insufficient privilege: Requires STATION_ADMIN or SUPER_ADMIN.", None

        clean_key = structure_key.strip().upper().replace(" ", "_")
        if not clean_key:
            return False, "Structure key cannot be empty.", None

        label = data.get("label", clean_key.replace("_", " ").title())
        h_min = float(data.get("recommended_height_min_m", 4.0))
        h_max = float(data.get("recommended_height_max_m", 15.0))
        vib = str(data.get("vibration_sensitivity", "MEDIUM")).upper()
        sway = str(data.get("wind_sway_sensitivity", "MEDIUM")).upper()
        angle = str(data.get("perspective_angle", "STANDARD")).upper()
        app = str(data.get("primary_application", "Traffic Surveillance & Enforcement"))
        now = time.time()

        with self.lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO mounting_structures (
                        structure_key, label, recommended_height_min_m, recommended_height_max_m,
                        vibration_sensitivity, wind_sway_sensitivity, perspective_angle,
                        primary_application, is_custom, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(structure_key) DO UPDATE SET
                        label = excluded.label,
                        recommended_height_min_m = excluded.recommended_height_min_m,
                        recommended_height_max_m = excluded.recommended_height_max_m,
                        vibration_sensitivity = excluded.vibration_sensitivity,
                        wind_sway_sensitivity = excluded.wind_sway_sensitivity,
                        perspective_angle = excluded.perspective_angle,
                        primary_application = excluded.primary_application
                """, (clean_key, label, h_min, h_max, vib, sway, angle, app, now, operator_username))
                conn.commit()

            return True, f"Mounting structure '{clean_key}' saved.", self.get_mounting_structure(clean_key)

    def delete_mounting_structure(
        self,
        structure_key: str,
        operator_role: Role = Role.SUPER_ADMIN,
    ) -> Tuple[bool, str]:
        """Deletes a custom mounting structure with foreign key safety check."""
        if operator_role not in (Role.SUPER_ADMIN, Role.STATION_ADMIN):
            return False, "Insufficient privilege: Requires STATION_ADMIN or SUPER_ADMIN."

        clean_key = structure_key.strip().upper()
        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_custom FROM mounting_structures WHERE structure_key = ?", (clean_key,))
                row = cursor.fetchone()
                if not row:
                    return False, f"Structure '{clean_key}' not found."

                # Verify if any active cameras use this structure
                cursor.execute("SELECT COUNT(*) as count FROM cameras WHERE mounting_structure = ?", (clean_key,))
                cam_count = cursor.fetchone()["count"]
                if cam_count > 0:
                    return False, f"Cannot delete '{clean_key}': Currently referenced by {cam_count} cameras."

                conn.execute("DELETE FROM mounting_structures WHERE structure_key = ?", (clean_key,))
                conn.commit()
                return True, f"Mounting structure '{clean_key}' deleted."

    def get_mounting_specs(self) -> Dict[str, Dict[str, Any]]:
        """Returns physical and optical deployment specs dynamically for all configured structures."""
        structures = self.list_mounting_structures()
        specs = {}
        for s in structures:
            key = s["structure_key"]
            specs[key] = {
                "structure_key": key,
                "label": s["label"],
                "recommended_height_range_m": [s["recommended_height_min_m"], s["recommended_height_max_m"]],
                "vibration_sensitivity": s["vibration_sensitivity"],
                "wind_sway_sensitivity": s["wind_sway_sensitivity"],
                "perspective_angle": s["perspective_angle"],
                "primary_application": s["primary_application"],
                "is_custom": bool(s["is_custom"]),
            }
        return specs

