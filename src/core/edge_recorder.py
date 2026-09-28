"""
ArgusTraffic AI - Edge Local Ring-Buffer & Offline Incident Storage Engine
Provides:
1. Rolling circular frame buffer in memory for instantaneous pre/post incident capture.
2. Segmented disk chunk writer with FIFO quota management (prevents disk saturation).
3. Offline Incident Vault with Store-and-Forward synchronization when network restores.
Author: Saptha Sanka (ArgusTraffic Autonomous Systems)
"""

from collections import deque
import datetime
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("argustraffic.edge_recorder")


class EdgeRingBuffer:
    """
    In-memory pre-event buffer holding the last N seconds of decoded frames.
    When a collision, wrong-way driving, or crime occurs, this enables saving the
    crucial seconds BEFORE the AI trigger occurred (pre-incident forensics).
    """

    def __init__(self, capacity_seconds: float = 15.0, fps: float = 30.0):
        self.capacity_frames = int(capacity_seconds * fps)
        self.fps = fps
        self.buffer: deque = deque(maxlen=self.capacity_frames)
        self.lock = threading.Lock()

    def append(self, frame: np.ndarray, timestamp: Optional[float] = None) -> None:
        """Stores a timestamped frame into the circular ring."""
        if frame is None or frame.size == 0:
            return
        ts = timestamp or time.time()
        with self.lock:
            self.buffer.append((ts, frame.copy()))

    def get_pre_event_window(self, window_seconds: float = 10.0) -> List[Tuple[float, np.ndarray]]:
        """Retrieves frames from the last window_seconds up to the current moment."""
        req_frames = int(window_seconds * self.fps)
        with self.lock:
            available = list(self.buffer)
        if not available:
            return []
        return available[-req_frames:]

    def clear(self) -> None:
        with self.lock:
            self.buffer.clear()

    @property
    def size(self) -> int:
        with self.lock:
            return len(self.buffer)


class EdgeStorageVault:
    """
    Local Edge NVR Segment Archiver and Store-and-Forward Dispatcher.
    Stores locked incident clips locally under %LOCALAPPDATA%/ArgusTraffic/vault
    and marks them for automated HQ cloud sync upon network restoration.
    """

    def __init__(self, storage_root: Optional[Path] = None, max_disk_mb: float = 2048.0):
        if storage_root is None:
            base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".argustraffic")))
            storage_root = base / "ArgusTraffic" / "edge_vault"
        self.storage_root = Path(storage_root)
        self.clips_dir = self.storage_root / "incident_clips"
        self.manifests_dir = self.storage_root / "pending_sync"
        self.max_disk_mb = max_disk_mb
        self.lock = threading.Lock()

        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def lock_incident_clip(
        self,
        incident_id: str,
        frames: List[Tuple[float, np.ndarray]],
        metadata: Dict[str, Any],
        fps: float = 30.0,
    ) -> Optional[Path]:
        """
        Compiles captured frames into an H.264/MP4 or JPEG package and locks it
        in local edge storage for store-and-forward dispatch.
        """
        if not frames:
            logger.warning(f"No frames provided to lock incident clip for {incident_id}")
            return None

        self._enforce_disk_quota()

        clip_filename = f"{incident_id}_{int(time.time())}.mp4"
        clip_path = self.clips_dir / clip_filename
        first_frame = frames[0][1]
        h, w = first_frame.shape[:2]

        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(clip_path), fourcc, fps, (w, h))
            for _, f in frames:
                if f.shape[:2] != (h, w):
                    f = cv2.resize(f, (w, h))
                writer.write(f)
            writer.release()
        except Exception as e:
            logger.error(f"Failed to write MP4 clip: {e}, falling back to keyframe image")
            clip_filename = f"{incident_id}_{int(time.time())}_keyframe.jpg"
            clip_path = self.clips_dir / clip_filename
            cv2.imwrite(str(clip_path), first_frame)

        # Store sync manifest
        manifest = {
            "incident_id": incident_id,
            "clip_path": str(clip_path),
            "clip_size_bytes": clip_path.stat().st_size if clip_path.exists() else 0,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "metadata": metadata,
            "synced_to_hq": False,
        }
        manifest_path = self.manifests_dir / f"{incident_id}.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Edge Vault locked incident clip: {clip_path.name} ({manifest['clip_size_bytes']} bytes)")
        return clip_path

    def get_pending_sync_queue(self) -> List[Dict[str, Any]]:
        """Returns all offline clips waiting to be uploaded to Central Headquarters."""
        pending = []
        for mf in self.manifests_dir.glob("*.json"):
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data.get("synced_to_hq", False):
                    pending.append(data)
            except Exception as e:
                logger.error(f"Error reading manifest {mf}: {e}")
        return pending

    def mark_as_synced(self, incident_id: str) -> bool:
        """Flags an incident as successfully synced to headquarters."""
        mf = self.manifests_dir / f"{incident_id}.json"
        if mf.exists():
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["synced_to_hq"] = True
                data["synced_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                with open(mf, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return True
            except Exception as e:
                logger.error(f"Error updating sync status for {incident_id}: {e}")
        return False

    def _enforce_disk_quota(self) -> None:
        """Purges oldest unsynced/synced clips if local disk quota is exceeded (FIFO)."""
        clips = sorted(self.clips_dir.glob("*.*"), key=lambda p: p.stat().st_mtime)
        total_size_mb = sum(p.stat().st_size for p in clips) / (1024 * 1024)

        while total_size_mb > self.max_disk_mb and clips:
            oldest = clips.pop(0)
            sz_mb = oldest.stat().st_size / (1024 * 1024)
            try:
                oldest.unlink()
                total_size_mb -= sz_mb
                logger.info(f"Disk quota pruned oldest edge clip: {oldest.name}")
            except Exception as e:
                logger.error(f"Failed to prune {oldest}: {e}")
