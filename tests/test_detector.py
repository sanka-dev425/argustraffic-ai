"""
Unit Tests for TrafficDetector.
"""

import numpy as np
import pytest
from src.core.detector import Detection, TrafficDetector


def test_detector_initialization():
    detector = TrafficDetector(model_name="yolov8n.pt", device="cpu")
    assert detector is not None
    assert detector.confidence_threshold == 0.35
    assert len(detector.target_classes) > 0


def test_detector_inference_on_blank_frame():
    detector = TrafficDetector(model_name="yolov8n.pt", device="cpu")
    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    detections, latency_ms = detector.detect(frame)

    assert isinstance(detections, list)
    assert latency_ms >= 0.0


def test_detection_dataclass_properties():
    det = Detection(
        bbox=(100.0, 100.0, 200.0, 300.0),
        confidence=0.92,
        class_id=2,
        class_name="car",
    )
    assert det.width == 100.0
    assert det.height == 200.0
    assert det.area == 20000.0
    assert det.center == (150.0, 200.0)
