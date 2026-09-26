"""
ArgusTraffic AI - Perception Engine: Model Registry & Lifecycle Manager
Maintains registered vision checkpoints, cryptographic checksums,
and deployment approval gates.
"""

from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.perception.detector.base import ModelFramework, ModelMetadata

logger = logging.getLogger("argustraffic.perception.registry")


class ModelRegistry:
    """Enterprise registry for vision models, checkpoint integrity, and lifecycle stages."""

    def __init__(self, registry_file: Optional[Path] = None):
        self.registry_file = registry_file
        self._models: Dict[str, ModelMetadata] = {}
        self._bootstrap_default_models()

    def _bootstrap_default_models(self) -> None:
        """Registers default platform reference models."""
        self.register_model(
            ModelMetadata(
                model_id="yolov8n_traffic",
                version="8.3.0",
                framework=ModelFramework.ULTRALYTICS_YOLO,
                input_size=640,
                precision="FP16",
                target_classes=["pedestrian", "bicycle", "car", "motorcycle", "bus", "truck"],
                expected_fps=35.0,
                expected_latency_ms=28.5,
                approved_for_production=True,
            )
        )
        self.register_model(
            ModelMetadata(
                model_id="rtdetr_traffic",
                version="1.0.0",
                framework=ModelFramework.RT_DETR,
                input_size=640,
                precision="FP16",
                target_classes=["pedestrian", "bicycle", "car", "motorcycle", "bus", "truck"],
                expected_fps=28.0,
                expected_latency_ms=35.0,
                approved_for_production=True,
            )
        )
        self.register_model(
            ModelMetadata(
                model_id="mock_test_detector",
                version="1.0.0",
                framework=ModelFramework.MOCK,
                input_size=640,
                precision="FP32",
                target_classes=["pedestrian", "car", "truck"],
                expected_fps=1000.0,
                expected_latency_ms=0.1,
                approved_for_production=True,
            )
        )

    def register_model(self, metadata: ModelMetadata) -> None:
        """Registers a new model version into the registry."""
        self._models[metadata.model_id] = metadata

    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        return self._models.get(model_id)

    def list_models(self) -> List[ModelMetadata]:
        return list(self._models.values())

    def verify_checkpoint_integrity(self, file_path: Path, expected_sha256: str) -> bool:
        """Cryptographically verifies that model weights on disk match the registry SHA-256."""
        if not file_path.exists():
            return False
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        calculated = hasher.hexdigest()
        return calculated.lower() == expected_sha256.lower()

    def get_summary_table(self) -> List[Dict[str, Any]]:
        """Returns diagnostic summary of all registered models."""
        return [
            {
                "model_id": m.model_id,
                "version": m.version,
                "framework": m.framework.value,
                "input_size": m.input_size,
                "precision": m.precision,
                "approved": m.approved_for_production,
            }
            for m in self._models.values()
        ]


# Singleton instance
_GLOBAL_REGISTRY: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ModelRegistry()
    return _GLOBAL_REGISTRY
