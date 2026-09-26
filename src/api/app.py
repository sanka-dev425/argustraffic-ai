"""
ArgusTraffic AI - FastAPI Application & Real-Time Streaming Server
Combines REST services, WebSocket live video feeds, MJPEG stream, and UI Command Center.
"""

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict

import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import yaml

from src.api.routes import router as api_router
from src.api.security import SecurityHeadersMiddleware
from src.core.detector import TrafficDetector
from src.core.dispatch import AlertDispatcher
from src.core.incident_db import IncidentDatabase
from src.core.incident_engine import IncidentEngine
from src.core.tracker import SpatialTracker
from src.core.zone_manager import ZoneManager
from src.core.auth_rbac import SecurityAuthManager
from src.utils.video_stream import VideoStream
from src.utils.visualizer import FrameVisualizer

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("argustraffic.server")

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Shared Application State
app_state: Dict[str, Any] = {
    "config": {},
    "detector": None,
    "tracker": None,
    "zone_manager": None,
    "incident_engine": None,
    "visualizer": None,
    "video_stream": None,
    "db": None,
    "dispatcher": None,
    "auth_mgr": None,
    "current_fps": 30.0,
    "current_latency_ms": 12.0,
}


def load_config() -> Dict[str, Any]:
    config_path = BASE_DIR / "configs" / "default_config.yaml"
    if config_path.exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def init_app_state():
    """Initializes detector, tracker, zones, and incident engine."""
    cfg = load_config()
    app_state["config"] = cfg

    logger.info("Initializing ArgusTraffic AI subsystems...")

    # 1. Detector
    model_cfg = cfg.get("model", {})
    app_state["detector"] = TrafficDetector(
        model_name=model_cfg.get("name", "yolov8n.pt"),
        confidence_threshold=model_cfg.get("confidence_threshold", 0.35),
        iou_threshold=model_cfg.get("iou_threshold", 0.45),
        target_classes=model_cfg.get("target_classes", [0, 1, 2, 3, 5, 7]),
        device=cfg.get("system", {}).get("device", "auto"),
        half_precision=cfg.get("system", {}).get("half_precision", True),
    )

    # 2. Tracker
    tracker_cfg = cfg.get("tracker", {})
    app_state["tracker"] = SpatialTracker(
        max_age=tracker_cfg.get("track_buffer", 30),
        min_hits=2,
        iou_threshold=0.30,
        history_length=tracker_cfg.get("history_length", 60),
    )

    # 3. Zone Manager with default highway zones
    app_state["zone_manager"] = ZoneManager()
    app_state["zone_manager"].create_default_traffic_zones(frame_width=1280, frame_height=720)

    # 4. Incident Engine
    app_state["incident_engine"] = IncidentEngine(config=cfg)

    # 5. Visualizer
    app_state["visualizer"] = FrameVisualizer(show_trajectories=True, show_zones=True, show_hud=True)

    # 6. Video Stream (defaults to realistic synthetic simulator)
    app_state["video_stream"] = VideoStream(source="synthetic")

    # 7. Persistent Incident Database & Dispatcher
    app_state["db"] = IncidentDatabase()
    app_state["dispatcher"] = AlertDispatcher()
    app_state["dispatcher"].start()

    # 8. Security Vault & Role-Based Access Control
    app_state["auth_mgr"] = SecurityAuthManager()

    logger.info("All ArgusTraffic AI subsystems successfully initialized.")


# Initialize immediately for module imports
init_app_state()

app = FastAPI(
    title="ArgusTraffic AI - Autonomous Traffic Hazard Vision API",
    description="Real-Time Smart City & Traffic Incident Intelligence Engine with YOLOv8, Kalman Spatial Tracking, and Evidence Ledger.",
    version="2.0.0",
)

# Enable CORS for external dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Add Defense-Grade Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# Register REST endpoints
app.include_router(api_router)

# Mount Static Files and Web UI
static_dir = BASE_DIR / "src" / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse, tags=["UI"])
async def get_index():
    index_file = BASE_DIR / "src" / "web" / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>ArgusTraffic AI Command Center</h1><p>UI loading...</p>")


def process_single_frame(frame_idx: int):
    """Synchronous CPU/GPU vision pipeline running inside worker thread."""
    detector = app_state["detector"]
    tracker = app_state["tracker"]
    zone_mgr = app_state["zone_manager"]
    incident_eng = app_state["incident_engine"]
    visualizer = app_state["visualizer"]
    stream = app_state["video_stream"]

    if not stream:
        return None, None, None, 0.0

    ret, frame = stream.read_frame()
    if not ret or frame is None:
        return None, None, None, 0.0

    loop_start = time.perf_counter()

    # 1. Detect
    detections, inf_ms = detector.detect(frame)

    # 2. Track
    tracked_dets = tracker.update(detections)

    # 3. Incident Evaluation
    new_alerts = incident_eng.analyze_frame(
        frame_idx=frame_idx,
        detections=tracked_dets,
        tracker=tracker,
        zone_manager=zone_mgr,
        fps=app_state["current_fps"],
    )

    # Persist and dispatch new alerts
    if new_alerts and app_state.get("db"):
        for a in new_alerts:
            ad = a.to_dict()
            app_state["db"].save_incident(ad)
            if app_state.get("dispatcher"):
                app_state["dispatcher"].dispatch(ad)

    # 4. Render Annotations onto Frame
    annotated_frame = visualizer.render(
        frame=frame,
        detections=tracked_dets,
        tracker=tracker,
        zone_manager=zone_mgr,
        active_alerts=new_alerts or incident_eng.active_alerts[-3:],
        fps=app_state["current_fps"],
        latency_ms=inf_ms,
    )

    # 5. Compress to JPEG
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
    _, buffer = cv2.imencode(".jpg", annotated_frame, encode_param)

    loop_elapsed = time.perf_counter() - loop_start
    return buffer, tracked_dets, new_alerts, inf_ms


