"""
ArgusTraffic AI - Perception Engine: Detector Backend Protocols & Interfaces
Enforces strict model-agnostic and hardware-independent abstraction.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable
import numpy as np

from src.core.interfaces import Detection


class ModelFramework(str, Enum):
    ULTRALYTICS_YOLO = "ultralytics_yolo"
    RT_DETR = "rt_detr"
    ONNX_RUNTIME = "onnx_runtime"
    TENSORRT = "tensorrt"
    PYTORCH = "pytorch"
    MOCK = "mock"


class ComputeBackend(str, Enum):
    CPU = "cpu"
    CUDA = "cuda"
    TENSORRT = "tensorrt"
    MPS = "mps"
    AUTO = "auto"


@dataclass
class ModelMetadata:
    model_id: str
    version: str
    framework: ModelFramework
    input_size: int = 640
    precision: str = "FP16"
    target_classes: List[str] = field(default_factory=lambda: ["car", "truck", "bus", "motorcycle", "bicycle", "pedestrian"])
    min_driver_version: Optional[str] = None
    cuda_requirement: Optional[str] = None
    expected_fps: float = 30.0
    expected_latency_ms: float = 30.0
    sha256_checksum: Optional[str] = None
    license: str = "AGPL-3.0 / Commercial"
    approved_for_production: bool = True


@runtime_checkable
class DetectorBackend(Protocol):
    """Abstract interface that all computer vision detector adapters must implement."""

    def load(self, model_config: Dict[str, Any]) -> bool:
        """Loads and compiles model weights into target accelerator memory."""
        ...

    def infer(self, frame: np.ndarray, context: Optional[Dict[str, Any]] = None) -> Tuple[List[Detection], float]:
        """
        Executes vision inference on a single BGR/RGB frame.
        Returns:
            Tuple of (List[Detection], latency_ms)
        """
        ...

    def warmup(self, iterations: int = 1) -> bool:
        """Executes warm-up passes to compile kernels and eliminate cold-start latency."""
        ...

    def health(self) -> Dict[str, Any]:
        """Returns hardware, memory, and operational health diagnostics."""
        ...

    def capabilities(self) -> Dict[str, Any]:
        """Reports supported input resolutions, classes, and backend acceleration."""
        ...

    def unload(self) -> None:
        """Frees accelerator VRAM and runtime resources."""
        ...
