"""
ArgusTraffic AI - FastAPI Application & Real-Time Streaming Server
Combines REST services, WebSocket live video feeds, MJPEG stream, and UI Command Center.
"""

import asyncio
import base64
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple

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
from src.core.edge_recorder import EdgeRingBuffer, EdgeStorageVault
from src.core.hotlist_engine import WantedVehicleHotlistEngine
from src.core.sla_escalation import SLAEscalationManager
from src.core.station_mesh import NationalStationMeshAggregator
from src.core.camera_watchdog import CameraSelfHealingWatchdog
from src.core.device_manager import CameraInventoryManager
from src.core.speed_engine import PointToPointAverageSpeedEngine
from src.core.evidence_report import ReportTemplateManager
from src.core.system_settings import SystemSettingsManager
from src.core.storage_watchdog import StorageWatchdogManager
from src.core.hardware_governor import HardwareGovernor
from src.core.optical_tamper_detector import OpticalTamperDetector
from src.core.license_manager import LicenseManager
from src.core.ledger_sentinel import ContinuousLedgerSentinel
from src.core.batch_writer import AsyncDatabaseBatchWriter
from src.core.memory_pool import FrameMemoryPool
from src.core.process_supervisor import WorkerSupervisor
from src.perception.preprocessing.weather_enhancer import OpticalWeatherEnhancer
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
    "hotlist_engine": None,
    "sla_manager": None,
    "station_mesh": None,
    "edge_vault": None,
    "edge_ring_buffer": None,
    "weather_enhancer": None,
    "camera_watchdog": None,
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
    """Initializes detector, tracker, zones, incident engine, and enterprise subsystems."""
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

    # 9. Enterprise Mission-Critical Engines
    app_state["hotlist_engine"] = WantedVehicleHotlistEngine()
    app_state["sla_manager"] = SLAEscalationManager()
    app_state["station_mesh"] = NationalStationMeshAggregator()
    app_state["edge_vault"] = EdgeStorageVault()
    app_state["edge_ring_buffer"] = EdgeRingBuffer(capacity_seconds=15.0)
    app_state["weather_enhancer"] = OpticalWeatherEnhancer()
    app_state["camera_watchdog"] = CameraSelfHealingWatchdog()
    app_state["camera_watchdog"].register_camera("CAM-042", "192.168.1.100", "192.168.1.2", 1)
    app_state["camera_watchdog"].register_camera("CAM-118", "192.168.1.101", "192.168.1.2", 2)
    app_state["section_speed_engine"] = PointToPointAverageSpeedEngine()
    app_state["camera_inventory"] = CameraInventoryManager()
    app_state["report_template_mgr"] = ReportTemplateManager()
    app_state["settings_mgr"] = SystemSettingsManager()
    app_state["storage_watchdog"] = StorageWatchdogManager()
    app_state["hardware_governor"] = HardwareGovernor()
    app_state["optical_tamper_detector"] = OpticalTamperDetector()
    app_state["license_manager"] = LicenseManager()
    app_state["ledger_sentinel"] = ContinuousLedgerSentinel()
    app_state["batch_writer"] = AsyncDatabaseBatchWriter()
    app_state["memory_pool"] = FrameMemoryPool()
    app_state["supervisor"] = WorkerSupervisor()

    logger.info("All ArgusTraffic AI subsystems successfully initialized.")


# Initialize immediately for module imports
init_app_state()

app = FastAPI(
    title="ArgusTraffic AI - Autonomous Traffic Hazard Vision API",
    description="Real-Time Smart City & Traffic Incident Intelligence Engine with YOLOv8, Kalman Spatial Tracking, and Evidence Ledger.",
    version="2.0.0",
)

# Enable CORS for local desktop webview and authorized internal networks
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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


@app.get("/manifest.json", tags=["PWA"])
async def get_pwa_manifest():
    manifest_file = BASE_DIR / "src" / "web" / "manifest.json"
    if manifest_file.exists():
        return FileResponse(str(manifest_file), media_type="application/manifest+json")
    return HTMLResponse("{}", media_type="application/json")


