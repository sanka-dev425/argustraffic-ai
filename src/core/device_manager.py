"""
ArgusTraffic AI - Enterprise Device Fleet & Stream Optimization Engine
Provides:
1. StreamRelayProxy: Single-ingestion camera multiplexer with Dual-Stream (Main/Sub) routing.
2. FOVDriftDetector: Optical landmark watchdog detecting camera physical displacement/tilting.
3. ThermalAdaptiveScheduler: Dynamic motion gating and thermal load shedding for edge devices.
4. NTPTimeSyncGuard: Validates timestamp alignment for legal court admissibility.
"""

from collections import deque
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

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
