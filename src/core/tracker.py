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
    appearance_embedding: Optional[np.ndarray] = None

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


def extract_appearance_embedding(frame: Optional[np.ndarray], bbox: Tuple[float, float, float, float]) -> Optional[np.ndarray]:
    """Extracts normalized color histogram appearance descriptor for visual Re-ID."""
    if frame is None or frame.size == 0:
        return None
    try:
        import cv2
        h, w = frame.shape[:2]
        x1 = max(0, min(int(bbox[0]), w - 1))
        y1 = max(0, min(int(bbox[1]), h - 1))
        x2 = max(x1 + 1, min(int(bbox[2]), w))
        y2 = max(y1 + 1, min(int(bbox[3]), h))

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # 8 bins H, 8 bins S
        hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist.flatten().astype(np.float32)
    except Exception:
        return None


def batch_iou(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """Vectorized SIMD pairwise IoU computation between N boxes_a and M boxes_b."""
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float32)
    tl = np.maximum(boxes_a[:, None, :2], boxes_b[None, :, :2])
    br = np.minimum(boxes_a[:, None, 2:], boxes_b[None, :, 2:])
    wh = np.clip(br - tl, a_min=0, a_max=None)
    inter = wh[:, :, 0] * wh[:, :, 1]
    area_a = (boxes_a[:, 2] - boxes_a[:, 0]) * (boxes_a[:, 3] - boxes_a[:, 1])
    area_b = (boxes_b[:, 2] - boxes_b[:, 0]) * (boxes_b[:, 3] - boxes_b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / union, 0.0).astype(np.float32)


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
    Integrates Visual Appearance Re-ID embeddings to resolve occlusions and vehicle crossovers.
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

    def update(self, detections: List[Detection], frame: Optional[np.ndarray] = None) -> List[Detection]:
        """
        Updates tracks with new detections from the current frame.
        Attaches track_id and velocity to each matched detection.
        Optionally uses visual appearance embeddings from frame for Re-ID.
        """
        active_track_ids = list(self.tracks.keys())
        unmatched_detections = list(range(len(detections)))
        unmatched_tracks = set(active_track_ids)

        if active_track_ids and detections:
            # Vectorized SIMD cost matrix computation
            track_boxes = np.array([self.tracks[tid].bbox for tid in active_track_ids], dtype=np.float32)
            det_boxes = np.array([d.bbox for d in detections], dtype=np.float32)
            cost_matrix = batch_iou(track_boxes, det_boxes)

            # Vectorized class matching bonus
            track_classes = np.array([self.tracks[tid].class_id for tid in active_track_ids])[:, None]
            det_classes = np.array([d.class_id for d in detections])[None, :]
            cost_matrix += np.where(track_classes == det_classes, 0.1, 0.0)

            # Visual Appearance Re-ID Bonus if frame is available
            if frame is not None:
                det_embeddings = [extract_appearance_embedding(frame, d.bbox) for d in detections]
                for t_idx, tid in enumerate(active_track_ids):
                    t_emb = self.tracks[tid].appearance_embedding
                    if t_emb is not None:
                        for d_idx, d_emb in enumerate(det_embeddings):
                            if d_emb is not None:
                                # Cosine similarity
                                sim = float(np.dot(t_emb, d_emb) / (np.linalg.norm(t_emb) * np.linalg.norm(d_emb) + 1e-6))
                                if sim > 0.65:
                                    cost_matrix[t_idx, d_idx] += 0.20 * sim

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
                self._update_track(t_id, det, frame)
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

            new_emb = extract_appearance_embedding(frame, det.bbox) if frame is not None else None
            new_track = Track(
                track_id=new_id,
                class_id=det.class_id,
                class_name=det.class_name,
                bbox=det.bbox,
                confidence=det.confidence,
                history=deque(maxlen=self.history_length),
                appearance_embedding=new_emb,
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

    def _update_track(self, track_id: int, det: Detection, frame: Optional[np.ndarray] = None) -> None:
        """Updates track position, history, smoothed velocity, and appearance embedding."""
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

        # Update appearance feature embedding with EMA
        if frame is not None:
            new_emb = extract_appearance_embedding(frame, det.bbox)
            if new_emb is not None:
                if track.appearance_embedding is None:
                    track.appearance_embedding = new_emb
                else:
                    track.appearance_embedding = 0.8 * track.appearance_embedding + 0.2 * new_emb
                    norm = np.linalg.norm(track.appearance_embedding)
                    if norm > 0:
                        track.appearance_embedding /= norm

        det.track_id = track_id
        det.velocity = track.velocity

    def get_track(self, track_id: int) -> Optional[Track]:
        return self.tracks.get(track_id)
