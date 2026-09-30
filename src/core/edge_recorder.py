"""
ArgusTraffic AI - Edge Local Ring-Buffer & Offline Incident Storage Engine
Provides:
1. Rolling circular frame buffer in memory for instantaneous pre/post incident capture.
2. Segmented disk chunk writer with FIFO quota management (prevents disk saturation).
3. Offline Incident Vault with Store-and-Forward synchronization when network restores.
Author: ArgusTraffic Autonomous Systems Engineering Team
"""

from collections import deque
import concurrent.futures
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
    Includes memory optimization by bounding frame dimensions to prevent RAM bloat.
    """

    def __init__(
        self,
        capacity_seconds: float = 15.0,
        fps: float = 30.0,
        max_resolution: Optional[Tuple[int, int]] = (1280, 720),
    ):
        self.capacity_frames = int(capacity_seconds * fps)
        self.fps = fps
        self.max_resolution = max_resolution
        self.buffer: deque = deque(maxlen=self.capacity_frames)
        self.lock = threading.Lock()

    def append(self, frame: np.ndarray, timestamp: Optional[float] = None) -> None:
        """Stores a timestamped frame into the circular ring."""
        if frame is None or frame.size == 0:
            return
        ts = timestamp or time.time()
        
        # Memory optimization: scale down if frame exceeds max_resolution
        stored_frame = frame
        if self.max_resolution:
            max_w, max_h = self.max_resolution
            h, w = frame.shape[:2]
            if w > max_w or h > max_h:
                scale = min(max_w / w, max_h / h)
                new_w, new_h = int(w * scale), int(h * scale)
                stored_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        with self.lock:
            self.buffer.append((ts, stored_frame.copy()))

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
    Utilizes an asynchronous ThreadPoolExecutor for non-blocking clip encoding.
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
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="ArgusClipWriter",
        )
        try:
            from src.core.evidence_vault_crypto import VaultCryptoEngine
            self.crypto_engine = VaultCryptoEngine()
        except Exception:
            self.crypto_engine = None

        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

    def lock_incident_clip_async(
        self,
        incident_id: str,
        frames: List[Tuple[float, np.ndarray]],
        metadata: Dict[str, Any],
        fps: float = 30.0,
        encrypt_at_rest: bool = True,
    ) -> concurrent.futures.Future:
        """Asynchronously encodes and saves incident video clip without blocking the vision loop."""
        return self._executor.submit(
            self.lock_incident_clip,
            incident_id,
            frames,
            metadata,
            fps,
            encrypt_at_rest,
        )

    def shutdown(self, wait: bool = False) -> None:
        """Gracefully flushes pending clip writers on shutdown."""
        self._executor.shutdown(wait=wait)

    def lock_incident_clip(
        self,
        incident_id: str,
        frames: List[Tuple[float, np.ndarray]],
        metadata: Dict[str, Any],
        fps: float = 30.0,
        encrypt_at_rest: bool = True,
    ) -> Optional[Path]:
        """
        Compiles captured frames into an H.264/MP4 or JPEG package, optionally encrypts
        with defense-grade AES-256-GCM, and locks it in local edge storage.
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

        # AES-256 Encryption at rest
        is_encrypted = False
        final_path = clip_path
        if encrypt_at_rest and self.crypto_engine and clip_path.exists():
            try:
                enc_path = self.crypto_engine.encrypt_file(clip_path)
                clip_path.unlink(missing_ok=True)
                final_path = enc_path
                is_encrypted = True
            except Exception as e:
                logger.warning(f"Failed to encrypt clip at rest: {e}, keeping raw container.")

        # Store sync manifest
        manifest = {
            "incident_id": incident_id,
            "clip_path": str(final_path),
            "clip_size_bytes": final_path.stat().st_size if final_path.exists() else 0,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "encrypted": is_encrypted,
            "cipher_suite": "AES-256-GCM-AUTH" if is_encrypted else "RAW",
            "metadata": metadata,
            "synced_to_hq": False,
        }
        manifest_path = self.manifests_dir / f"{incident_id}.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Edge Vault locked incident clip: {final_path.name} ({manifest['clip_size_bytes']} bytes, encrypted={is_encrypted})")
        return final_path

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

    def get_clip_path(self, incident_id: str) -> Optional[Path]:
        """Returns the local filesystem path to the MP4/AVI/JPEG clip for an incident."""
        mf = self.manifests_dir / f"{incident_id}.json"
        if mf.exists():
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                p = Path(data.get("clip_path", ""))
                if p.exists():
                    return p
            except Exception:
                pass

        for f in self.clips_dir.glob(f"{incident_id}*"):
            if f.is_file() and f.stat().st_size > 0:
                return f

        return None

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
