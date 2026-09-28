"""
ArgusTraffic AI - Core Object Detector
Encapsulates YOLOv8 / YOLOv11 / RT-DETR inference with GPU acceleration,
FP16 support, and zero-copy Tensor/NumPy pipeline.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import torch
try:
    import torchvision
    import torchvision.ops
except ImportError:
    pass

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False

logger = logging.getLogger("argustraffic.detector")


def apply_clahe_enhancement(
    frame: np.ndarray,
    clip_limit: float = 2.5,
    tile_grid_size: Tuple[int, int] = (8, 8),
) -> np.ndarray:
    """
    Applies Contrast Limited Adaptive Histogram Equalization (CLAHE) on the luminance (L) channel
    of the LAB color space. Balances nighttime headlight glare, deep shadows, and foggy weather.
    """
    if frame is None or frame.size == 0:
        return frame
    try:
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
        cl = clahe.apply(l_channel)
        merged = cv2.merge((cl, a_channel, b_channel))
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    except Exception as e:
        logger.debug(f"CLAHE enhancement failed, returning raw frame: {e}")
        return frame


def check_optical_tampering(
    frame: np.ndarray,
    min_variance: float = 12.0,
    dark_threshold: float = 14.0,
    bright_threshold: float = 242.0,
) -> Dict[str, Any]:
    """
    Anti-Tampering Watchdog: Inspects frame focus, luminance entropy, and sharpness variance
    to instantly detect camera lens paint spraying, blackout covers, intentional disorientation,
    or blinding high-intensity headlight/laser flares.
    """
    if frame is None or frame.size == 0:
        return {"tampered": True, "reason": "empty_frame", "score": 0.0, "mean_brightness": 0.0}

    try:
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        mean_val = float(np.mean(gray))
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Check conditions
        if mean_val < dark_threshold:
            return {
                "tampered": True,
                "reason": "lens_covered_or_blackout",
                "variance": laplacian_var,
                "mean_brightness": mean_val,
            }
        elif mean_val > bright_threshold:
            return {
                "tampered": True,
                "reason": "blinding_glare_or_laser",
                "variance": laplacian_var,
                "mean_brightness": mean_val,
            }
        elif laplacian_var < min_variance:
            return {
                "tampered": True,
                "reason": "lens_spray_or_severe_defocus",
                "variance": laplacian_var,
                "mean_brightness": mean_val,
            }

        return {
            "tampered": False,
            "reason": "nominal",
            "variance": laplacian_var,
            "mean_brightness": mean_val,
        }
    except Exception as e:
        logger.error(f"Error checking optical tampering: {e}")
        return {"tampered": False, "reason": "inspection_error", "variance": 0.0, "mean_brightness": 0.0}



@dataclass
class Detection:
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    confidence: float
    class_id: int
    class_name: str
    track_id: Optional[int] = None
    velocity: Optional[Tuple[float, float]] = None  # (vx, vy) in px/frame

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


class TrafficDetector:
    """High-performance object detection wrapper supporting YOLO models."""

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        confidence_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        target_classes: Optional[List[int]] = None,
        device: str = "auto",
        half_precision: bool = True,
        input_size: int = 640,
        enable_clahe: bool = False,
    ):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.target_classes = target_classes or [0, 1, 2, 3, 5, 7]  # COCO person, bike, car, moto, bus, truck
        self.input_size = input_size
        self.enable_clahe = enable_clahe

        # Resolve compute device
        if device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self.half = half_precision and (self.device == "cuda")
        self.model = None
        self.class_names: Dict[int, str] = {}
        self._load_model()

    def _load_model(self) -> None:
        """Loads and warms up the detection model."""
        if not ULTRALYTICS_AVAILABLE:
            logger.warning("Ultralytics is not installed. Detector falling back to mock mode.")
            self._setup_mock_names()
            return

        try:
            logger.info(f"Loading model '{self.model_name}' on {self.device} (FP16={self.half})...")
            model_file = Path(self.model_name)
            if not model_file.is_absolute() and not model_file.exists():
                meipass = getattr(sys, "_MEIPASS", None)
                if meipass and (Path(meipass) / self.model_name).exists():
                    model_file = Path(meipass) / self.model_name
                elif (Path(__file__).resolve().parent.parent.parent / self.model_name).exists():
                    model_file = Path(__file__).resolve().parent.parent.parent / self.model_name
                elif (Path(__file__).resolve().parent.parent / self.model_name).exists():
                    model_file = Path(__file__).resolve().parent.parent / self.model_name

            self.model = YOLO(str(model_file))
            self.class_names = self.model.names if hasattr(self.model, "names") else {}

            # Perform warm-up inference
            dummy_frame = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
            predict_kwargs = {"source": dummy_frame, "device": self.device, "verbose": False}
            if self.half:
                predict_kwargs["half"] = True
            self.model.predict(**predict_kwargs)
            logger.info("Detector initialized and warm-up completed successfully.")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}. Fallback to mock detector.")
            self.model = None
            self._setup_mock_names()

    def _setup_mock_names(self) -> None:
        self.class_names = {
            0: "pedestrian",
            1: "bicycle",
            2: "car",
            3: "motorcycle",
            5: "bus",
            7: "truck",
        }

    def detect(self, frame: np.ndarray) -> Tuple[List[Detection], float]:
        """
        Runs object detection on a single RGB or BGR frame.
        
        Returns:
            Tuple of (List[Detection], inference_time_ms)
        """
        start_time = time.perf_counter()
        if self.enable_clahe:
            frame = apply_clahe_enhancement(frame)

        if self.model is None or not ULTRALYTICS_AVAILABLE:
            # Fallback mock detection for unit tests or fallback mode
            dets = self._mock_detect(frame)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return dets, elapsed_ms

        predict_kwargs = {
            "source": frame,
            "conf": self.confidence_threshold,
            "iou": self.iou_threshold,
            "classes": self.target_classes,
            "device": self.device,
            "imgsz": self.input_size,
            "verbose": False,
        }
        if self.half:
            predict_kwargs["half"] = True

        results = self.model.predict(**predict_kwargs)

        detections: List[Detection] = []
        if len(results) > 0:
            result = results[0]
            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                cls_ids = boxes.cls.cpu().numpy().astype(int)

                for box, conf, cls_id in zip(xyxy, confs, cls_ids):
                    cls_name = self.class_names.get(cls_id, str(cls_id))
                    # Normalize labels
                    if cls_name == "person":
                        cls_name = "pedestrian"

                    detections.append(
                        Detection(
                            bbox=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                            confidence=float(conf),
                            class_id=int(cls_id),
                            class_name=cls_name,
                        )
                    )

        inference_time_ms = (time.perf_counter() - start_time) * 1000.0
        return detections, inference_time_ms

    def _mock_detect(self, frame: np.ndarray) -> List[Detection]:
        """Provides simulated detections for test setups without weight downloads."""
        h, w = frame.shape[:2]
        return [
            Detection(
                bbox=(w * 0.2, h * 0.4, w * 0.4, h * 0.65),
                confidence=0.92,
                class_id=2,
                class_name="car",
            ),
            Detection(
                bbox=(w * 0.6, h * 0.5, w * 0.85, h * 0.8),
                confidence=0.88,
                class_id=7,
                class_name="truck",
            ),
        ]
