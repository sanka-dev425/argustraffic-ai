"""
ArgusTraffic AI - Perception Engine: Multi-Factor Perception Confidence
Calculates calibrated confidence scores synthesizing model certainty,
temporal stability, tracking consistency, spatial geometry, and environmental quality.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from src.core.interfaces import Detection
from src.perception.conditions.scene_quality import SceneQuality


@dataclass
class PerceptionConfidenceVector:
    detection_confidence: float
    temporal_confidence: float
    tracking_confidence: float
    geometry_confidence: float
    scene_quality_confidence: float
    overall_confidence: float


class PerceptionConfidenceEngine:
    """Computes multi-signal calibrated perception certainty."""

    def __init__(
        self,
        weight_det: float = 0.35,
        weight_temp: float = 0.25,
        weight_track: float = 0.15,
        weight_geom: float = 0.15,
        weight_scene: float = 0.10,
    ):
        self.w_det = weight_det
        self.w_temp = weight_temp
        self.w_track = weight_track
        self.w_geom = weight_geom
        self.w_scene = weight_scene

    def evaluate(
        self,
        detection: Detection,
        temporal_hits: int = 1,
        track_age: int = 1,
        scene_quality: Optional[SceneQuality] = None,
    ) -> PerceptionConfidenceVector:
        """
        Synthesizes confidence signals into a verifiable confidence vector.
        """
        det_conf = max(0.0, min(1.0, detection.confidence))

        # Temporal factor (reaches 1.0 after 4 consecutive hits)
        temp_conf = min(1.0, max(0.2, temporal_hits / 4.0))

        # Tracking factor (reaches 1.0 after 10 frames)
        track_conf = min(1.0, max(0.3, track_age / 10.0))

        # Geometry plausibility
        geom_conf = self._evaluate_geometry(detection.bbox, detection.class_name)

        # Scene quality factor
        scene_conf = scene_quality.overall_quality_score if scene_quality else 0.90

        # Weighted composite score
        composite = (
            self.w_det * det_conf
            + self.w_temp * temp_conf
            + self.w_track * track_conf
            + self.w_geom * geom_conf
            + self.w_scene * scene_conf
        )

        overall = round(max(0.01, min(0.99, composite)), 2)

        return PerceptionConfidenceVector(
            detection_confidence=round(det_conf, 2),
            temporal_confidence=round(temp_conf, 2),
            tracking_confidence=round(track_conf, 2),
            geometry_confidence=round(geom_conf, 2),
            scene_quality_confidence=round(scene_conf, 2),
            overall_confidence=overall,
        )

    @staticmethod
    def _evaluate_geometry(bbox: Tuple[float, float, float, float], class_name: str) -> float:
        """Evaluates bounding box aspect ratio and scale sanity."""
        x1, y1, x2, y2 = bbox
        w = max(1.0, x2 - x1)
        h = max(1.0, y2 - y1)
        aspect_ratio = w / h

        # Pedestrians are typically taller than wide (aspect ratio < 1.0)
        if class_name == "pedestrian":
            if 0.15 <= aspect_ratio <= 0.85:
                return 1.0
            return 0.60

        # Vehicles are typically wider or roughly boxy (aspect ratio 0.6 to 2.5)
        if class_name in ["car", "truck", "bus"]:
            if 0.5 <= aspect_ratio <= 2.8:
                return 1.0
            return 0.70

        return 0.85
