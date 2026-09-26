"""
ArgusTraffic AI - Real-Time Multi-Object Spatial Velocity Tracker
Maintains persistent IDs, computes trajectory histories, and estimates
instantaneous and smoothed velocity vectors.
"""

from collections import deque
from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.core.detector import Detection


@dataclass
class Track:
    track_id: int
    class_id: int
    class_name: str
    bbox: Tuple[float, float, float, float]
    confidence: float
    history: deque = field(default_factory=lambda: deque(maxlen=60))  # List of (center_x, center_y, timestamp)
    velocity: Tuple[float, float] = (0.0, 0.0)  # (vx, vy) px/frame
    speed: float = 0.0  # magnitude in px/frame
    frames_since_update: int = 0
    total_frames: int = 1
    state: str = "active"  # active, lost, removed

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


def compute_iou(boxA: Tuple[float, float, float, float], boxB: Tuple[float, float, float, float]) -> float:
    """Calculates Intersection over Union (IoU) between two bounding boxes."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    inter_width = max(0.0, xB - xA)
    inter_height = max(0.0, yB - yA)
    inter_area = inter_width * inter_height

    boxA_area = max(0.0, boxA[2] - boxA[0]) * max(0.0, boxA[3] - boxA[1])
    boxB_area = max(0.0, boxB[2] - boxB[0]) * max(0.0, boxB[3] - boxB[1])

    union_area = boxA_area + boxB_area - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


class SpatialTracker:
    """
    High-speed online multi-object tracker that tracks targets across frames,
    computes motion vectors, smoothing, and keeps track lifetimes.
    """

    def __init__(
        self,
        max_age: int = 30,
        min_hits: int = 2,
        iou_threshold: float = 0.30,
        history_length: int = 60,
    ):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.history_length = history_length

        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}

    def update(self, detections: List[Detection]) -> List[Detection]:
        """
        Updates tracks with new detections from the current frame.
        Attaches track_id and velocity to each matched detection.
        """
        active_track_ids = list(self.tracks.keys())
        unmatched_detections = list(range(len(detections)))
        unmatched_tracks = set(active_track_ids)

        if active_track_ids and detections:
            # Build cost matrix based on 1.0 - IoU
            cost_matrix = np.zeros((len(active_track_ids), len(detections)), dtype=np.float32)
            for t_idx, t_id in enumerate(active_track_ids):
                track = self.tracks[t_id]
                for d_idx, det in enumerate(detections):
                    iou = compute_iou(track.bbox, det.bbox)
                    # Class matching bonus
                    if track.class_id == det.class_id:
                        iou += 0.1
                    cost_matrix[t_idx, d_idx] = iou

            # Greedy Hungarian-style matching
            matched_track_indices = set()
            matched_det_indices = set()

            # Sort candidate pairs by highest IoU descending
            candidate_pairs = []
            for t_idx in range(len(active_track_ids)):
                for d_idx in range(len(detections)):
                    score = cost_matrix[t_idx, d_idx]
                    if score >= self.iou_threshold:
                        candidate_pairs.append((score, t_idx, d_idx))

            candidate_pairs.sort(key=lambda x: x[0], reverse=True)

            for score, t_idx, d_idx in candidate_pairs:
                if t_idx in matched_track_indices or d_idx in matched_det_indices:
                    continue
                matched_track_indices.add(t_idx)
                matched_det_indices.add(d_idx)

                t_id = active_track_ids[t_idx]
                det = detections[d_idx]
                self._update_track(t_id, det)
                unmatched_tracks.discard(t_id)

            unmatched_detections = [i for i in range(len(detections)) if i not in matched_det_indices]

        # Age unmatched tracks
        for t_id in list(unmatched_tracks):
            track = self.tracks[t_id]
            track.frames_since_update += 1
            if track.frames_since_update > self.max_age:
                del self.tracks[t_id]

        # Initialize new tracks for unmatched detections
        for d_idx in unmatched_detections:
            det = detections[d_idx]
            new_id = self.next_track_id
            self.next_track_id += 1

            new_track = Track(
                track_id=new_id,
                class_id=det.class_id,
                class_name=det.class_name,
                bbox=det.bbox,
                confidence=det.confidence,
                history=deque(maxlen=self.history_length),
            )
            new_track.history.append(new_track.center)
            self.tracks[new_id] = new_track

            det.track_id = new_id
            det.velocity = (0.0, 0.0)

        # Update detections with current track stats
        for det in detections:
            if det.track_id and det.track_id in self.tracks:
                track = self.tracks[det.track_id]
                det.velocity = track.velocity

        return detections

    def _update_track(self, track_id: int, det: Detection) -> None:
        """Updates track position, history, and smoothed velocity."""
        track = self.tracks[track_id]
        old_center = track.center
        new_center = det.center

        # Velocity calculation
        vx = new_center[0] - old_center[0]
        vy = new_center[1] - old_center[1]

        # Exponential moving average smoothing for velocity
        alpha = 0.4
        smoothed_vx = alpha * vx + (1 - alpha) * track.velocity[0]
        smoothed_vy = alpha * vy + (1 - alpha) * track.velocity[1]

        track.bbox = det.bbox
        track.confidence = det.confidence
        track.velocity = (smoothed_vx, smoothed_vy)
        track.speed = math.hypot(smoothed_vx, smoothed_vy)
        track.frames_since_update = 0
        track.total_frames += 1
        track.history.append(new_center)

        det.track_id = track_id
        det.velocity = track.velocity

    def get_track(self, track_id: int) -> Optional[Track]:
        return self.tracks.get(track_id)
