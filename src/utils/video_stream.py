"""
ArgusTraffic AI - Video Stream and Synthetic Traffic Scene Generator
Enables robust frame capture from Webcam, RTSP, Video File, or an internal
realistic high-fidelity traffic simulation engine with cars, wrong-way drivers, and jaywalkers.
"""

import math
import os
from pathlib import Path
import random
import time
from typing import Generator, Optional, Tuple

import cv2
import numpy as np


class SyntheticTrafficSimulator:
    """
    Generates dynamic, realistic multi-vehicle traffic scenes with lanes,
    animated vehicles, pedestrians, stalled cars, and wrong-way anomalies.
    """

    def __init__(self, width: int = 1280, height: int = 720):
        self.width = width
        self.height = height
        self.frame_count = 0

        # State for animated simulated entities
        self.south_cars = [
            {"x": width * 0.25, "y": float(i * 180), "speed": random.uniform(3.5, 5.0), "color": (40, 40, 220), "cls": "car"}
            for i in range(4)
        ]
        self.north_cars = [
            {"x": width * 0.65, "y": float(height - i * 190), "speed": random.uniform(3.5, 5.2), "color": (220, 150, 40), "cls": "car"}
            for i in range(4)
        ]
        # Wrong-way car on Southbound lane moving upwards!
        self.wrong_way_car = {
            "x": width * 0.38,
            "y": float(height - 50),
            "speed": -4.2,  # Moving UPWARDS against Southbound flow!
            "color": (255, 30, 30),
            "cls": "car",
            "active": True,
        }
        # Stalled vehicle on Northbound lane
        self.stalled_car = {
            "x": width * 0.76,
            "y": float(height * 0.35),
            "speed": 0.0,
            "color": (180, 50, 180),
            "cls": "truck",
        }
        # Pedestrian crossing mid-block
        self.pedestrian = {
            "x": float(width * 0.12),
            "y": float(height * 0.50),
            "speed": 1.4,
            "color": (20, 220, 20),
            "cls": "pedestrian",
        }

    def next_frame(self) -> np.ndarray:
        """Generates the next simulated video frame."""
        self.frame_count += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # 1. Asphalt Road Background
        frame[:] = (50, 50, 55)

        # Sidewalks / Curbs
        frame[:, : int(self.width * 0.12)] = (75, 75, 80)
        frame[:, int(self.width * 0.88) :] = (75, 75, 80)

        # Road Markings (Solid outer lines)
        cv2.line(frame, (int(self.width * 0.12), 0), (int(self.width * 0.12), self.height), (220, 220, 220), 3)
        cv2.line(frame, (int(self.width * 0.88), 0), (int(self.width * 0.88), self.height), (220, 220, 220), 3)

        # Double Yellow Center Divider
        cv2.line(frame, (int(self.width * 0.50) - 4, 0), (int(self.width * 0.50) - 4, self.height), (0, 215, 255), 3)
        cv2.line(frame, (int(self.width * 0.50) + 4, 0), (int(self.width * 0.50) + 4, self.height), (0, 215, 255), 3)

        # Dashed lane divider lines
        dash_len = 30
        dash_gap = 25
        for y in range(0, self.height, dash_len + dash_gap):
            cv2.line(frame, (int(self.width * 0.31), y), (int(self.width * 0.31), y + dash_len), (255, 255, 255), 2)
            cv2.line(frame, (int(self.width * 0.69), y), (int(self.width * 0.69), y + dash_len), (255, 255, 255), 2)

        # Crosswalk Zebra Stripes
        cw_top = int(self.height * 0.46)
        cw_bot = int(self.height * 0.54)
        for x in range(int(self.width * 0.14), int(self.width * 0.86), 40):
            cv2.rectangle(frame, (x, cw_top), (x + 22, cw_bot), (240, 240, 240), -1)

        # 2. Render & Update Southbound Vehicles
        for car in self.south_cars:
            car["y"] += car["speed"]
            if car["y"] > self.height + 60:
                car["y"] = -80
            cx, cy = int(car["x"]), int(car["y"])
            self._draw_vehicle(frame, cx, cy, 55, 100, car["color"])

        # 3. Render & Update Northbound Vehicles
        for car in self.north_cars:
            car["y"] -= car["speed"]
            if car["y"] < -80:
                car["y"] = self.height + 80
            cx, cy = int(car["x"]), int(car["y"])
            self._draw_vehicle(frame, cx, cy, 55, 100, car["color"])

        # 4. Render Wrong-Way Vehicle (Southbound lane, traveling North!)
        self.wrong_way_car["y"] += self.wrong_way_car["speed"]
        if self.wrong_way_car["y"] < -80:
            self.wrong_way_car["y"] = self.height + 50
        wx, wy = int(self.wrong_way_car["x"]), int(self.wrong_way_car["y"])
        self._draw_vehicle(frame, wx, wy, 52, 95, self.wrong_way_car["color"], heading_up=True)

        # 5. Render Stalled Vehicle (Stationary)
        sx, sy = int(self.stalled_car["x"]), int(self.stalled_car["y"])
        self._draw_vehicle(frame, sx, sy, 70, 140, self.stalled_car["color"])
        # Hazard flasher lights blinking every 15 frames
        if (self.frame_count // 15) % 2 == 0:
            cv2.circle(frame, (sx - 28, sy - 60), 6, (0, 140, 255), -1)
            cv2.circle(frame, (sx + 28, sy - 60), 6, (0, 140, 255), -1)
            cv2.circle(frame, (sx - 28, sy + 60), 6, (0, 140, 255), -1)
            cv2.circle(frame, (sx + 28, sy + 60), 6, (0, 140, 255), -1)

        # 6. Render Pedestrian
        self.pedestrian["x"] += self.pedestrian["speed"]
        if self.pedestrian["x"] > self.width * 0.88:
            self.pedestrian["x"] = self.width * 0.12
        px, py = int(self.pedestrian["x"]), int(self.pedestrian["y"])
        cv2.circle(frame, (px, py - 12), 7, (255, 200, 180), -1)
        cv2.rectangle(frame, (px - 6, py - 5), (px + 6, py + 15), (0, 180, 240), -1)
        cv2.line(frame, (px - 4, py + 15), (px - 6, py + 26), (40, 40, 40), 2)
        cv2.line(frame, (px + 4, py + 15), (px + 6, py + 26), (40, 40, 40), 2)

        return frame

    def _draw_vehicle(self, frame: np.ndarray, x: int, y: int, w: int, h: int, color: Tuple[int, int, int], heading_up: bool = False) -> None:
        """Renders vehicle body, windows, headlights, and shadow."""
        cv2.rectangle(frame, (x - w // 2 + 4, y - h // 2 + 4), (x + w // 2 + 4, y + h // 2 + 4), (30, 30, 30), -1)
        cv2.rectangle(frame, (x - w // 2, y - h // 2), (x + w // 2, y + h // 2), color, -1)
        cv2.rectangle(frame, (x - w // 2 + 6, y - h // 4), (x + w // 2 - 6, y + h // 4), (40, 40, 40), -1)
        cv2.rectangle(frame, (x - w // 2 + 8, y - h // 6), (x + w // 2 - 8, y + h // 6), color, -1)

        light_color = (0, 240, 255)
        tail_color = (0, 0, 230)
        front_y = y - h // 2 + 4 if heading_up else y + h // 2 - 4
        back_y = y + h // 2 - 4 if heading_up else y - h // 2 + 4

        cv2.circle(frame, (x - w // 2 + 8, front_y), 4, light_color, -1)
        cv2.circle(frame, (x + w // 2 - 8, front_y), 4, light_color, -1)
        cv2.circle(frame, (x - w // 2 + 8, back_y), 4, tail_color, -1)
        cv2.circle(frame, (x + w // 2 - 8, back_y), 4, tail_color, -1)


class VideoStream:
    """Unified video stream handler for Webcam, RTSP, Video Files, and Autonomous Simulation."""

    def __init__(self, source: Optional[str] = None, loop: bool = True):
        self.source = source
        self.loop = loop
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_synthetic = False
        self.synthetic_sim: Optional[SyntheticTrafficSimulator] = None
        self._init_source()

    def _init_source(self) -> None:
        # Check if source points to synthetic simulation or empty
        if self.source == "synthetic":
            self.is_synthetic = True
            self.synthetic_sim = SyntheticTrafficSimulator()
            return

        if self.source is None or self.source == "":
            # Try loading demo video if available
            root_dir = Path(__file__).resolve().parent.parent.parent
            demo_video = root_dir / "demo_traffic.mp4"
            if demo_video.exists():
                self.cap = cv2.VideoCapture(str(demo_video))
                if self.cap.isOpened():
                    self.is_synthetic = False
                    return
            self.is_synthetic = True
            self.synthetic_sim = SyntheticTrafficSimulator()
            return

        try:
            # Check numeric webcam index or file/RTSP URL
            src = int(self.source) if str(self.source).isdigit() else self.source
            self.cap = cv2.VideoCapture(src)
            if self.cap.isOpened():
                self.is_synthetic = False
            else:
                self.is_synthetic = True
                self.synthetic_sim = SyntheticTrafficSimulator()
        except Exception:
            self.is_synthetic = True
            self.synthetic_sim = SyntheticTrafficSimulator()

    def read_frame(self) -> Tuple[bool, np.ndarray]:
        """Reads the next available frame."""
        if not self.is_synthetic and self.cap is not None and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                if self.loop:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self.cap.read()
                else:
                    return False, None
            if ret and frame is not None:
                return True, frame

        # Fallback to simulation engine
        if self.synthetic_sim is None:
            self.synthetic_sim = SyntheticTrafficSimulator()
        return True, self.synthetic_sim.next_frame()

    def release(self) -> None:
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
