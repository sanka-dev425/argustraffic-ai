"""
ArgusTraffic AI - Optical Camera Anti-Tamper & Lens Obstruction AI Engine
Detects:
1. Physical spray paint, lens cloth obstruction, or deliberate camera coverage (Low Entropy / Color Flatness)
2. Lens Defocusing / Accidental blur / Water condensation (Laplacian Spatial Frequency Variance)
3. Night Laser Blinding / Sensor Dazzling / Glare Saturation (Localized High-Intensity Luminescence)
"""

from dataclasses import dataclass
from enum import Enum
import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("argustraffic.tamper_detector")


class TamperState(str, Enum):
    CLEAR = "CLEAR_HEALTHY"
    OCCLUDED = "OCCLUSION_SPRAY_PAINT"
    DEFOCUSED = "DEFOCUSED_BLURRED"
    BLINDED = "SENSOR_BLINDED_LASER"


@dataclass
class TamperDiagnostics:
    camera_id: str
    state: TamperState
    is_tampered: bool
    blur_score: float         # Laplacian variance (lower means more blur)
    entropy_score: float      # Histogram spread (lower means flat/occluded)
    saturation_ratio: float   # % of extreme bright pixels
    confidence: float
    message: str
    analyzed_at: float


class OpticalTamperDetector:
    """
    Real-time edge optical diagnostics agent detecting physical camera tampering,
    focus shift, lens spray paint, and blinding attacks.
    """

    def __init__(
        self,
        min_blur_threshold: float = 35.0,        # Below this is considered defocused/blurred
        min_entropy_threshold: float = 3.2,      # Below this is considered flat/covered/spray-painted
        max_saturation_ratio: float = 0.28,      # Above 28% pure white pixels indicates blinding
    ):
        self.min_blur_threshold = min_blur_threshold
        self.min_entropy_threshold = min_entropy_threshold
        self.max_saturation_ratio = max_saturation_ratio

    def analyze_frame(self, frame: np.ndarray, camera_id: str = "CAM-01") -> TamperDiagnostics:
        """
        Analyzes a single camera frame for physical interference, vandalism, or defocus.
        """
        now = time.time()
        if frame is None or frame.size == 0:
            return TamperDiagnostics(
                camera_id=camera_id,
                state=TamperState.OCCLUDED,
                is_tampered=True,
                blur_score=0.0,
                entropy_score=0.0,
                saturation_ratio=0.0,
                confidence=1.0,
                message="Zero-byte corrupt or missing video frame",
                analyzed_at=now,
            )

        # 1. Convert to Grayscale
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Downsample for ultra-fast zero-latency processing
        h, w = gray.shape[:2]
        if w > 640:
            scale = 640.0 / w
            gray_small = cv2.resize(gray, (640, int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            gray_small = gray

        # 2. Compute Laplacian Variance for Focus/Blur Measurement
        laplacian = cv2.Laplacian(gray_small, cv2.CV_64F)
        blur_score = float(laplacian.var())

        # 3. Compute Shannon Entropy / Histogram Spread for Occlusion/Spray Detection
        hist = cv2.calcHist([gray_small], [0], None, [256], [0, 256]).ravel()
        hist_norm = hist / hist.sum()
        # Filter non-zero probabilities for entropy calculation
        non_zero = hist_norm[hist_norm > 0]
        entropy_score = float(-np.sum(non_zero * np.log2(non_zero)))

        # 4. Compute High-Intensity Pixel Saturation for Laser Blinding Detection
        total_pixels = gray_small.size
        saturated_pixels = int(np.sum(gray_small >= 250))
        saturation_ratio = float(saturated_pixels / total_pixels) if total_pixels > 0 else 0.0

        # 5. Diagnostic Decision Logic
        if saturation_ratio >= self.max_saturation_ratio:
            state = TamperState.BLINDED
            is_tampered = True
            msg = f"High-intensity sensor saturation ({saturation_ratio*100:.1f}%). Possible laser blinding or direct glare attack."
            conf = min(0.99, 0.70 + (saturation_ratio * 0.5))

        elif entropy_score < self.min_entropy_threshold:
            state = TamperState.OCCLUDED
            is_tampered = True
            msg = f"Low scene entropy ({entropy_score:.2f}). Lens obstructed, spray painted, or physically covered."
            conf = min(0.99, 0.75 + ((self.min_entropy_threshold - entropy_score) / self.min_entropy_threshold) * 0.25)

        elif blur_score < self.min_blur_threshold:
            state = TamperState.DEFOCUSED
            is_tampered = True
            msg = f"Low spatial frequency variance ({blur_score:.1f}). Camera lens defocused or severely blurred."
            conf = min(0.95, 0.70 + ((self.min_blur_threshold - blur_score) / self.min_blur_threshold) * 0.25)

        else:
            state = TamperState.CLEAR
            is_tampered = False
            msg = "Optical lens clarity, focus sharpness, and illumination entropy within nominal operating range."
            conf = 0.98

        return TamperDiagnostics(
            camera_id=camera_id,
            state=state,
            is_tampered=is_tampered,
            blur_score=round(blur_score, 2),
            entropy_score=round(entropy_score, 2),
            saturation_ratio=round(saturation_ratio, 4),
            confidence=round(conf, 2),
            message=msg,
            analyzed_at=now,
        )
