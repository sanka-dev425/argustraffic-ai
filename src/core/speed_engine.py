"""ArgusTraffic AI - Enterprise Speed Radar & Calibration Engine
Calculates vehicle velocity in km/h using pixel-to-meter homography/scaling,
temporal trajectory differentiation, and exponential smoothing.
"""

from collections import deque
import math
import time
from typing import Dict, List, Optional, Tuple


class SpeedRadarEngine:
    """Optical speed radar with perspective scaling and temporal differentiation."""

    def __init__(
        self,
        pixels_per_meter: float = 18.5,
        speed_limit_kmh: float = 60.0,
        smoothing_window: int = 8,
    ):
        """
        Args:
            pixels_per_meter: Calibration constant mapping image pixels to physical meters.
            speed_limit_kmh: Regulatory speed threshold for violation detection.
            smoothing_window: Trajectory frame window for moving average velocity calculation.
        """
        self.pixels_per_meter = max(1.0, pixels_per_meter)
        self.speed_limit_kmh = speed_limit_kmh
        self.smoothing_window = smoothing_window

        # Trajectory history: track_id -> deque of (timestamp, cx, cy)
        self._trajectories: Dict[int, deque] = {}
        # Cached smoothed speeds: track_id -> km/h
        self._current_speeds: Dict[int, float] = {}

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
        # Convert to physical meters
        meters = pixel_dist / self.pixels_per_meter
        # Metric speed: m/s -> km/h
        raw_speed_kmh = (meters / dt) * 3.6

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
