"""
ArgusTraffic AI - Dynamic Hardware Load Governor & Adaptive Inference Throttler
Prevents GPU VRAM exhaustion, CUDA Out-of-Memory (OOM) faults, and CPU thread starvation
when scaling to 8+ high-resolution 4K/1080p camera streams simultaneously.
"""

from dataclasses import dataclass
from enum import Enum
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("argustraffic.governor")


class GovernorState(str, Enum):
    OPTIMAL = "OPTIMAL"                  # Normal load: 100% full-rate processing
    HIGH_LOAD = "HIGH_LOAD_ADAPTIVE"     # Load > 75%: skip every 2nd frame on overview cameras
    CRITICAL = "CRITICAL_OOM_SHEDDING"   # Load > 90%: prioritize emergency radar/hazard zones only


@dataclass
class StreamWorkloadProfile:
    camera_id: str
    is_priority_zone: bool
    frames_received: int = 0
    frames_processed: int = 0
    frames_shed: int = 0
    avg_inference_latency_ms: float = 12.0


class HardwareGovernor:
    """
    Intelligent Compute Governor & Edge Inference Rate Throttler.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.lock = threading.Lock()
        self.state = GovernorState.OPTIMAL
        self.streams: Dict[str, StreamWorkloadProfile] = {}
        self.total_shed_frames = 0
        self.total_processed_frames = 0
        self.last_load_check_time = time.time()
        self.simulated_load_factor = 0.35  # Default nominal load

    def register_stream(self, camera_id: str, is_priority_zone: bool = False) -> None:
        """Registers a camera stream into the workload governor."""
        with self.lock:
            self.streams[camera_id] = StreamWorkloadProfile(
                camera_id=camera_id,
                is_priority_zone=is_priority_zone,
            )

    def record_inference_time(self, camera_id: str, latency_ms: float) -> None:
        """Updates rolling inference latency to detect hardware backpressure."""
        with self.lock:
            prof = self.streams.get(camera_id)
            if prof:
                prof.avg_inference_latency_ms = (prof.avg_inference_latency_ms * 0.8) + (latency_ms * 0.2)

            # Check if backpressure requires state escalation
            if latency_ms > 85.0:
                self.state = GovernorState.CRITICAL
            elif latency_ms > 45.0:
                self.state = GovernorState.HIGH_LOAD
            else:
                self.state = GovernorState.OPTIMAL

    def set_system_load_factor(self, load_factor: float) -> None:
        """Manually or externally updates the load factor (0.0 to 1.0)."""
        with self.lock:
            self.simulated_load_factor = max(0.0, min(1.0, load_factor))
            if self.simulated_load_factor >= 0.88:
                self.state = GovernorState.CRITICAL
            elif self.simulated_load_factor >= 0.70:
                self.state = GovernorState.HIGH_LOAD
            else:
                self.state = GovernorState.OPTIMAL

    def should_process_frame(self, camera_id: str, frame_index: int, is_priority_zone: bool = False) -> bool:
        """
        Calculates whether a frame should undergo full neural network inference
        or be throttled to prevent GPU VRAM exhaustion.
        """
        with self.lock:
            prof = self.streams.get(camera_id)
            if not prof:
                prof = StreamWorkloadProfile(camera_id=camera_id, is_priority_zone=is_priority_zone)
                self.streams[camera_id] = prof

            prof.frames_received += 1

            if self.state == GovernorState.OPTIMAL:
                # 100% frame throughput
                prof.frames_processed += 1
                self.total_processed_frames += 1
                return True

            elif self.state == GovernorState.HIGH_LOAD:
                # Priority zones get 100% throughput; non-priority drops every 2nd frame
                if is_priority_zone or prof.is_priority_zone:
                    prof.frames_processed += 1
                    self.total_processed_frames += 1
                    return True
                else:
                    if frame_index % 2 == 0:
                        prof.frames_processed += 1
                        self.total_processed_frames += 1
                        return True
                    else:
                        prof.frames_shed += 1
                        self.total_shed_frames += 1
                        return False

            else:  # GovernorState.CRITICAL
                # Heavy load: priority zones process every 2nd frame; overview streams process every 4th frame
                if is_priority_zone or prof.is_priority_zone:
                    if frame_index % 2 == 0:
                        prof.frames_processed += 1
                        self.total_processed_frames += 1
                        return True
                    else:
                        prof.frames_shed += 1
                        self.total_shed_frames += 1
                        return False
                else:
                    if frame_index % 4 == 0:
                        prof.frames_processed += 1
                        self.total_processed_frames += 1
                        return True
                    else:
                        prof.frames_shed += 1
                        self.total_shed_frames += 1
                        return False

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns real-time compute load shedding and VRAM preservation metrics."""
        with self.lock:
            total_in = sum(p.frames_received for p in self.streams.values())
            total_proc = sum(p.frames_processed for p in self.streams.values())
            total_shed = sum(p.frames_shed for p in self.streams.values())
            shed_pct = round((total_shed / total_in * 100.0), 1) if total_in > 0 else 0.0

            return {
                "state": self.state.value,
                "load_factor": round(self.simulated_load_factor, 2),
                "total_monitored_streams": len(self.streams),
                "total_frames_ingested": total_in,
                "total_frames_processed": total_proc,
                "total_frames_shed": total_shed,
                "vram_preservation_ratio_pct": shed_pct,
                "stream_profiles": {
                    cid: {
                        "is_priority": p.is_priority_zone,
                        "received": p.frames_received,
                        "processed": p.frames_processed,
                        "shed": p.frames_shed,
                        "avg_latency_ms": round(p.avg_inference_latency_ms, 1),
                    }
                    for cid, p in self.streams.items()
                },
            }
