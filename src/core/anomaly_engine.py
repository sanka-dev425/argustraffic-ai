"""ArgusTraffic AI - Abnormal Movement & Trajectory Intelligence Engine
Detects erratic swerving, illegal U-turns, abrupt emergency braking,
and hazardous highway maneuvers.
"""

from collections import deque
import math
import time
from typing import Dict, List, Optional, Tuple


class AnomalyEngine:
    """Evaluates spatial trajectories for anomalous and high-risk driving behaviors."""

    def __init__(
        self,
        swerve_variance_threshold: float = 450.0,
        deceleration_threshold_ms2: float = 6.5,
        history_window: int = 15,
    ):
        self.swerve_variance_threshold = swerve_variance_threshold
        self.deceleration_threshold_ms2 = deceleration_threshold_ms2
        self.history_window = history_window

        # track_id -> deque of (timestamp, cx, cy, vx, vy, speed_kmh)
        self._trajectory_history: Dict[int, deque] = {}

    def ingest_vector(
        self,
        track_id: int,
        cx: float,
        cy: float,
        vx: float,
        vy: float,
        speed_kmh: float,
        timestamp: Optional[float] = None,
    ) -> List[Dict]:
        """Ingests instantaneous vehicle movement and returns any active hazard anomalies."""
        now = timestamp or time.time()

        if track_id not in self._trajectory_history:
            self._trajectory_history[track_id] = deque(maxlen=self.history_window)

        hist = self._trajectory_history[track_id]
        hist.append((now, cx, cy, vx, vy, speed_kmh))

        anomalies = []

        if len(hist) < 6:
            return anomalies

        # 1. Erratic Swerving / Zigzag Detection
        is_swerving, var_x = self._check_swerving(hist)
        if is_swerving:
            anomalies.append({
                "type": "ERRATIC_SWERVE_HAZARD",
                "severity": "HIGH",
                "track_id": track_id,
                "score": round(min(1.0, var_x / (self.swerve_variance_threshold * 2)), 2),
                "details": f"Vehicle exhibiting lateral oscillation variance ({var_x:.1f})",
            })

        # 2. Sudden Severe Deceleration / Slam-Braking
        is_braking, decel_val = self._check_sudden_braking(hist)
        if is_braking:
            anomalies.append({
                "type": "ABRUPT_BRAKING_HAZARD",
                "severity": "CRITICAL",
                "track_id": track_id,
                "score": 0.95,
                "details": f"Severe deceleration observed ({decel_val:.1f} m/s²)",
            })

        # 3. Heading Inversion / Illegal U-Turn in Motion
        is_uturn = self._check_u_turn(hist)
        if is_uturn:
            anomalies.append({
                "type": "ILLEGAL_U_TURN_DETECTED",
                "severity": "CRITICAL",
                "track_id": track_id,
                "score": 0.98,
                "details": "Vehicle executed trajectory reversal > 140° in designated traffic corridor",
            })

        return anomalies

    def _check_swerving(self, hist: deque) -> Tuple[bool, float]:
        """Calculates lateral (x-axis) deviation variance."""
        x_coords = [h[1] for h in hist]
        mean_x = sum(x_coords) / len(x_coords)
        var_x = sum((x - mean_x) ** 2 for x in x_coords) / len(x_coords)
        return (var_x > self.swerve_variance_threshold), var_x

    def _check_sudden_braking(self, hist: deque) -> Tuple[bool, float]:
        """Computes rate of velocity reduction."""
        t1, _, _, _, _, s1 = hist[0]
        t2, _, _, _, _, s2 = hist[-1]
        dt = t2 - t1
        if dt <= 0.1:
            return False, 0.0

        v1_ms = s1 / 3.6
        v2_ms = s2 / 3.6
        dv = v2_ms - v1_ms
        accel = dv / dt

        if accel < -self.deceleration_threshold_ms2 and s1 > 25.0:
            return True, abs(accel)
        return False, 0.0

    def _check_u_turn(self, hist: deque) -> bool:
        """Computes dot product of initial heading vector vs latest heading vector."""
        # Initial velocity vector
        vx_init = hist[2][3]
        vy_init = hist[2][4]
        # Current velocity vector
        vx_curr = hist[-1][3]
        vy_curr = hist[-1][4]

        mag_init = math.hypot(vx_init, vy_init)
        mag_curr = math.hypot(vx_curr, vy_curr)

        if mag_init < 1.0 or mag_curr < 1.0:
            return False

        # Cosine similarity between initial and current vector
        cos_theta = (vx_init * vx_curr + vy_init * vy_curr) / (mag_init * mag_curr)
        # Reversal occurs when angle is near 180 degrees (cos < -0.65)
        return cos_theta < -0.65

    def purge_stale_tracks(self, active_track_ids: List[int]):
        """Cleans memory cache for retired vehicles."""
        active_set = set(active_track_ids)
        stale = [tid for tid in self._trajectory_history if tid not in active_set]
        for tid in stale:
            self._trajectory_history.pop(tid, None)
