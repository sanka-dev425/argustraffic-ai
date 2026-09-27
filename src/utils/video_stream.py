"""
ArgusTraffic AI - Ultra-HD Photorealistic CCTV Traffic Scene Engine
Renders realistic multi-lane industrial CCTV camera footage with textured asphalt,
specular metallic vehicle shading, projector headlight cones, brake lights,
emergency strobe lights, pedestrians, optical ANPR plates, and OSD telemetry.
Author: Saptha Sanka (ArgusTraffic Autonomous Systems)
"""

import datetime
import math
import os
from pathlib import Path
import random
import time
from typing import Generator, List, Optional, Tuple

import cv2
import numpy as np


class SyntheticTrafficSimulator:
    """
    High-fidelity industrial CCTV traffic simulator.
    Simulates high-angle municipal CCTV footage with perspective road markings,
    metallic vehicle contours, volumetric headlight projection, emergency flashers,
    ANPR micro-plates, pedestrian kinematics, and authentic camera OSD telemetry.
    """

    def __init__(self, width: int = 1280, height: int = 720):
        self.width = width
        self.height = height
        self.frame_count = 0

        # Precompute realistic asphalt road texture
        self.road_texture = self._build_photorealistic_road()

        # Realistic vehicle fleet
        self.south_vehicles = [
            {"x": width * 0.22, "y": 80.0, "speed": 4.6, "type": "sedan", "color": (195, 195, 205), "plate": "WP-CAR-7821", "len": 102, "w": 50},
            {"x": width * 0.36, "y": 270.0, "speed": 4.2, "type": "suv", "color": (32, 45, 135), "plate": "NW-SUV-9014", "len": 112, "w": 54},
            {"x": width * 0.22, "y": 510.0, "speed": 4.9, "type": "police", "color": (240, 240, 245), "plate": "POLICE-09", "len": 104, "w": 52},
            {"x": width * 0.36, "y": 700.0, "speed": 3.6, "type": "bus", "color": (20, 130, 210), "plate": "SP-BUS-4491", "len": 165, "w": 60},
        ]

        self.north_vehicles = [
            {"x": width * 0.64, "y": float(height - 90), "speed": 4.7, "type": "sedan", "color": (190, 150, 45), "plate": "CP-CAR-5520", "len": 100, "w": 50},
            {"x": width * 0.78, "y": float(height - 290), "speed": 3.7, "type": "truck", "color": (130, 135, 140), "plate": "WP-TRK-8812", "len": 175, "w": 64},
            {"x": width * 0.64, "y": float(height - 500), "speed": 4.5, "type": "suv", "color": (28, 28, 30), "plate": "CP-SUV-1029", "len": 112, "w": 54},
        ]

        # Wrong-Way Critical Anomaly (Heading North in Southbound Lane 2)
        self.wrong_way_car = {
            "x": width * 0.36,
            "y": float(height - 60),
            "speed": -4.2,
            "type": "sedan",
            "color": (220, 38, 38),
            "plate": "CP-HVY-3012",
            "len": 102,
            "w": 50,
        }

        # Stalled Commercial Freight Vehicle on Northbound Shoulder
        self.stalled_truck = {
            "x": width * 0.81,
            "y": float(height * 0.30),
            "speed": 0.0,
            "type": "truck",
            "color": (175, 85, 25),
            "plate": "WP-FLT-0041",
            "len": 170,
            "w": 62,
        }

        # Pedestrian crossing
        self.pedestrian = {
            "x": float(width * 0.12),
            "y": float(height * 0.50),
            "speed": 1.1,
        }

    def _build_photorealistic_road(self) -> np.ndarray:
        """Constructs textured high-grade asphalt with aggregate grain and curb wear."""
        road = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # Deep dark gray asphalt base
        road[:] = (36, 38, 42)

        # Micro-texture noise
        noise = np.random.normal(0, 4, (self.height, self.width)).astype(np.int16)
        for c in range(3):
            ch = road[:, :, c].astype(np.int16) + noise
            road[:, :, c] = np.clip(ch, 0, 255).astype(np.uint8)

        # Sidewalk / Curbs on sides with stone texture
        curb_w = int(self.width * 0.12)
        road[:, :curb_w] = (58, 62, 68)
        road[:, self.width - curb_w :] = (58, 62, 68)

        # Subtle oil slick traces in lane centers
        lane_xs = [int(self.width * 0.22), int(self.width * 0.36), int(self.width * 0.64), int(self.width * 0.78)]
        for lx in lane_xs:
            cv2.line(road, (lx, 0), (lx, self.height), (26, 28, 30), 16)

        return road

    def next_frame(self) -> np.ndarray:
        """Renders the next photorealistic CCTV traffic frame."""
        self.frame_count += 1
        frame = self.road_texture.copy()

        # 1. Road Geometry & Markings
        curb_w = int(self.width * 0.12)
        # Outer Solid White Edge Lines
        cv2.line(frame, (curb_w, 0), (curb_w, self.height), (225, 228, 232), 3, cv2.LINE_AA)
        cv2.line(frame, (self.width - curb_w, 0), (self.width - curb_w, self.height), (225, 228, 232), 3, cv2.LINE_AA)

        # Center Double Yellow Median Divider with Cat's Eye Reflectors
        cx = int(self.width * 0.50)
        cv2.line(frame, (cx - 6, 0), (cx - 6, self.height), (0, 210, 255), 3, cv2.LINE_AA)
        cv2.line(frame, (cx + 6, 0), (cx + 6, self.height), (0, 210, 255), 3, cv2.LINE_AA)
        for my in range(0, self.height, 48):
            cv2.circle(frame, (cx, my), 2, (0, 240, 255), -1, cv2.LINE_AA)

        # Dashed White Lane Lines
        dash_len, dash_gap = 38, 32
        offset = (self.frame_count * 2) % (dash_len + dash_gap)
        for y in range(-dash_len + offset, self.height + dash_len, dash_len + dash_gap):
            cv2.line(frame, (int(self.width * 0.29), y), (int(self.width * 0.29), y + dash_len), (235, 238, 242), 2, cv2.LINE_AA)
            cv2.line(frame, (int(self.width * 0.71), y), (int(self.width * 0.71), y + dash_len), (235, 238, 242), 2, cv2.LINE_AA)

        # High-Contrast Pedestrian Crosswalk (Zebra Stripes)
        cw_top = int(self.height * 0.46)
        cw_bot = int(self.height * 0.54)
        for x in range(curb_w + 14, self.width - curb_w - 20, 40):
            cv2.rectangle(frame, (x, cw_top), (x + 22, cw_bot), (235, 238, 242), -1)

        # 2. Render Southbound Vehicles
        for v in self.south_vehicles:
            v["y"] += v["speed"]
            if v["y"] > self.height + 140:
                v["y"] = -120
                v["speed"] = random.uniform(4.0, 5.2)
            self._render_vehicle(frame, int(v["x"]), int(v["y"]), v["w"], v["len"], v["color"], v["type"], v["plate"], heading_south=True)

        # 3. Render Northbound Vehicles
        for v in self.north_vehicles:
            v["y"] -= v["speed"]
            if v["y"] < -140:
                v["y"] = self.height + 120
                v["speed"] = random.uniform(4.0, 5.2)
            self._render_vehicle(frame, int(v["x"]), int(v["y"]), v["w"], v["len"], v["color"], v["type"], v["plate"], heading_south=False)

        # 4. Render Critical Wrong-Way Anomaly (Red Sedan travelling North in Southbound Lane!)
        self.wrong_way_car["y"] += self.wrong_way_car["speed"]
        if self.wrong_way_car["y"] < -140:
            self.wrong_way_car["y"] = self.height + 60
        self._render_vehicle(
            frame,
            int(self.wrong_way_car["x"]),
            int(self.wrong_way_car["y"]),
            self.wrong_way_car["w"],
            self.wrong_way_car["len"],
            self.wrong_way_car["color"],
            "sedan",
            self.wrong_way_car["plate"],
            heading_south=False,
            is_hazard=True,
        )

        # 5. Render Stalled Heavy Truck on Shoulder with Hazard Strobes
        sx, sy = int(self.stalled_truck["x"]), int(self.stalled_truck["y"])
        self._render_vehicle(frame, sx, sy, self.stalled_truck["w"], self.stalled_truck["len"], self.stalled_truck["color"], "truck", self.stalled_truck["plate"], heading_south=False)
        if (self.frame_count // 10) % 2 == 0:
            # Amber hazard strobe blinkers
            cv2.circle(frame, (sx - 28, sy - 80), 6, (0, 185, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (sx + 28, sy - 80), 6, (0, 185, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (sx - 28, sy + 80), 6, (0, 185, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (sx + 28, sy + 80), 6, (0, 185, 255), -1, cv2.LINE_AA)

        # 6. Render Pedestrian with Walking Kinematics
        self.pedestrian["x"] += self.pedestrian["speed"]
        if self.pedestrian["x"] > self.width - curb_w:
            self.pedestrian["x"] = curb_w
        self._render_pedestrian(frame, int(self.pedestrian["x"]), int(self.pedestrian["y"]))

        # 7. CCTV OSD HUD Telemetry
        self._render_cctv_osd(frame)

        return frame

    def _render_vehicle(
        self,
        frame: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
        color: Tuple[int, int, int],
        vtype: str,
        plate: str,
        heading_south: bool = True,
        is_hazard: bool = False,
    ) -> None:
        """Renders realistic vehicle with metallic shading, windshield, lighting, and soft ground shadow."""
        hw, hh = w // 2, h // 2

        # 1. Soft Ambient Vehicle Shadow
        shadow_poly = np.array([
            [x - hw - 8, y - hh + 4],
            [x + hw + 8, y - hh + 4],
            [x + hw + 10, y + hh + 10],
            [x - hw - 6, y + hh + 10],
        ], np.int32)
        cv2.fillPoly(frame, [shadow_poly], (18, 20, 22))

        # 2. Volumetric Headlight Beams projected on road
        if heading_south:
            beam_poly1 = np.array([[x - hw + 8, y + hh], [x - hw - 14, y + hh + 75], [x - hw + 24, y + hh + 75]], np.int32)
            beam_poly2 = np.array([[x + hw - 8, y + hh], [x + hw - 24, y + hh + 75], [x + hw + 14, y + hh + 75]], np.int32)
            cv2.fillPoly(frame, [beam_poly1], (48, 54, 58))
            cv2.fillPoly(frame, [beam_poly2], (48, 54, 58))
        else:
            beam_poly1 = np.array([[x - hw + 8, y - hh], [x - hw - 14, y - hh - 75], [x - hw + 24, y - hh - 75]], np.int32)
            beam_poly2 = np.array([[x + hw - 8, y - hh], [x + hw - 24, y - hh - 75], [x + hw + 14, y - hh - 75]], np.int32)
            cv2.fillPoly(frame, [beam_poly1], (48, 54, 58))
            cv2.fillPoly(frame, [beam_poly2], (48, 54, 58))

        # 3. Main Vehicle Body Chassis (Contoured rounded metallic polygon)
        body_poly = np.array([
            [x - hw + 6, y - hh],
            [x + hw - 6, y - hh],
            [x + hw, y - hh + 10],
            [x + hw, y + hh - 10],
            [x + hw - 6, y + hh],
            [x - hw + 6, y + hh],
            [x - hw, y + hh - 10],
            [x - hw, y - hh + 10],
        ], np.int32)
        cv2.fillPoly(frame, [body_poly], color)
        # Body Border Accent
        border_col = (max(0, color[0] - 40), max(0, color[1] - 40), max(0, color[2] - 40))
        cv2.polylines(frame, [body_poly], True, border_col, 2, cv2.LINE_AA)

        # 4. Windshields, Cabin Roof, Windows
        cabin_w = hw - 6
        front_y = y + int(hh * 0.35) if heading_south else y - int(hh * 0.35)
        rear_y = y - int(hh * 0.35) if heading_south else y + int(hh * 0.35)

        if vtype == "bus":
            # Long passenger cabin with tinted glass strips
            cv2.rectangle(frame, (x - cabin_w, y - hh + 15), (x + cabin_w, y + hh - 15), (24, 30, 36), -1)
            # Roof AC unit
            cv2.rectangle(frame, (x - 12, y - 30), (x + 12, y + 30), (220, 225, 230), -1)
        elif vtype == "truck":
            # Cab front + Long Freight Container
            cab_h = int(hh * 0.4)
            cab_y = y + hh - cab_h if heading_south else y - hh
            cv2.rectangle(frame, (x - cabin_w, cab_y), (x + cabin_w, cab_y + cab_h), (max(0, color[0] - 30), max(0, color[1] - 30), max(0, color[2] - 30)), -1)
            # Trailer container with safety ribs
            trail_y1 = y - hh if heading_south else y - hh + cab_h + 8
            trail_y2 = y + hh - cab_h - 8 if heading_south else y + hh
            cv2.rectangle(frame, (x - hw, trail_y1), (x + hw, trail_y2), (180, 185, 190), -1)
            for rib_y in range(trail_y1 + 10, trail_y2 - 10, 18):
                cv2.line(frame, (x - hw + 2, rib_y), (x + hw - 2, rib_y), (140, 145, 150), 2)
        else:
            # Passenger Sedan / SUV / Police Cruiser
            # Front Windshield with subtle sky reflection
            cv2.rectangle(frame, (x - cabin_w, front_y - 8), (x + cabin_w, front_y + 8), (28, 38, 48), -1)
            cv2.line(frame, (x - cabin_w + 3, front_y), (x + cabin_w - 3, front_y), (80, 110, 140), 1, cv2.LINE_AA)
            # Rear Windshield
            cv2.rectangle(frame, (x - cabin_w, rear_y - 8), (x + cabin_w, rear_y + 8), (22, 28, 35), -1)
            # Metallic Roof Center
            roof_col = (max(0, color[0] - 20), max(0, color[1] - 20), max(0, color[2] - 20))
            cv2.rectangle(frame, (x - cabin_w + 3, min(front_y, rear_y) + 8), (x + cabin_w - 3, max(front_y, rear_y) - 8), roof_col, -1)

            # Police Cruiser Emergency Lightbar
            if vtype == "police":
                lbar_y = y
                if (self.frame_count // 6) % 2 == 0:
                    cv2.rectangle(frame, (x - 14, lbar_y - 4), (x, lbar_y + 4), (0, 0, 255), -1)  # Blue
                    cv2.rectangle(frame, (x, lbar_y - 4), (x + 14, lbar_y + 4), (255, 0, 0), -1)  # Red
                else:
                    cv2.rectangle(frame, (x - 14, lbar_y - 4), (x, lbar_y + 4), (255, 0, 0), -1)  # Red
                    cv2.rectangle(frame, (x, lbar_y - 4), (x + 14, lbar_y + 4), (0, 0, 255), -1)  # Blue

        # 5. Side Mirrors
        sm_y = y + int(hh * 0.25) if heading_south else y - int(hh * 0.25)
        cv2.rectangle(frame, (x - hw - 4, sm_y - 3), (x - hw, sm_y + 3), color, -1)
        cv2.rectangle(frame, (x + hw, sm_y - 3), (x + hw + 4, sm_y + 3), color, -1)

        # 6. Headlights & Taillights
        if heading_south:
            hl_y = y + hh - 2
            tl_y = y - hh + 2
            # Projector Xenon Headlamps
            cv2.circle(frame, (x - hw + 8, hl_y), 4, (235, 248, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (x + hw - 8, hl_y), 4, (235, 248, 255), -1, cv2.LINE_AA)
            # Glowing Red LED Taillights
            cv2.circle(frame, (x - hw + 8, tl_y), 3, (0, 0, 240), -1, cv2.LINE_AA)
            cv2.circle(frame, (x + hw - 8, tl_y), 3, (0, 0, 240), -1, cv2.LINE_AA)
        else:
            hl_y = y - hh + 2
            tl_y = y + hh - 2
            # Projector Xenon Headlamps
            cv2.circle(frame, (x - hw + 8, hl_y), 4, (235, 248, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (x + hw - 8, hl_y), 4, (235, 248, 255), -1, cv2.LINE_AA)
            # Glowing Red LED Taillights
            cv2.circle(frame, (x - hw + 8, tl_y), 3, (0, 0, 240), -1, cv2.LINE_AA)
            cv2.circle(frame, (x + hw - 8, tl_y), 3, (0, 0, 240), -1, cv2.LINE_AA)

        # 7. License Plate Tag
        plate_y = y + hh - 1 if heading_south else y - hh + 1
        cv2.rectangle(frame, (x - 16, plate_y - 2), (x + 16, plate_y + 2), (245, 248, 252), -1)

    def _render_pedestrian(self, frame: np.ndarray, x: int, y: int) -> None:
        """Renders anti-aliased pedestrian."""
        # Ground shadow
        cv2.ellipse(frame, (x + 2, y + 14), (8, 4), 0, 0, 360, (20, 22, 25), -1, cv2.LINE_AA)
        # Head
        cv2.circle(frame, (x, y - 10), 6, (230, 195, 165), -1, cv2.LINE_AA)
        # Torso / Jacket
        cv2.rectangle(frame, (x - 6, y - 4), (x + 6, y + 8), (0, 160, 220), -1)
        # Legs
        cv2.line(frame, (x - 3, y + 8), (x - 5, y + 18), (32, 36, 42), 2, cv2.LINE_AA)
        cv2.line(frame, (x + 3, y + 8), (x + 5, y + 18), (32, 36, 42), 2, cv2.LINE_AA)

    def _render_cctv_osd(self, frame: np.ndarray) -> None:
        """Renders municipal CCTV timestamp, camera ID, and telemetry header."""
        now = datetime.datetime.now(datetime.timezone.utc)
        time_str = now.strftime("%Y-%m-%d  %H:%M:%S.%f")[:-3] + " UTC"
        cam_id = "CH-042 [CANAL_ST_8TH_AVE]  •  1080P@30FPS  •  H.265 MAIN"

        # Translucent top telemetry header bar
        cv2.rectangle(frame, (0, 0), (self.width, 34), (8, 12, 18), -1)
        cv2.line(frame, (0, 34), (self.width, 34), (28, 42, 65), 1)

        # Camera ID & Encoding Telemetry
        cv2.putText(frame, cam_id, (18, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 229, 255), 1, cv2.LINE_AA)

        # Pulsating Recording Indicator
        if (self.frame_count // 15) % 2 == 0:
            cv2.circle(frame, (self.width - 320, 17), 5, (0, 0, 245), -1, cv2.LINE_AA)
            cv2.putText(frame, "REC ●", (self.width - 308, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 245), 1, cv2.LINE_AA)
        else:
            cv2.putText(frame, "REC", (self.width - 308, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (130, 130, 130), 1, cv2.LINE_AA)

        # Real-Time UTC Timestamp
        cv2.putText(frame, time_str, (self.width - 235, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (230, 235, 240), 1, cv2.LINE_AA)


class VideoStream:
    """Unified video stream handler for Webcams, RTSP IP Cameras, Video Files, and High-Definition Simulation."""

    def __init__(self, source: Optional[str] = None, loop: bool = True):
        self.source = source
        self.loop = loop
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_synthetic = False
        self.synthetic_sim: Optional[SyntheticTrafficSimulator] = None
        self._init_source()

    def _init_source(self) -> None:
        if self.source == "synthetic" or self.source is None or self.source == "":
            self.is_synthetic = True
            self.synthetic_sim = SyntheticTrafficSimulator()
            return

        try:
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
