"""
ArgusTraffic AI - Perception Engine: Adaptive Preprocessing Pipeline
Applies scene-aware dynamic range expansion, CLAHE enhancement for night scenes,
and aspect-preserving letterbox scaling.
"""

from typing import Tuple
import cv2
import numpy as np

from src.perception.conditions.scene_quality import IlluminationState, SceneQuality


class AdaptivePreprocessor:
    """Dynamically enhances video frames based on measured environmental scene conditions."""

    def __init__(self, target_size: int = 640):
        self.target_size = target_size
        self._clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

    def preprocess(
        self, frame: np.ndarray, quality: SceneQuality
    ) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """
        Enhances frame dynamically and computes letterbox geometry.

        Returns:
            (processed_frame, scale_factor, (pad_x, pad_y))
        """
        enhanced = frame

        # 1. Low-light / Night Adaptive Enhancement (CLAHE on L-channel in LAB space)
        if quality.is_low_light or quality.illumination_state == IlluminationState.NIGHT:
            enhanced = self._apply_clahe_enhancement(enhanced)

        # 2. Letterbox Resizing
        letterboxed, scale, pads = self.letterbox(enhanced, self.target_size)
        return letterboxed, scale, pads

    def _apply_clahe_enhancement(self, frame: np.ndarray) -> np.ndarray:
        """Expands contrast in low-light and shadow regions without blowing out highlights."""
        try:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l_enhanced = self._clahe.apply(l)
            merged = cv2.merge((l_enhanced, a, b))
            return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        except Exception:
            return frame

    @staticmethod
    def letterbox(
        img: np.ndarray, target_shape: int = 640, color: Tuple[int, int, int] = (114, 114, 114)
    ) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """Resize image to target square maintaining aspect ratio with uniform border padding."""
        shape = img.shape[:2]  # (height, width)
        r = min(target_shape / shape[0], target_shape / shape[1])

        # Compute unpadded new dimensions
        new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
        dw, dh = target_shape - new_unpad[0], target_shape - new_unpad[1]
        dw /= 2
        dh /= 2

        if shape[::-1] != new_unpad:
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)

        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
        return img, r, (int(left), int(top))
