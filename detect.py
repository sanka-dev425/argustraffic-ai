"""
ArgusTraffic AI - Standalone CLI Inference Runner
Process live video feeds, webcam, or video files with YOLOv8 and Spatial Incident Intelligence.
Example:
    python detect.py --source demo_traffic.mp4 --save
    python detect.py --source 0 --view
"""

import argparse
import logging
from pathlib import Path
import time
import cv2
import numpy as np

from src.core.detector import TrafficDetector
from src.core.incident_engine import IncidentEngine
from src.core.tracker import SpatialTracker
from src.core.zone_manager import ZoneManager
from src.utils.video_stream import VideoStream
from src.utils.visualizer import FrameVisualizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("argustraffic.detect")


def run_detection(
    source: str = "synthetic",
    model_name: str = "yolov8n.pt",
    conf_thresh: float = 0.35,
    iou_thresh: float = 0.45,
    device: str = "auto",
    view: bool = False,
    save: bool = False,
    output_path: str = "output_detection.mp4",
):
    logger.info(f"Initializing detector '{model_name}' on device '{device}'...")
    detector = TrafficDetector(
        model_name=model_name,
        confidence_threshold=conf_thresh,
        iou_threshold=iou_thresh,
        device=device,
    )
    tracker = SpatialTracker()
    zone_mgr = ZoneManager()
    zone_mgr.create_default_traffic_zones(1280, 720)
    incident_eng = IncidentEngine()
    visualizer = FrameVisualizer()
    is_live = source.isdigit() or source == "synthetic"
    stream = VideoStream(source=source, loop=is_live)

    writer = None
    frame_idx = 0
    start_time = time.time()

    logger.info(f"Starting inference pipeline on source: {source}")

    try:
        while True:
            ret, frame = stream.read_frame()
            if not ret or frame is None:
                break

            frame_idx += 1
            t0 = time.perf_counter()

            # 1. Detection
            detections, inf_ms = detector.detect(frame)

            # 2. Tracking
            tracked = tracker.update(detections)

            # 3. Incident rules
            alerts = incident_eng.analyze_frame(
                frame_idx=frame_idx,
                detections=tracked,
                tracker=tracker,
                zone_manager=zone_mgr,
                fps=30.0,
            )

            fps = 1.0 / max(0.001, (time.perf_counter() - t0))

            # 4. Render
            annotated = visualizer.render(
                frame=frame,
                detections=tracked,
                tracker=tracker,
                zone_manager=zone_mgr,
                active_alerts=alerts or incident_eng.active_alerts[-3:],
                fps=fps,
                latency_ms=inf_ms,
            )

            # Log any triggered alerts
            for a in alerts:
                logger.warning(f"INCIDENT: [{a.severity}] {a.description}")

            # Save to output video if requested
            if save:
                if writer is None:
                    h, w = annotated.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(output_path, fourcc, 30, (w, h))
                writer.write(annotated)

            # Interactive preview window
            if view:
                cv2.imshow("ArgusTraffic AI - Real-Time Detection Feed", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            # Limit console printing
            if frame_idx % 60 == 0:
                logger.info(f"Frame {frame_idx:05d} | FPS: {fps:.1f} | Active Targets: {len(tracker.tracks)} | Alerts: {len(incident_eng.active_alerts)}")

    except KeyboardInterrupt:
        logger.info("Pipeline stopped by user.")
    finally:
        stream.release()
        if writer:
            writer.release()
            logger.info(f"Annotated output saved to: {output_path}")
        if view:
            cv2.destroyAllWindows()

    total_time = time.time() - start_time
    avg_fps = frame_idx / total_time if total_time > 0 else 0
    logger.info(f"Processed {frame_idx} frames in {total_time:.2f}s ({avg_fps:.1f} FPS avg).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ArgusTraffic AI CLI")
    parser.add_argument("--source", type=str, default="synthetic", help="Video file, RTSP URL, webcam index (0), or 'synthetic'")
    parser.add_argument("--weights", type=str, default="yolov8n.pt", help="YOLO model checkpoint name or path")
    parser.add_argument("--conf", type=float, default=0.35, help="Confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45, help="IoU NMS threshold")
    parser.add_argument("--device", type=str, default="auto", help="Inference device: 'cpu', 'cuda', 'auto'")
    parser.add_argument("--view", action="store_true", help="Display interactive OpenCV preview window")
    parser.add_argument("--save", action="store_true", help="Save annotated output video")
    parser.add_argument("--output", type=str, default="output_detection.mp4", help="Output video file path")
    args = parser.parse_args()

    run_detection(
        source=args.source,
        model_name=args.weights,
        conf_thresh=args.conf,
        iou_thresh=args.iou,
        device=args.device,
        view=args.view,
        save=args.save,
        output_path=args.output,
    )