@app.get("/sw.js", tags=["PWA"])
async def get_service_worker():
    sw_file = BASE_DIR / "src" / "web" / "sw.js"
    if sw_file.exists():
        return FileResponse(str(sw_file), media_type="application/javascript")
    return HTMLResponse("// noop", media_type="application/javascript")


def process_single_frame(frame_idx: int):
    """Synchronous CPU/GPU vision pipeline running inside worker thread with enterprise extensions."""
    detector = app_state["detector"]
    tracker = app_state["tracker"]
    zone_mgr = app_state["zone_manager"]
    incident_eng = app_state["incident_engine"]
    visualizer = app_state["visualizer"]
    stream = app_state["video_stream"]
    enhancer = app_state.get("weather_enhancer")
    ring_buf = app_state.get("edge_ring_buffer")
    edge_vault = app_state.get("edge_vault")
    sla_mgr = app_state.get("sla_manager")
    watchdog = app_state.get("camera_watchdog")

    if not stream:
        return None, None, None, 0.0

    ret, frame = stream.read_frame()
    if watchdog:
        watchdog.record_frame_status("CAM-042", ret and frame is not None)

    if not ret or frame is None:
        return None, None, None, 0.0

    # 0. Edge Ring Buffer & Weather Pre-Filter
    if ring_buf:
        ring_buf.append(frame)

    proc_frame = frame
    if enhancer:
        proc_frame, _ = enhancer.enhance(frame)

    loop_start = time.perf_counter()

    # 1. Detect
    detections, inf_ms = detector.detect(proc_frame)

    # 2. Track with Visual Re-ID
    tracked_dets = tracker.update(detections, frame=proc_frame)

    # 3. Incident Evaluation
    new_alerts = incident_eng.analyze_frame(
        frame_idx=frame_idx,
        detections=tracked_dets,
        tracker=tracker,
        zone_manager=zone_mgr,
        fps=app_state["current_fps"],
    )

    # Persist, archive in edge vault, and register in SLA watchdog
    if new_alerts:
        for a in new_alerts:
            ad = a.to_dict()
            if app_state.get("db"):
                app_state["db"].save_incident(ad)
            if app_state.get("batch_writer"):
                app_state["batch_writer"].enqueue_incident(ad)
            if app_state.get("dispatcher"):
                app_state["dispatcher"].dispatch(ad)
            if sla_mgr:
                sla_mgr.register_incident(ad)
            if edge_vault and ring_buf:
                clip_frames = ring_buf.get_pre_event_window(10.0)
                edge_vault.lock_incident_clip_async(ad.get("alert_id", "INC"), clip_frames, ad)

    # Periodic SLA Escalation check
    if sla_mgr and (frame_idx % 30 == 0):
        sla_mgr.evaluate_escalations()

    # 4. Render Annotations onto Frame
    annotated_frame = visualizer.render(
        frame=proc_frame,
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


class VideoStreamBroadcaster:
    """
    Centralized Single-Producer Multi-Consumer Broadcaster.
    Maintains a single computer vision processing loop that encodes frames once
    and broadcasts to all active WebSocket clients concurrently without duplicated inference.
    """

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()
        self.latest_buffer: Optional[bytes] = None
        self.latest_payload: Optional[str] = None
        self.worker_task: Optional[asyncio.Task] = None
        self.running = False
        self.frame_idx = 0
        self.prev_time = 0.0

    async def add_client(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.add(ws)
            if self.worker_task is None or self.worker_task.done():
                self.running = True
                self.worker_task = asyncio.create_task(self._broadcast_loop())
        if self.latest_payload:
            try:
                await ws.send_text(self.latest_payload)
            except Exception:
                pass

    async def remove_client(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.discard(ws)

    async def _broadcast_loop(self) -> None:
        logger.info("Centralized VideoStreamBroadcaster worker started.")
        try:
            while self.running:
                loop_start = time.perf_counter()

                async with self.lock:
                    num_clients = len(self.clients)

                if num_clients == 0:
                    await asyncio.sleep(0.05)
                    continue

                self.frame_idx += 1
                buffer, tracked_dets, new_alerts, inf_ms = await asyncio.to_thread(
                    process_single_frame, self.frame_idx
                )

                if buffer is not None:
                    now = time.perf_counter()
                    if self.prev_time:
                        app_state["current_latency_ms"] = (now - self.prev_time) * 1000.0
                        loop_elapsed = now - loop_start
                        app_state["current_fps"] = 1.0 / loop_elapsed if loop_elapsed > 0 else 30.0
                    self.prev_time = now

                    b64_frame = base64.b64encode(buffer).decode("utf-8")
                    payload = json.dumps({
                        "frame_idx": self.frame_idx,
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
                    })

                    self.latest_buffer = buffer.tobytes()
                    self.latest_payload = payload

                    async with self.lock:
                        target_clients = list(self.clients)

                    if target_clients:
                        # Non-blocking backpressure: drop frame for slow clients taking >150ms to prevent RAM queue buildup
                        async def safe_send(client):
                            return await asyncio.wait_for(client.send_text(payload), timeout=0.15)

                        results = await asyncio.gather(
                            *[safe_send(ws) for ws in target_clients],
                            return_exceptions=True,
                        )
                        stale = [ws for ws, res in zip(target_clients, results) if isinstance(res, (Exception, asyncio.TimeoutError))]
                        if stale:
                            async with self.lock:
                                for ws in stale:
                                    self.clients.discard(ws)

                pacing_sleep = max(0.005, (1.0 / 30.0) - (time.perf_counter() - loop_start))
                await asyncio.sleep(pacing_sleep)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Broadcaster loop error: {e}")
        finally:
            logger.info("VideoStreamBroadcaster worker ended.")


broadcaster = VideoStreamBroadcaster()
app_state["broadcaster"] = broadcaster


@app.get("/video/feed", tags=["Video"])
async def video_feed_endpoint(channel: str = "CAM-042"):
    """MJPEG Streaming endpoint for direct HTTP video feed supporting multi-channel command matrix."""
    async def frame_generator():
        if broadcaster.worker_task is None or broadcaster.worker_task.done():
            broadcaster.running = True
            broadcaster.worker_task = asyncio.create_task(broadcaster._broadcast_loop())

        # If requesting the main active broadcaster stream
        if channel == "CAM-042" or channel == "MAIN_FEED":
            while True:
                if broadcaster.latest_buffer:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + broadcaster.latest_buffer + b"\r\n"
                    )
                else:
                    buf, _, _, _ = await asyncio.to_thread(process_single_frame, 1)
                    if buf is not None:
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                        )
                await asyncio.sleep(0.033)
        else:
            # Dedicated perspective CCTV stream for secondary matrix channels (CAM-002, CAM-003, CAM-004)
            from src.utils.video_stream import PerspectiveCCTVSimulator
            sim = PerspectiveCCTVSimulator(camera_id=channel)
            while True:
                frame = sim.next_frame()
                _, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                )
                await asyncio.sleep(0.033)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws/stream")
async def websocket_stream_endpoint(websocket: WebSocket):
    """
    Robust asynchronous WebSocket endpoint delivering real-time annotated video frames,
    detections, tracking vectors, and incident alerts with separated non-blocking I/O.
    """
    await websocket.accept()
    logger.info("Client connected to real-time WebSocket video stream.")
    await broadcaster.add_client(websocket)

    try:
        while True:
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
        await broadcaster.remove_client(websocket)
        logger.info("WebSocket connection cleanly closed.")


@asynccontextmanager
async def lifespan(app_inst: FastAPI):
    """Modern lifespan event handler for robust subsystem startup and shutdown."""
    logger.info("ArgusTraffic AI platform online.")
    yield
    logger.info("Gracefully shutting down ArgusTraffic AI subsystems...")
    broadcaster.running = False
    if broadcaster.worker_task and not broadcaster.worker_task.done():
        broadcaster.worker_task.cancel()
    if app_state.get("video_stream"):
        try:
            app_state["video_stream"].release()
        except Exception:
            pass
    if app_state.get("dispatcher"):
        try:
            app_state["dispatcher"].stop()
        except Exception:
            pass
    logger.info("All subsystems cleanly terminated.")


app.router.lifespan_context = lifespan


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
