"""
ArgusTraffic AI - Perception Engine: Deterministic Mock Detector Adapter
Provides deterministic detections for testing, headless CI environments, and benchmarks.
"""

import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.core.interfaces import Detection
from src.perception.detector.base import DetectorBackend


class MockDetectorAdapter(DetectorBackend):
    """Deterministic mock detector adapter."""

    def __init__(self, predefined_detections: Optional[List[Detection]] = None):
        self.predefined_detections = predefined_detections
        self.is_loaded = True

    def load(self, model_config: Dict[str, Any]) -> bool:
        self.is_loaded = True
        return True

    def infer(self, frame: np.ndarray, context: Optional[Dict[str, Any]] = None) -> Tuple[List[Detection], float]:
        t0 = time.perf_counter()
        h, w = frame.shape[:2]

        if self.predefined_detections is not None:
            dets = [d for d in self.predefined_detections]
        else:
            dets = [
                Detection(
                    bbox=(w * 0.20, h * 0.40, w * 0.35, h * 0.65),
                    confidence=0.92,
                    class_id=2,
                    class_name="car",
                ),
                Detection(
                    bbox=(w * 0.60, h * 0.50, w * 0.85, h * 0.80),
                    confidence=0.88,
                    class_id=7,
                    class_name="truck",
                ),
            ]

        latency = (time.perf_counter() - t0) * 1000.0
        return dets, latency

    def warmup(self, iterations: int = 1) -> bool:
        return True

    def health(self) -> Dict[str, Any]:
        return {"status": "ONLINE", "backend": "MOCK", "vram_allocated_mb": 0.0}

    def capabilities(self) -> Dict[str, Any]:
        return {"supported_classes": ["car", "truck", "bus", "pedestrian"], "fp16": True}

    def unload(self) -> None:
        self.is_loaded = False
