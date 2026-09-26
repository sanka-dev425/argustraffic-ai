"""
ArgusTraffic AI - Spatial Kinematics & Multi-Signal Risk Engine
Implements mathematical Time-to-Collision (TTC), proximity hazard analysis,
and multi-factor risk assessment for Intelligent Transportation Systems.
"""

import math
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.core.config_schema import RiskEngineSettings, get_platform_config
from src.core.interfaces import (
    ObjectCategory,
    RiskAssessment,
    RiskEngineProtocol,
    RiskLevel,
    TrackedObject,
)


class SpatialRiskEngine(RiskEngineProtocol):
    """
    Evaluates dynamic trajectory vectors, relative velocities, and spatial proximity
    to compute continuous risk scores and discrete severity classifications.
    """

    def __init__(self, config: Optional[RiskEngineSettings] = None):
        self.config = config or get_platform_config().risk

    def assess_risk(
        self,
        tracks: List[TrackedObject],
        zones: Optional[Dict[str, Any]] = None,
        frame_time: Optional[float] = None,
    ) -> List[RiskAssessment]:
        """
        Runs comprehensive pairwise kinematic trajectory analysis across all active tracks.
        """
        if not self.config.enabled or len(tracks) < 1:
            return []

        timestamp = frame_time if frame_time is not None else time.time()
        assessments: List[RiskAssessment] = []

        # 1. Pairwise interaction risk (Vehicle-Vehicle & Vehicle-Pedestrian)
        num_tracks = len(tracks)
        for i in range(num_tracks):
            for j in range(i + 1, num_tracks):
                t1 = tracks[i]
                t2 = tracks[j]

                assessment = self._evaluate_pairwise_risk(t1, t2, timestamp)
                if assessment and assessment.risk_level != RiskLevel.NEGLIGIBLE:
                    assessments.append(assessment)

        # 2. Single-agent anomalous state risk (e.g. stalled or high-speed erratic)
        for t in tracks:
            single_assessment = self._evaluate_single_agent_risk(t, timestamp)
            if single_assessment and single_assessment.risk_level != RiskLevel.NEGLIGIBLE:
                assessments.append(single_assessment)

        # Sort descending by risk score
        assessments.sort(key=lambda x: x.risk_score, reverse=True)
        return assessments

    def _evaluate_pairwise_risk(
        self, t1: TrackedObject, t2: TrackedObject, timestamp: float
    ) -> Optional[RiskAssessment]:
        p1 = np.array(t1.centroid)
        p2 = np.array(t2.centroid)
        distance_px = float(np.linalg.norm(p1 - p2))

        v1 = np.array(t1.velocity)  # (vx, vy) px/frame
        v2 = np.array(t2.velocity)

        # Relative velocity vector: V_rel = V1 - V2
        v_rel = v1 - v2
        rel_speed = float(np.linalg.norm(v_rel))

        # Relative position vector: R = P2 - P1
        r_vec = p2 - p1

        # Check if objects are converging (closing in)
        # Convergence rate = - (R . V_rel) / |R|
        dot_product = np.dot(r_vec, v_rel)
        is_converging = dot_product > 0

        ttc: Optional[float] = None
        if is_converging and rel_speed > 0.5:
            # Approximate Time-to-Collision in seconds (assuming 30 FPS)
            closing_speed_px_per_sec = rel_speed * 30.0
            ttc = max(0.1, distance_px / closing_speed_px_per_sec)

        # Determine vulnerability weight
        is_pedestrian_involved = (
            t1.class_name in [ObjectCategory.PEDESTRIAN, ObjectCategory.BICYCLE]
            or t2.class_name in [ObjectCategory.PEDESTRIAN, ObjectCategory.BICYCLE]
        )

        factors: List[str] = []
        raw_score = 0.0

        # Factor 1: TTC Score (0 to 1.0)
        if ttc is not None:
            if ttc <= self.config.critical_ttc_seconds:
                raw_score += self.config.weight_ttc * 1.0
                factors.append(f"Critical TTC: {ttc:.2f}s")
            elif ttc <= self.config.high_ttc_seconds:
                raw_score += self.config.weight_ttc * 0.7
                factors.append(f"High-risk TTC: {ttc:.2f}s")
            elif ttc <= self.config.medium_ttc_seconds:
                raw_score += self.config.weight_ttc * 0.4
                factors.append(f"Moderate TTC: {ttc:.2f}s")

        # Factor 2: Proximity Score
        proximity_threshold = 120.0 if is_pedestrian_involved else 80.0
        if distance_px < proximity_threshold:
            prox_intensity = 1.0 - (distance_px / proximity_threshold)
            raw_score += self.config.weight_proximity * prox_intensity
            factors.append(f"Close Proximity: {distance_px:.1f}px")

        # Factor 3: Vulnerable Road User Weight
        if is_pedestrian_involved and distance_px < 150.0:
            raw_score += self.config.weight_vulnerable_road_user
            factors.append("Vulnerable Road User in Conflict Zone")

        # Factor 4: Relative Speed Severity
        if rel_speed > 5.0 and distance_px <= 250.0:
            raw_score += self.config.weight_relative_speed * min(1.0, rel_speed / 20.0)
            factors.append(f"High Relative Delta-V: {rel_speed:.1f} px/f")

        risk_score = min(1.0, max(0.0, raw_score))

        # Map to Risk Level
        if risk_score >= 0.75:
            level = RiskLevel.CRITICAL
        elif risk_score >= 0.50:
            level = RiskLevel.HIGH
        elif risk_score >= 0.25:
            level = RiskLevel.MEDIUM
        elif risk_score >= 0.10:
            level = RiskLevel.LOW
        else:
            level = RiskLevel.NEGLIGIBLE

        if level == RiskLevel.NEGLIGIBLE:
            return None

        primary_hazard = (
            "Pedestrian Conflict Hazard"
            if is_pedestrian_involved
            else "Vehicle Collision Trajectory"
        )

        return RiskAssessment(
            risk_level=level,
            risk_score=round(risk_score, 3),
            confidence=round(min(t1.confidence, t2.confidence), 2),
            time_to_collision_sec=round(ttc, 2) if ttc is not None else None,
            involved_track_ids=[t1.track_id, t2.track_id],
            primary_hazard=primary_hazard,
            contributing_factors=factors,
            timestamp=timestamp,
        )

    def _evaluate_single_agent_risk(
        self, track: TrackedObject, timestamp: float
    ) -> Optional[RiskAssessment]:
        """Assesses single-vehicle anomalies such as stalled obstacles."""
        if track.class_name in [ObjectCategory.CAR, ObjectCategory.TRUCK, ObjectCategory.BUS]:
            # If confirmed vehicle is stationary for significant age
            if track.speed_px_per_sec < 2.0 and track.age > 90:  # ~3 seconds at 30 fps
                return RiskAssessment(
                    risk_level=RiskLevel.MEDIUM,
                    risk_score=0.45,
                    confidence=track.confidence,
                    time_to_collision_sec=None,
                    involved_track_ids=[track.track_id],
                    primary_hazard="Stationary Roadway Obstruction",
                    contributing_factors=["Zero velocity sustained > 3.0s"],
                    timestamp=timestamp,
                )
        return None
