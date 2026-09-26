"""
ArgusTraffic AI - Rigorous Performance and Throughput Benchmark Suite
Measures latency (P50, P95, P99), sustained FPS, tracking throughput,
and spatial incident rule evaluation latency.
"""

import argparse
from pathlib import Path
import sys
import time
from typing import Dict, List

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch

from src.core.detector import TrafficDetector
from src.core.incident_engine import IncidentEngine
from src.core.tracker import SpatialTracker
from src.core.zone_manager import ZoneManager


def run_benchmark(num_frames: int = 150, resolution: tuple = (1280, 720), device: str = "auto") -> Dict[str, float]:
    print("=" * 65)
    print("   ARGUSTRAFFIC AI - SYSTEM PERFORMANCE BENCHMARK   ")
    print("=" * 65)

    detector = TrafficDetector(model_name="yolov8n.pt", device=device, half_precision=True)
    tracker = SpatialTracker()
    zone_mgr = ZoneManager()
    zone_mgr.create_default_traffic_zones(frame_width=resolution[0], frame_height=resolution[1])
    incident_eng = IncidentEngine()

    print(f"Device: {detector.device.upper()} | Model: {detector.model_name} | Target: {resolution[0]}x{resolution[1]}")
    print(f"Running {num_frames} inference cycles...")

    # Warm-up
    dummy_frame = np.random.randint(0, 255, (resolution[1], resolution[0], 3), dtype=np.uint8)
    for _ in range(10):
        _ = detector.detect(dummy_frame)

    det_latencies: List[float] = []
    track_latencies: List[float] = []
    incident_latencies: List[float] = []
    total_latencies: List[float] = []

    for i in range(num_frames):
        t0 = time.perf_counter()

        # 1. Detection
        detections, det_ms = detector.detect(dummy_frame)
        t1 = time.perf_counter()

        # 2. Tracking
        tracked_dets = tracker.update(detections)
        t2 = time.perf_counter()

        # 3. Incident Engine
        _ = incident_eng.analyze_frame(
            frame_idx=i,
            detections=tracked_dets,
            tracker=tracker,
            zone_manager=zone_mgr,
            fps=30.0,
        )
        t3 = time.perf_counter()

        det_latencies.append(det_ms)
        track_latencies.append((t2 - t1) * 1000.0)
        incident_latencies.append((t3 - t2) * 1000.0)
        total_latencies.append((t3 - t0) * 1000.0)

    # Compute percentiles
    avg_det_ms = np.mean(det_latencies)
    avg_track_ms = np.mean(track_latencies)
    avg_inc_ms = np.mean(incident_latencies)
    avg_total_ms = np.mean(total_latencies)
    p50_total = np.percentile(total_latencies, 50)
    p95_total = np.percentile(total_latencies, 95)
    p99_total = np.percentile(total_latencies, 99)
    sustained_fps = 1000.0 / avg_total_ms if avg_total_ms > 0 else 0

    print("-" * 65)
    print(f"| {'Pipeline Stage':<28} | {'Avg Latency (ms)':<16} | {'% of Frame':<12} |")
    print("-" * 65)
    print(f"| {'YOLOv8 Detection (imgsz=640)':<28} | {avg_det_ms:<16.2f} | {avg_det_ms/avg_total_ms*100:<12.1f} |")
    print(f"| {'Spatial Trajectory Tracking':<28} | {avg_track_ms:<16.2f} | {avg_track_ms/avg_total_ms*100:<12.1f} |")
    print(f"| {'Incident Rule Evaluation':<28} | {avg_inc_ms:<16.2f} | {avg_inc_ms/avg_total_ms*100:<12.1f} |")
    print("-" * 65)
    print(f"| {'Total End-to-End Latency':<28} | {avg_total_ms:<16.2f} | 100.0%       |")
    print("-" * 65)
    print(f"Latency Percentiles: P50 = {p50_total:.2f} ms | P95 = {p95_total:.2f} ms | P99 = {p99_total:.2f} ms")
    print(f"Sustained Pipeline Speed: {sustained_fps:.1f} FPS (Target: >= 30.0 FPS)")
    print("=" * 65)

    return {
        "device": detector.device,
        "avg_detection_ms": round(float(avg_det_ms), 2),
        "avg_tracking_ms": round(float(avg_track_ms), 2),
        "avg_incident_ms": round(float(avg_inc_ms), 2),
        "p50_ms": round(float(p50_total), 2),
        "p95_ms": round(float(p95_total), 2),
        "p99_ms": round(float(p99_total), 2),
        "fps": round(float(sustained_fps), 1),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ArgusTraffic AI Benchmark")
    parser.add_argument("--frames", type=int, default=100, help="Number of benchmark iterations")
    parser.add_argument("--device", type=str, default="auto", help="Compute device ('cpu', 'cuda', 'auto')")
    args = parser.parse_args()

    run_benchmark(num_frames=args.frames, device=args.device)
