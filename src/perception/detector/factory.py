"""
ArgusTraffic AI - Perception Engine: Detector Factory
Instantiates detector backends dynamically based on configuration or registry selection.
"""

from typing import Any, Dict, Optional
from src.perception.detector.base import ComputeBackend, DetectorBackend, ModelFramework
from src.perception.detector.mock_adapter import MockDetectorAdapter
from src.perception.detector.yolo_adapter import YOLODetectorAdapter


def create_detector(
    framework: ModelFramework = ModelFramework.ULTRALYTICS_YOLO,
    model_path: str = "yolov8n.pt",
    device: str = "auto",
    confidence_threshold: float = 0.35,
    iou_threshold: float = 0.45,
    input_size: int = 640,
) -> DetectorBackend:
    """Factory function instantiating the requested perception detector adapter."""
    if framework == ModelFramework.MOCK:
        return MockDetectorAdapter()
    elif framework in [ModelFramework.ULTRALYTICS_YOLO, ModelFramework.RT_DETR]:
        return YOLODetectorAdapter(
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            device=device,
            input_size=input_size,
        )
    else:
        # Default fallback to YOLO adapter
        return YOLODetectorAdapter(
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            device=device,
            input_size=input_size,
        )
