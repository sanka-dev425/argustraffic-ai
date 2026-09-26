"""
ArgusTraffic AI - Perception Engine: Temporal Detection Fusion
Suppresses transient single-frame false positives, resolves detection flickering,
and bridges brief detector dropouts across a sliding temporal window.
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from src.core.interfaces import Detection


@dataclass
class TemporalCandidate:
    candidate_id: int
    detections: List[Detection]
    class_id: int
    class_name: str
    last_bbox: Tuple[float, float, float, float]
    consecutive_hits: int = 1
    missed_frames: int = 0


class TemporalDetectionFusionEngine:
    """Fuses multi-frame observations to confirm persistent objects and suppress noise."""

    def __init__(
        self,
        window_size: int = 5,
        min_hits_to_confirm: int = 2,
        max_missed_frames: int = 2,
        match_iou_threshold: float = 0.30,
    ):
        self.window_size = window_size
        self.min_hits_to_confirm = min_hits_to_confirm
        self.max_missed_frames = max_missed_frames
        self.match_iou_threshold = match_iou_threshold

        self._next_id: int = 1
        self._candidates: Dict[int, TemporalCandidate] = {}

    def update(self, current_detections: List[Detection]) -> List[Detection]:
        """
        Updates temporal candidates with current frame detections.
        Returns only temporally confirmed and verified detections.
        """
        matched_candidates = set()
        matched_detections = set()

        # 1. Associate current detections with existing temporal candidates
        for det_idx, det in enumerate(current_detections):
            best_candidate_id = None
            best_iou = self.match_iou_threshold

            for c_id, cand in self._candidates.items():
                if c_id in matched_candidates:
                    continue
                # Class match requirement
                if cand.class_id == det.class_id:
                    iou = self._compute_iou(cand.last_bbox, det.bbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_candidate_id = c_id

            if best_candidate_id is not None:
                cand = self._candidates[best_candidate_id]
                cand.detections.append(det)
                cand.last_bbox = det.bbox
                cand.consecutive_hits += 1
                cand.missed_frames = 0
                matched_candidates.add(best_candidate_id)
                matched_detections.add(det_idx)

        # 2. Add unmatched detections as new tentative candidates
        for det_idx, det in enumerate(current_detections):
            if det_idx not in matched_detections:
                new_c = TemporalCandidate(
                    candidate_id=self._next_id,
                    detections=[det],
                    class_id=det.class_id,
                    class_name=det.class_name,
                    last_bbox=det.bbox,
                    consecutive_hits=1,
                    missed_frames=0,
                )
                self._candidates[self._next_id] = new_c
                self._next_id += 1

        # 3. Handle unmatched existing candidates (missed in this frame)
        to_remove = []
        for c_id, cand in self._candidates.items():
            if c_id not in matched_candidates:
                cand.missed_frames += 1
                if cand.missed_frames > self.max_missed_frames:
                    to_remove.append(c_id)

        for c_id in to_remove:
            self._candidates.pop(c_id, None)

        # 4. Filter confirmed detections
        confirmed_detections: List[Detection] = []
        for cand in self._candidates.values():
            if cand.consecutive_hits >= self.min_hits_to_confirm:
                latest_det = cand.detections[-1]
                # Boost confidence slightly based on temporal persistence
                temporal_boost = min(0.08, (cand.consecutive_hits - 1) * 0.02)
                calibrated_conf = min(0.99, latest_det.confidence + temporal_boost)
                confirmed_detections.append(
                    Detection(
                        bbox=cand.last_bbox,
                        confidence=round(calibrated_conf, 2),
                        class_id=cand.class_id,
                        class_name=cand.class_name,
                        track_id=latest_det.track_id,
                    )
                )

        return confirmed_detections

    @staticmethod
    def _compute_iou(boxA: Tuple[float, float, float, float], boxB: Tuple[float, float, float, float]) -> float:
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        iw = max(0.0, xB - xA)
        ih = max(0.0, yB - yA)
        intersection = iw * ih

        areaA = max(0.0, boxA[2] - boxA[0]) * max(0.0, boxA[3] - boxA[1])
        areaB = max(0.0, boxB[2] - boxB[0]) * max(0.0, boxB[3] - boxB[1])
        union = areaA + areaB - intersection
        return intersection / union if union > 0 else 0.0
