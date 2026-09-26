"""
ArgusTraffic AI - Perception Engine Package
"""

from src.perception.conditions.scene_quality import (
    IlluminationState,
    SceneQuality,
    SceneQualityEvaluator,
    WeatherEstimate,
)
from src.perception.confidence import (
    PerceptionConfidenceEngine,
    PerceptionConfidenceVector,
)
from src.perception.detector.base import (
    ComputeBackend,
    DetectorBackend,
    ModelFramework,
    ModelMetadata,
)
from src.perception.detector.factory import create_detector
from src.perception.detector.mock_adapter import MockDetectorAdapter
from src.perception.detector.registry import ModelRegistry, get_model_registry
from src.perception.detector.yolo_adapter import YOLODetectorAdapter
from src.perception.fusion.temporal import TemporalDetectionFusionEngine
from src.perception.pipeline import PerceptionPipeline
from src.perception.preprocessing.pipeline import AdaptivePreprocessor
from src.perception.roi.small_object import SmallObjectTilingEngine

__all__ = [
    "DetectorBackend",
    "ModelFramework",
    "ComputeBackend",
    "ModelMetadata",
    "ModelRegistry",
    "get_model_registry",
    "create_detector",
    "YOLODetectorAdapter",
    "MockDetectorAdapter",
    "SceneQuality",
    "SceneQualityEvaluator",
    "IlluminationState",
    "WeatherEstimate",
    "AdaptivePreprocessor",
    "SmallObjectTilingEngine",
    "TemporalDetectionFusionEngine",
    "PerceptionConfidenceEngine",
    "PerceptionConfidenceVector",
    "PerceptionPipeline",
]
