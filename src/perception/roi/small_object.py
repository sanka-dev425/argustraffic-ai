"""
ArgusTraffic AI - Perception Engine: Small Object Tiling & Slicing Engine
Enables detection of distant vehicles and pedestrians via high-resolution overlapping tile slices
combined with global coordinate reprojection and Non-Maximum Suppression (NMS).
"""

from typing import List, Tuple
import numpy as np

from src.core.interfaces import Detection


class SmallObjectTilingEngine:
    """Generates overlapping spatial image tiles for micro-object inference."""

    def __init__(self, tile_size: int = 640, overlap_ratio: float = 0.20, iou_nms_threshold: float = 0.45):
        self.tile_size = tile_size
        self.overlap_ratio = overlap_ratio
        self.iou_nms_threshold = iou_nms_threshold

    def generate_tiles(self, frame: np.ndarray) -> List[Tuple[np.ndarray, int, int]]:
        """
        Slices frame into overlapping grid tiles.
        Returns:
            List of (tile_img, offset_x, offset_y)
        """
        h, w = frame.shape[:2]
        step = int(self.tile_size * (1.0 - self.overlap_ratio))
        tiles = []

        y = 0
        while y < h:
            x = 0
            tile_h = min(self.tile_size, h - y)
            while x < w:
                tile_w = min(self.tile_size, w - x)
                crop = frame[y : y + tile_h, x : x + tile_w]

                # Pad tile if at edge and smaller than tile_size
                if crop.shape[0] < self.tile_size or crop.shape[1] < self.tile_size:
                    padded = np.zeros((self.tile_size, self.tile_size, 3), dtype=crop.dtype)
                    padded[:crop.shape[0], :crop.shape[1]] = crop
                    tiles.append((padded, x, y))
                else:
                    tiles.append((crop, x, y))

                if x + tile_w >= w:
                    break
                x += step
            if y + tile_h >= h:
                break
            y += step

        return tiles

    def merge_tile_detections(
        self, tile_results: List[Tuple[List[Detection], int, int]]
    ) -> List[Detection]:
        """
        Projects tile-relative bounding boxes back to global frame coordinates
        and applies Non-Maximum Suppression (NMS).
        """
        global_detections: List[Detection] = []

        for detections, off_x, off_y in tile_results:
            for det in detections:
                x1, y1, x2, y2 = det.bbox
                global_detections.append(
                    Detection(
                        bbox=(x1 + off_x, y1 + off_y, x2 + off_x, y2 + off_y),
                        confidence=det.confidence,
                        class_id=det.class_id,
                        class_name=det.class_name,
                    )
                )

        if not global_detections:
            return []

        return self._apply_nms(global_detections)

    def _apply_nms(self, detections: List[Detection]) -> List[Detection]:
        """Performs class-aware Non-Maximum Suppression."""
        # Sort descending by confidence
        detections.sort(key=lambda d: d.confidence, reverse=True)
        keep: List[Detection] = []

        while detections:
            best = detections.pop(0)
            keep.append(best)

            remaining = []
            for d in detections:
                # Same class IoU check
                if d.class_id == best.class_id:
                    iou = self._compute_iou(best.bbox, d.bbox)
                    if iou < self.iou_nms_threshold:
                        remaining.append(d)
                else:
                    remaining.append(d)
            detections = remaining

        return keep

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