@app.get("/video/feed", tags=["Video"])
async def video_feed_endpoint():
    """MJPEG Streaming endpoint for direct HTTP video feed."""
    async def frame_generator():
        frame_idx = 0
        while True:
            frame_idx += 1
            buffer, _, _, _ = await asyncio.to_thread(process_single_frame, frame_idx)
            if buffer is not None:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
            await asyncio.sleep(0.033)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.websocket("/ws/stream")
async def websocket_stream_endpoint(websocket: WebSocket):
    """
    Robust asynchronous WebSocket endpoint delivering real-time annotated video frames,
    detections, tracking vectors, and incident alerts with separated non-blocking I/O.
    """
    await websocket.accept()
    logger.info("Client connected to real-time WebSocket video stream.")

    frame_idx = 0
    prev_time = time.perf_counter()
    stop_event = asyncio.Event()

    async def client_receiver():
        """Handles incoming commands from client without blocking frame stream."""
        try:
            while not stop_event.is_set():
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                    action = data.get("action")
                    if action == "set_source":
                        new_src = data.get("source", "synthetic")
                        logger.info(f"Switching video source to: {new_src}")
                        if app_state["video_stream"]:
                            app_state["video_stream"].release()
                        app_state["video_stream"] = VideoStream(source=new_src)
                    elif action == "toggle_zones":
                        app_state["visualizer"].show_zones = not app_state["visualizer"].show_zones
                    elif action == "toggle_trajectories":
                        app_state["visualizer"].show_trajectories = not app_state["visualizer"].show_trajectories
                    elif action == "set_confidence":
                        app_state["detector"].confidence_threshold = float(data.get("value", 0.35))
                except Exception as ex:
                    logger.warning(f"Error handling client action: {ex}")
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            stop_event.set()

    async def stream_sender():
        """Pushes frames and telemetry to client at smooth ~30 FPS."""
        nonlocal frame_idx, prev_time
        try:
            while not stop_event.is_set():
                loop_start = time.perf_counter()
                frame_idx += 1

                # Process computer vision in worker thread
                buffer, tracked_dets, new_alerts, inf_ms = await asyncio.to_thread(process_single_frame, frame_idx)

                if buffer is not None:
                    # Measure performance
                    now = time.perf_counter()
                    app_state["current_latency_ms"] = (now - prev_time) * 1000.0 if prev_time else 15.0
                    loop_elapsed = now - loop_start
                    app_state["current_fps"] = 1.0 / loop_elapsed if loop_elapsed > 0 else 30.0
                    prev_time = now

                    b64_frame = base64.b64encode(buffer).decode("utf-8")
                    payload = {
                        "frame_idx": frame_idx,
                        "fps": round(app_state["current_fps"], 1),
                        "inference_ms": round(inf_ms, 1),
                        "active_tracks_count": len(app_state["tracker"].tracks) if app_state.get("tracker") else 0,
                        "detections": [
                            {
                                "track_id": d.track_id,
                                "class_name": d.class_name,
                                "confidence": round(d.confidence, 2),
                                "center": [round(c, 1) for c in d.center],
                                "velocity": [round(v, 2) for v in d.velocity] if d.velocity else [0, 0],
                            }
                            for d in (tracked_dets or [])
                        ],
                        "new_alerts": [a.to_dict() for a in (new_alerts or [])],
                        "image": f"data:image/jpeg;base64,{b64_frame}",
                    }
                    await websocket.send_text(json.dumps(payload))

                # Frame pacing (~30 FPS)
                pacing_sleep = max(0.005, (1.0 / 30.0) - (time.perf_counter() - loop_start))
                await asyncio.sleep(pacing_sleep)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket send loop error: {e}")
        finally:
            stop_event.set()

    # Run receiver and sender concurrently
    receiver_task = asyncio.create_task(client_receiver())
    sender_task = asyncio.create_task(stream_sender())

    # Wait until either disconnects
    done, pending = await asyncio.wait(
        [receiver_task, sender_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()
    logger.info("WebSocket connection cleanly closed.")


def start_server():
    import uvicorn
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    uvicorn.run(
        "src.api.app:app",
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 8080),
        reload=False,
    )


if __name__ == "__main__":
    start_server()
