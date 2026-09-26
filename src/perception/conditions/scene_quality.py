"""
ArgusTraffic AI - Perception Engine: Scene Quality & Environmental Analysis
Evaluates frame sharpness, illumination, contrast, glare, and low-light states
to dynamically steer adaptive preprocessing and confidence calibration.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple
import cv2
import numpy as np


class IlluminationState(str, Enum):
    DAYLIGHT = "DAYLIGHT"
    LOW_LIGHT = "LOW_LIGHT"
    NIGHT = "NIGHT"
    GLARE = "GLARE"
    OVEREXPOSED = "OVEREXPOSED"


class WeatherEstimate(str, Enum):
    CLEAR = "CLEAR"
    OVERCAST = "OVERCAST"
    FOG_HAZE = "FOG_HAZE"
    RAIN_ADVERSE = "RAIN_ADVERSE"


@dataclass
class SceneQuality:
    brightness: float          # 0 to 255
    contrast: float            # standard deviation of gray levels
    sharpness_score: float     # Laplacian variance
    glare_ratio: float         # percentage of blown-out pixels
    is_low_light: bool
    is_blurry: bool
    illumination_state: IlluminationState
    weather_estimate: WeatherEstimate
    overall_quality_score: float  # 0.0 (unusable) to 1.0 (crystal clear)


class SceneQualityEvaluator:
    """Computes real-time spatial and statistical scene characteristics."""

    def __init__(self, blur_threshold: float = 80.0, low_light_threshold: float = 50.0):
        self.blur_threshold = blur_threshold
        self.low_light_threshold = low_light_threshold

    def evaluate(self, frame: np.ndarray) -> SceneQuality:
        """Evaluates scene clarity and ambient lighting conditions on a BGR frame."""
        # Convert to grayscale
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # 1. Brightness & Contrast
        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))

        # 2. Sharpness (Laplacian variance)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = float(laplacian.var())

        # 3. Glare Ratio (pixels > 250)
        glare_ratio = float(np.count_nonzero(gray >= 250)) / float(gray.size)

        # 4. Illumination State Classification
        if mean_val < 30.0:
            illum = IlluminationState.NIGHT
            is_low_light = True
        elif mean_val < self.low_light_threshold:
            illum = IlluminationState.LOW_LIGHT
            is_low_light = True
        elif glare_ratio > 0.15:
            illum = IlluminationState.GLARE
            is_low_light = False
        elif mean_val > 210.0:
            illum = IlluminationState.OVEREXPOSED
            is_low_light = False
        else:
            illum = IlluminationState.DAYLIGHT
            is_low_light = False

        # 5. Blur Detection
        is_blurry = sharpness < self.blur_threshold

        # 6. Weather estimation heuristic
        # Fog/haze typically causes low contrast + low sharpness despite moderate brightness
        if std_val < 25.0 and mean_val > 90.0:
            weather = WeatherEstimate.FOG_HAZE
        elif is_low_light and std_val < 35.0:
            weather = WeatherEstimate.RAIN_ADVERSE
        elif std_val < 40.0:
            weather = WeatherEstimate.OVERCAST
        else:
            weather = WeatherEstimate.CLEAR

        # 7. Overall Composite Quality Score (0.0 to 1.0)
        sharpness_factor = min(1.0, sharpness / 200.0)
        contrast_factor = min(1.0, std_val / 60.0)
        brightness_penalty = 0.0
        if is_low_light:
            brightness_penalty = (self.low_light_threshold - mean_val) / self.low_light_threshold * 0.4
        elif illum in [IlluminationState.GLARE, IlluminationState.OVEREXPOSED]:
            brightness_penalty = 0.3

        raw_score = (0.5 * sharpness_factor + 0.5 * contrast_factor) - brightness_penalty
        overall_score = round(max(0.05, min(1.0, raw_score)), 2)

        return SceneQuality(
            brightness=round(mean_val, 1),
            contrast=round(std_val, 1),
            sharpness_score=round(sharpness, 1),
            glare_ratio=round(glare_ratio, 3),
            is_low_light=is_low_light,
            is_blurry=is_blurry,
            illumination_state=illum,
            weather_estimate=weather,
            overall_quality_score=overall_score,
        )
