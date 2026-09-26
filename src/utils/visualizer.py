"""
ArgusTraffic AI - High-Visibility Real-Time HUD and Visualizer
Renders glassmorphic telemetry, trajectory trails, danger zones,
and incident warnings directly onto video frames.
"""

import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.core.detector import Detection
from src.core.incident_engine import IncidentAlert
from src.core.tracker import SpatialTracker
from src.core.zone_manager import TrafficZone, ZoneManager

# Color Palette (BGR format for OpenCV)
PALETTE = {
    "car": (118, 230, 0),         # Neon Green
    "pedestrian": (75, 75, 255),   # Coral Red
    "truck": (176, 39, 156),       # Purple
    "bus": (255, 176, 0),          # Cyan / Blue
    "motorcycle": (0, 215, 255),   # Gold
    "bicycle": (0, 165, 255),      # Orange
    "default": (200, 200, 200),
    "critical": (0, 0, 255),       # Bright Red
    "warning": (0, 190, 255),      # Amber
    "info": (255, 200, 0),         # Sky Blue
    "lane": (0, 140, 255),         # Translucent Orange/Gold
    "crosswalk": (255, 255, 0),    # Translucent Cyan
}


class FrameVisualizer:
    """Renders professional overlays, trajectory trails, and HUD analytics."""

    def __init__(self, show_trajectories: bool = True, show_zones: bool = True, show_hud: bool = True):
        self.show_trajectories = show_trajectories
        self.show_zones = show_zones
        self.show_hud = show_hud

    def render(
        self,
        frame: np.ndarray,
        detections: List[Detection],
        tracker: Optional[SpatialTracker] = None,
        zone_manager: Optional[ZoneManager] = None,
        active_alerts: Optional[List[IncidentAlert]] = None,
        fps: float = 0.0,
        latency_ms: float = 0.0,
    ) -> np.ndarray:
        """Draws all annotations and HUD onto a copy of the input frame."""
        canvas = frame.copy()
        h, w = canvas.shape[:2]

        # 1. Render Polygons / Zones
        if self.show_zones and zone_manager:
            overlay = canvas.copy()
            for zone in zone_manager.zones.values():
                pts = np.array(zone.polygon, dtype=np.int32)
                color = PALETTE["crosswalk"] if zone.zone_type == "crosswalk" else (40, 40, 60)
                cv2.fillPoly(overlay, [pts], color)
                cv2.polylines(canvas, [pts], True, (0, 255, 255) if zone.zone_type == "crosswalk" else (100, 150, 255), 2)

                # Render Lane Direction Arrow if available
                if zone.expected_flow and len(zone.polygon) >= 2:
                    cx = int(np.mean([p[0] for p in zone.polygon]))
                    cy = int(np.mean([p[1] for p in zone.polygon]))
                    arrow_len = 45
                    dx = int(zone.expected_flow.dx * arrow_len)
                    dy = int(zone.expected_flow.dy * arrow_len)
                    cv2.arrowedLine(canvas, (cx - dx // 2, cy - dy // 2), (cx + dx // 2, cy + dy // 2), (0, 255, 255), 2, tipLength=0.3)
                    cv2.putText(canvas, zone.name, (cx - 50, cy - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

            # Alpha blend zone overlay
            cv2.addWeighted(overlay, 0.20, canvas, 0.80, 0, canvas)

        # 2. Render Trajectory Trails
        if self.show_trajectories and tracker:
            for track in tracker.tracks.values():
                if len(track.history) > 1:
                    pts = [(int(p[0]), int(p[1])) for p in track.history]
                    color = PALETTE.get(track.class_name.lower(), PALETTE["default"])
                    for i in range(1, len(pts)):
                        alpha = i / len(pts)
                        thickness = max(1, int(3 * alpha))
                        cv2.line(canvas, pts[i - 1], pts[i], color, thickness)

        # 3. Render Detections and Bounding Boxes
        for det in detections:
            x1, y1, x2, y2 = [int(v) for v in det.bbox]
            color = PALETTE.get(det.class_name.lower(), PALETTE["default"])

            # Check if this object is in any active alert
            is_critical = False
            if active_alerts and det.track_id:
                for a in active_alerts:
                    if det.track_id in a.involved_track_ids:
                        color = PALETTE["critical"]
                        is_critical = True
                        break

            # Draw rounded or standard bounding box
            thickness = 3 if is_critical else 2
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)

            # Velocity vector arrow
            if det.velocity:
                vx, vy = det.velocity
                cx, cy = int(det.center[0]), int(det.center[1])
                speed = math.hypot(vx, vy)
                if speed > 1.0:
                    scale = 4.0
                    end_pt = (int(cx + vx * scale), int(cy + vy * scale))
                    cv2.arrowedLine(canvas, (cx, cy), end_pt, (255, 255, 255), 2, tipLength=0.3)

            # Badge Label
            track_str = f"#{det.track_id} " if det.track_id else ""
            speed_str = f" | {math.hypot(det.velocity[0], det.velocity[1]):.1f}px/f" if det.velocity else ""
            label = f"{track_str}{det.class_name} {det.confidence:.2f}{speed_str}"

            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(canvas, (x1, max(0, y1 - lh - 8)), (x1 + lw + 8, y1), color, -1)
            cv2.putText(canvas, label, (x1 + 4, max(lh + 2, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

        # 4. Render Active Incident Flash Banners
        if active_alerts:
            banner_y = 60
            for alert in active_alerts[:3]:  # Show top 3 alerts
                banner_color = PALETTE["critical"] if alert.severity == "CRITICAL" else PALETTE["warning"]
                banner_text = f"[{alert.severity}] {alert.description}"
                (tw, th), _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)

                cv2.rectangle(canvas, (10, banner_y - th - 10), (20 + tw, banner_y + 6), (15, 15, 20), -1)
                cv2.rectangle(canvas, (10, banner_y - th - 10), (20 + tw, banner_y + 6), banner_color, 2)
                cv2.putText(canvas, banner_text, (15, banner_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, banner_color, 2, cv2.LINE_AA)
                banner_y += th + 24

        # 5. Render HUD Glassmorphic Watermark
        if self.show_hud:
            hud_w, hud_h = 290, 85
            hud_bg = canvas[10:10 + hud_h, 10:10 + hud_w].copy()
            black_overlay = np.zeros_like(hud_bg)
            cv2.addWeighted(hud_bg, 0.2, black_overlay, 0.8, 0, hud_bg)
            canvas[10:10 + hud_h, 10:10 + hud_w] = hud_bg
            cv2.rectangle(canvas, (10, 10), (10 + hud_w, 10 + hud_h), (0, 230, 118), 1)

            cv2.putText(canvas, "ARGUSTRAFFIC AI - LIVE HUD", (18, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 230, 118), 1, cv2.LINE_AA)
            cv2.putText(canvas, f"FPS: {fps:.1f} | Latency: {latency_ms:.1f} ms", (18, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            active_tracks_count = len(tracker.tracks) if tracker else len(detections)
            cv2.putText(canvas, f"Tracked Targets: {active_tracks_count} | Incidents: {len(active_alerts or [])}", (18, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

        return canvas
