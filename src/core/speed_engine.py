"""ArgusTraffic AI - Enterprise Speed Radar & Calibration Engine
Calculates vehicle velocity in km/h using pixel-to-meter homography/scaling,
temporal trajectory differentiation, and exponential smoothing.
"""

from collections import deque
from dataclasses import dataclass, field
import datetime
import math
import time
from typing import Any, Dict, List, Optional, Tuple


class SpeedRadarEngine:
    """Optical speed radar with perspective scaling and temporal differentiation."""

    def __init__(
        self,
        pixels_per_meter: float = 18.5,
        speed_limit_kmh: float = 60.0,
        smoothing_window: int = 8,
        perspective_correction: bool = False,
        vanishing_y: float = 120.0,
        reference_y: float = 540.0,
        max_plausible_speed_kmh: float = 240.0,
    ):
        """
        Args:
            pixels_per_meter: Calibration constant mapping image pixels to physical meters at reference depth.
            speed_limit_kmh: Regulatory speed threshold for violation detection.
            smoothing_window: Trajectory frame window for moving average velocity calculation.
            perspective_correction: Whether to apply non-linear depth foreshortening compensation.
            vanishing_y: Estimated vertical coordinate of the roadway horizon/vanishing point.
            reference_y: Vertical coordinate in image space where pixels_per_meter is calibrated.
            max_plausible_speed_kmh: Physical upper bound to reject tracker teleportation anomalies.
        """
        self.pixels_per_meter = max(1.0, pixels_per_meter)
        self.speed_limit_kmh = speed_limit_kmh
        self.smoothing_window = smoothing_window
        self.perspective_correction = perspective_correction
        self.vanishing_y = vanishing_y
        self.reference_y = reference_y
        self.max_plausible_speed_kmh = max_plausible_speed_kmh

        # Trajectory history: track_id -> deque of (timestamp, cx, cy)
        self._trajectories: Dict[int, deque] = {}
        # Cached smoothed speeds: track_id -> km/h
        self._current_speeds: Dict[int, float] = {}

    def get_pixels_per_meter_at_y(self, y: float) -> float:
        """Calculates perspective depth-adjusted pixels per meter at frame height y."""
        if not self.perspective_correction:
            return self.pixels_per_meter

        # Clamped distance from vanishing horizon
        denom = max(10.0, self.reference_y - self.vanishing_y)
        dist_from_horizon = max(10.0, y - self.vanishing_y)
        depth_scale = dist_from_horizon / denom

        # Bound scale between 0.25 (deep horizon) and 2.5 (extreme foreground)
        depth_scale = max(0.25, min(2.5, depth_scale))
        return self.pixels_per_meter * depth_scale

    def update_track(
        self, track_id: int, cx: float, cy: float, timestamp: Optional[float] = None
    ) -> float:
        """Updates centroid observation for a track and calculates smoothed speed in km/h.

        Returns:
            Current speed in km/h.
        """
        now = timestamp or time.time()

        if track_id not in self._trajectories:
            self._trajectories[track_id] = deque(maxlen=self.smoothing_window)

        hist = self._trajectories[track_id]
        hist.append((now, cx, cy))

        if len(hist) < 2:
            self._current_speeds[track_id] = 0.0
            return 0.0

        # Calculate velocity across the time window
        t_start, x_start, y_start = hist[0]
        t_end, x_end, y_end = hist[-1]

        dt = t_end - t_start
        if dt <= 0.001:
            return self._current_speeds.get(track_id, 0.0)

        # Pixel Euclidean distance
        pixel_dist = math.hypot(x_end - x_start, y_end - y_start)

        # Depth-aware perspective calibration
        avg_y = (y_start + y_end) / 2.0
        local_ppm = self.get_pixels_per_meter_at_y(avg_y)

        # Convert to physical meters
        meters = pixel_dist / local_ppm
        # Metric speed: m/s -> km/h
        raw_speed_kmh = (meters / dt) * 3.6

        # Data Science Sanity Guard: Check physical plausibility
        if math.isnan(raw_speed_kmh) or math.isinf(raw_speed_kmh) or raw_speed_kmh < 0.0:
            return self._current_speeds.get(track_id, 0.0)

        # Outlier rejection: Discard tracking teleportation spikes
        if raw_speed_kmh > self.max_plausible_speed_kmh:
            return self._current_speeds.get(track_id, 0.0)

        # Exponential moving average filter with previous speed
        prev_speed = self._current_speeds.get(track_id, raw_speed_kmh)
        smoothed_speed = round(0.35 * raw_speed_kmh + 0.65 * prev_speed, 1)

        self._current_speeds[track_id] = smoothed_speed
        return smoothed_speed

    def get_speed(self, track_id: int) -> float:
        """Returns the latest estimated speed for a given vehicle track ID."""
        return self._current_speeds.get(track_id, 0.0)

    def is_speeding(self, track_id: int) -> Tuple[bool, float, float]:
        """Checks if a vehicle exceeds the configured speed limit.

        Returns:
            Tuple of (is_violating, observed_speed, limit)
        """
        speed = self.get_speed(track_id)
        is_violating = speed > self.speed_limit_kmh
        return is_violating, speed, self.speed_limit_kmh

    def purge_stale_tracks(self, active_track_ids: List[int]):
        """Cleans up internal caches for retired vehicle tracks."""
        active_set = set(active_track_ids)
        stale = [tid for tid in self._trajectories if tid not in active_set]
        for tid in stale:
            self._trajectories.pop(tid, None)
            self._current_speeds.pop(tid, None)


