"""
Unit Tests for SpatialTracker and multi-object matching.
"""

import pytest
from src.core.detector import Detection
from src.core.tracker import SpatialTracker, compute_iou


def test_iou_computation():
    box1 = (0.0, 0.0, 10.0, 10.0)
    box2 = (0.0, 0.0, 10.0, 10.0)
    assert pytest.approx(compute_iou(box1, box2), 0.01) == 1.0

    box3 = (10.0, 10.0, 20.0, 20.0)
    assert compute_iou(box1, box3) == 0.0

    box4 = (5.0, 0.0, 15.0, 10.0)
    # intersection: 5x10=50, union: 100+100-50=150, iou = 50/150 = 0.333
    assert pytest.approx(compute_iou(box1, box4), 0.01) == 0.333


def test_tracker_maintains_persistent_id():
    tracker = SpatialTracker(iou_threshold=0.20)

    # Frame 1: Detection at (100, 100, 160, 160)
    det1 = [Detection(bbox=(100.0, 100.0, 160.0, 160.0), confidence=0.9, class_id=2, class_name="car")]
    tracked1 = tracker.update(det1)
    assert len(tracked1) == 1
    assert tracked1[0].track_id is not None
    orig_id = tracked1[0].track_id

    # Frame 2: Vehicle moved slightly to (105, 105, 165, 165)
    det2 = [Detection(bbox=(105.0, 105.0, 165.0, 165.0), confidence=0.9, class_id=2, class_name="car")]
    tracked2 = tracker.update(det2)
    assert len(tracked2) == 1
    # Must retain same track_id
    assert tracked2[0].track_id == orig_id
    # Velocity must be positive
    assert tracked2[0].velocity[0] > 0
    assert tracked2[0].velocity[1] > 0
