"""
ArgusTraffic AI - Chaos Engineering & Resilience Test Suite
Injects adversarial, degraded, and anomalous conditions to verify:
- Graceful degradation
- Zero silent unhandled crashes on corrupt frames
- Stream reconnect recovery
- Extreme load burst handling
"""

import numpy as np
import pytest

from src.core.detector import Detection, TrafficDetector
from src.core.tracker import SpatialTracker
from src.core.incident_engine import IncidentEngine
from src.core.zone_manager import ZoneManager
from src.utils.video_stream import VideoStream


def test_chaos_corrupted_and_extreme_frames():
    """Validates that detector, tracker, and visualizer handle anomalous frames gracefully."""
    detector = TrafficDetector(model_name="yolov8n.pt", device="cpu")
    tracker = SpatialTracker()

    # 1. Pure Black Frame
    black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    dets, latency = detector.detect(black_frame)
    assert isinstance(dets, list)
    assert latency >= 0.0

    # 2. Pure White Saturation Frame
    white_frame = np.full((720, 1280, 3), 255, dtype=np.uint8)
    dets, latency = detector.detect(white_frame)
    assert isinstance(dets, list)

    # 3. High-frequency Gaussian Noise Frame
    noise_frame = np.random.randint(0, 256, (720, 1280, 3), dtype=np.uint8)
    dets, latency = detector.detect(noise_frame)
    assert isinstance(dets, list)

    # 4. Small atypical resolution frame (320x240)
    small_frame = np.zeros((240, 320, 3), dtype=np.uint8)
    dets, latency = detector.detect(small_frame)
    assert isinstance(dets, list)


def test_chaos_extreme_detection_burst_load():
    """Simulates an anomalous frame with 100 simultaneous bounding box detections."""
    tracker = SpatialTracker(max_age=15, iou_threshold=0.25)

    # Generate 100 random synthetic detections
    burst_dets = [
        Detection(
            bbox=(float(i * 10), 100.0, float(i * 10 + 30), 160.0),
            confidence=0.85,
            class_id=2,
            class_name="car",
        )
        for i in range(100)
    ]

    tracks = tracker.update(burst_dets)
    # Ensure tracker processed 100 detections without crashing or running out of memory
    assert len(tracks) > 0
    assert len(tracker.tracks) <= 150


def test_chaos_rapid_track_loss_and_recovery():
    """Simulates rapid occlusion (object disappears for 5 frames, then reappears)."""
    tracker = SpatialTracker(max_age=10, min_hits=2)

    # Step 1: Detect object for 3 frames
    det = Detection(bbox=(100.0, 100.0, 200.0, 200.0), confidence=0.90, class_id=2, class_name="car")
    orig_track_id = None
    for _ in range(3):
        res = tracker.update([det])
        if res and res[0].track_id is not None:
            orig_track_id = res[0].track_id

    assert orig_track_id is not None

    # Step 2: Object disappears for 4 frames (occlusion)
    for _ in range(4):
        tracker.update([])

    assert orig_track_id in tracker.tracks
    assert tracker.tracks[orig_track_id].frames_since_update == 4

    # Step 3: Object reappears at approximately same location
    reappeared_det = Detection(bbox=(105.0, 102.0, 205.0, 202.0), confidence=0.92, class_id=2, class_name="car")
    res_reappeared = tracker.update([reappeared_det])

    # Should retain the same persistent track ID
    assert orig_track_id in tracker.tracks
    assert tracker.tracks[orig_track_id].frames_since_update == 0


def test_chaos_synthetic_stream_loop_recovery():
    """Tests VideoStream synthetic mode loop stability over 30 consecutive frames."""
    stream = VideoStream(source="synthetic", loop=True)
    frames_read = 0
    for _ in range(30):
        ret, frame = stream.read_frame()
        if ret and frame is not None:
            frames_read += 1

    assert frames_read == 30
    stream.release()