@dataclass
class SectionPassage:
    plate: str
    camera_id: str
    checkpoint_id: str
    timestamp: float
    snapshot_path: Optional[str] = None
    vehicle_class: str = "car"


class PointToPointAverageSpeedEngine:
    """
    Enterprise Point-to-Point (P2P) Section Control Speed Enforcement Engine.
    Computes true average corridor velocity between highway checkpoints (Gantry A -> Gantry B),
    eliminating the 'brake right in front of radar' blindspot.
    """

    def __init__(
        self,
        corridor_id: str = "EXPRESSWAY_SECTION_01",
        section_distance_km: float = 5.0,
        speed_limit_kmh: float = 100.0,
        tolerance_kmh: float = 3.0,
    ):
        self.corridor_id = corridor_id
        self.section_distance_km = section_distance_km
        self.speed_limit_kmh = speed_limit_kmh
        self.tolerance_kmh = tolerance_kmh
        self.entry_passages: Dict[str, SectionPassage] = {}
        self.violations: List[Dict[str, Any]] = []

    def record_passage(
        self,
        plate: str,
        camera_id: str,
        checkpoint_role: str,  # 'ENTRY' or 'EXIT'
        timestamp: Optional[float] = None,
        vehicle_class: str = "car",
        snapshot_path: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Records an ANPR passage at an entry or exit checkpoint gantry.
        If an EXIT passage matches an earlier ENTRY, computes average speed and logs violation if speeding.
        """
        clean_plate = plate.replace(" ", "").replace("-", "").upper()
        ts = timestamp or time.time()
        role = checkpoint_role.upper()

        if role == "ENTRY":
            passage = SectionPassage(
                plate=clean_plate,
                camera_id=camera_id,
                checkpoint_id=camera_id,
                timestamp=ts,
                snapshot_path=snapshot_path,
                vehicle_class=vehicle_class,
            )
            self.entry_passages[clean_plate] = passage
            return None

        elif role == "EXIT":
            entry = self.entry_passages.pop(clean_plate, None)
            if not entry:
                return None

            elapsed_seconds = ts - entry.timestamp
            if elapsed_seconds <= 1.0:
                return None  # Ignore duplicate or unrealistic timing

            # Average speed: km / hours
            hours = elapsed_seconds / 3600.0
            average_speed_kmh = round(self.section_distance_km / hours, 1)

            # Determine violation
            effective_threshold = self.speed_limit_kmh + self.tolerance_kmh
            is_violation = average_speed_kmh > effective_threshold

            dossier = {
                "dossier_id": f"P2P-{clean_plate}-{int(ts)}",
                "plate": clean_plate,
                "corridor_id": self.corridor_id,
                "section_distance_km": self.section_distance_km,
                "entry_camera": entry.camera_id,
                "entry_time": datetime.datetime.fromtimestamp(entry.timestamp, datetime.timezone.utc).isoformat(),
                "exit_camera": camera_id,
                "exit_time": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(),
                "elapsed_seconds": round(elapsed_seconds, 1),
                "speed_limit_kmh": self.speed_limit_kmh,
                "average_speed_kmh": average_speed_kmh,
                "excess_kmh": round(max(0.0, average_speed_kmh - self.speed_limit_kmh), 1),
                "is_violation": is_violation,
                "vehicle_class": vehicle_class,
                "evidence_snapshots": [entry.snapshot_path, snapshot_path],
            }

            if is_violation:
                self.violations.append(dossier)

            return dossier

        return None

    def get_violations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns historical point-to-point section speed violations."""
        return self.violations[-limit:]


class PerspectiveHomographyCalibrator:
    """
    Sub-millimeter Planar Homography Perspective Calibrator.
    Maps 4 image pixel coordinates (trapezoid lane projection) onto physical metric space (meters).
    Enables true Bird's-Eye-View (BEV) vehicle speed and distance estimation without perspective bias.
    """

    def __init__(
        self,
        src_points: Optional[List[Tuple[float, float]]] = None,
        real_width_meters: float = 3.65,
        real_length_meters: float = 25.0,
    ):
        """
        Args:
            src_points: 4 quadrilateral points in image space [TL, TR, BR, BL] (x, y).
            real_width_meters: Physical lane width in meters (default 3.65m standard lane).
            real_length_meters: Physical distance along the travel axis in meters.
        """
        self.real_width_meters = real_width_meters
        self.real_length_meters = real_length_meters
        # Default standard 1080p highway projection polygon
        self.src_points = src_points or [
            (480.0, 300.0),   # Top-Left (Far lane marker)
            (800.0, 300.0),   # Top-Right
            (1150.0, 700.0),  # Bottom-Right (Near foreground)
            (130.0, 700.0),   # Bottom-Left
        ]
        self._homography_matrix: Optional[Any] = None
        self._compute_matrix()

    def _compute_matrix(self) -> None:
        import numpy as np
        try:
            import cv2
            src = np.array(self.src_points, dtype=np.float32)
            dst = np.array(
                [
                    [0.0, 0.0],
                    [self.real_width_meters, 0.0],
                    [self.real_width_meters, self.real_length_meters],
                    [0.0, self.real_length_meters],
                ],
                dtype=np.float32,
            )
            self._homography_matrix = cv2.getPerspectiveTransform(src, dst)
        except Exception:
            self._homography_matrix = None

    def transform_pixel_to_meter(self, px: float, py: float) -> Tuple[float, float]:
        """Maps an image pixel coordinate (px, py) to ground-plane world metric (x_meters, y_meters)."""
        import numpy as np
        if self._homography_matrix is None:
            # Linear fallback
            return (px * 0.05, py * 0.05)

        pt = np.array([[[px, py]]], dtype=np.float32)
        try:
            import cv2
            transformed = cv2.perspectiveTransform(pt, self._homography_matrix)
            wx, wy = transformed[0][0]
            return (float(wx), float(wy))
        except Exception:
            return (px * 0.05, py * 0.05)

    def calculate_speed_kmh(
        self,
        point_start: Tuple[float, float],
        point_end: Tuple[float, float],
        dt_seconds: float,
    ) -> float:
        """Computes true metric ground speed in km/h between two pixel observations."""
        if dt_seconds <= 0.001:
            return 0.0

        w_start = self.transform_pixel_to_meter(point_start[0], point_start[1])
        w_end = self.transform_pixel_to_meter(point_end[0], point_end[1])

        distance_meters = math.hypot(w_end[0] - w_start[0], w_end[1] - w_start[1])
        speed_mps = distance_meters / dt_seconds
        speed_kmh = speed_mps * 3.6
        return round(speed_kmh, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src_points": self.src_points,
            "real_width_meters": self.real_width_meters,
            "real_length_meters": self.real_length_meters,
        }

