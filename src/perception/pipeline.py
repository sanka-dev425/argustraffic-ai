"""
ArgusTraffic AI - Perception Engine: Multi-Stage Perception Pipeline Orchestrator
Integrates Scene Quality Analysis -> Adaptive Preprocessing -> Detection Backend ->
Small-Object Tiling -> Temporal Fusion -> Multi-Factor Confidence Calibration.
"""

import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.core.interfaces import Detection
from src.perception.conditions.scene_quality import SceneQuality, SceneQualityEvaluator
from src.perception.confidence import PerceptionConfidenceEngine, PerceptionConfidenceVector
from src.perception.detector.base import ComputeBackend, DetectorBackend, ModelFramework
from src.perception.detector.factory import create_detector
from src.perception.detector.registry import get_model_registry
from src.perception.fusion.temporal import TemporalDetectionFusionEngine
from src.perception.preprocessing.pipeline import AdaptivePreprocessor
from src.perception.roi.small_object import SmallObjectTilingEngine


class PerceptionPipeline:
    """
    Production-grade multi-stage perception pipeline.
    Seamlessly orchestrates scene analysis, adaptive enhancement, model inference, and temporal consensus.
    """

    def __init__(
        self,
        framework: ModelFramework = ModelFramework.ULTRALYTICS_YOLO,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        device: str = "auto",
        enable_tiling: bool = False,
        enable_temporal_fusion: bool = True,
    ):
        self.detector: DetectorBackend = create_detector(
            framework=framework,
            model_path=model_path,
            device=device,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
        )
        self.quality_evaluator = SceneQualityEvaluator()
        self.preprocessor = AdaptivePreprocessor()
        self.tiler = SmallObjectTilingEngine()
        self.temporal_fusion = TemporalDetectionFusionEngine() if enable_temporal_fusion else None
        self.confidence_engine = PerceptionConfidenceEngine()

        self.enable_tiling = enable_tiling
        self.last_scene_quality: Optional[SceneQuality] = None
        self.total_frames_processed: int = 0

    def process_frame(self, frame: np.ndarray) -> Tuple[List[Detection], float, SceneQuality]:
        """
        Processes a single video frame through the complete multi-stage perception chain.

        Returns:
            Tuple of (calibrated_detections, latency_ms, scene_quality)
        """
        t0 = time.perf_counter()
        self.total_frames_processed += 1

        # 1. Scene Quality Assessment
        scene_quality = self.quality_evaluator.evaluate(frame)
        self.last_scene_quality = scene_quality

        # 2. Adaptive Preprocessing (CLAHE enhancement if low light)
        enhanced_frame, scale, pads = self.preprocessor.preprocess(frame, scene_quality)

        # 3. Model Inference (Global or Tiled)
        if self.enable_tiling and (frame.shape[0] >= 1080 or frame.shape[1] >= 1920):
            tiles = self.tiler.generate_tiles(frame)
            tile_results = []
            for tile_img, off_x, off_y in tiles:
                tile_dets, _ = self.detector.infer(tile_img)
                tile_results.append((tile_dets, off_x, off_y))
            raw_detections = self.tiler.merge_tile_detections(tile_results)
        else:
            raw_detections, _ = self.detector.infer(enhanced_frame)

        # 4. Temporal Detection Fusion
        if self.temporal_fusion is not None:
            fused_detections = self.temporal_fusion.update(raw_detections)
        else:
            fused_detections = raw_detections

        # 5. Multi-Factor Confidence Calibration
        calibrated_detections: List[Detection] = []
        for det in fused_detections:
            conf_vector = self.confidence_engine.evaluate(
                detection=det,
                temporal_hits=2,
                track_age=1,
                scene_quality=scene_quality,
            )
            # Re-assign calibrated confidence
            det.confidence = conf_vector.overall_confidence
            calibrated_detections.append(det)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return calibrated_detections, latency_ms, scene_quality

    def get_health(self) -> Dict[str, Any]:
        """Diagnostics for the perception plane."""
        det_health = self.detector.health()
        return {
            "perception_status": "ONLINE",
            "detector_backend": det_health.get("backend", "YOLO"),
            "detector_health": det_health,
            "total_frames_processed": self.total_frames_processed,
            "last_scene_quality": self.last_scene_quality.__dict__ if self.last_scene_quality else None,
            "tiling_active": self.enable_tiling,
            "temporal_fusion_active": self.temporal_fusion is not None,
        }
