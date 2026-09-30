"""
ArgusTraffic AI - Enterprise Storage & Disk Space Watchdog Subsystem
Monitors disk utilization on the telemetry host and enforces automated FIFO retention policies.
Protects mission-critical SQLite ledgers and active RTSP buffers from catastrophic disk saturation.
Guarantees Court Evidence Legal Hold preservation against automated pruning.
"""

import datetime
import logging
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.utils.paths import get_data_dir

logger = logging.getLogger("argustraffic.storage")


class StorageHealthStatus:
    OPTIMAL = "OPTIMAL"                  # < 75% used
    WARNING = "WARNING_HIGH_USAGE"       # 75% - 85% used
    CRITICAL = "CRITICAL_PURGE_REQUIRED" # 85% - 95% used
    EMERGENCY = "EMERGENCY_SATURATED"    # > 95% used


class StorageWatchdogManager:
    """
    Automated Disk Space Governor & FIFO Evidence Pruning Subsystem with Legal Hold protection.
    """

    _instance = None

    def __new__(cls, data_dir: Optional[Union[str, Path]] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, data_dir: Optional[Union[str, Path]] = None):
        if data_dir is not None:
            self.data_dir = Path(data_dir)
            self._initialized = True
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.legal_holds: Set[str] = getattr(self, "legal_holds", set())
            return
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.data_dir = get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.legal_holds: Set[str] = set()

    def add_legal_hold(self, file_path: Union[str, Path]) -> None:
        """Flags an evidence file or bundle with strict legal hold protection."""
        self.legal_holds.add(str(Path(file_path).resolve()))
        logger.info(f"[STORAGE-WATCHDOG] Legal hold placed on {file_path}")

    def remove_legal_hold(self, file_path: Union[str, Path]) -> None:
        """Removes legal hold protection from a file."""
        self.legal_holds.discard(str(Path(file_path).resolve()))

    def is_protected_file(self, file_path: Path) -> bool:
        """Checks if a file is protected from FIFO purging by extension or legal hold."""
        PROTECTED_EXTENSIONS = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".db-journal")
        if file_path.name.lower().endswith(PROTECTED_EXTENSIONS):
            return True
        str_p = str(file_path.resolve())
        if str_p in self.legal_holds:
            return True
        # Path markers
        lower_p = str_p.lower()
        if "court_bundle" in lower_p or "legal_hold" in lower_p or "evidence_bundle" in lower_p or "merkle_chain" in lower_p:
            return True
        return False

    def get_storage_status(self) -> Dict[str, Any]:
        """Calculates host drive capacity, application data footprint, and disk health."""
        try:
            total, used, free = shutil.disk_usage(str(self.data_dir))
        except Exception:
            total, used, free = 100 * 1024 * 1024 * 1024, 20 * 1024 * 1024 * 1024, 80 * 1024 * 1024 * 1024

        percent_used = (used / total) * 100.0 if total > 0 else 0.0
        percent_free = (free / total) * 100.0 if total > 0 else 100.0

        if percent_used >= 95.0:
            health = StorageHealthStatus.EMERGENCY
        elif percent_used >= 85.0:
            health = StorageHealthStatus.CRITICAL
        elif percent_used >= 75.0:
            health = StorageHealthStatus.WARNING
        else:
            health = StorageHealthStatus.OPTIMAL

        # Calculate App specific storage footprint
        app_bytes = 0
        file_count = 0
        try:
            for root, _, files in os.walk(str(self.data_dir)):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        app_bytes += os.path.getsize(fp)
                        file_count += 1
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "status": health,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "percent_used": round(percent_used, 1),
            "percent_free": round(percent_free, 1),
            "app_data_bytes": app_bytes,
            "app_data_mb": round(app_bytes / (1024**2), 2),
            "total_managed_files": file_count,
            "total_legal_holds": len(self.legal_holds),
            "data_directory": str(self.data_dir),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def execute_fifo_purge(
        self,
        max_target_used_pct: float = 80.0,
        purge_subdirs: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Prunes oldest non-critical snapshot/clip files (FIFO order) until disk usage drops below target.
        Mission-critical SQLite database files and Court-Flagged Legal Holds are strictly protected.
        """
        status = self.get_storage_status()
        current_used_pct = status["percent_used"]

        if current_used_pct <= max_target_used_pct and not dry_run:
            return {
                "purge_executed": False,
                "reason": f"Disk utilization ({current_used_pct}%) is within safe threshold (<= {max_target_used_pct}%).",
                "files_pruned": 0,
                "bytes_freed": 0,
                "current_status": status,
            }

        target_dirs = purge_subdirs or ["snapshots", "evidence", "temp", "recordings", "clips"]
        candidates = []

        for sub in target_dirs:
            target_path = self.data_dir / sub
            if target_path.exists() and target_path.is_dir():
                for p in target_path.rglob("*"):
                    if p.is_file() and not self.is_protected_file(p):
                        try:
                            mtime = p.stat().st_mtime
                            size = p.stat().st_size
                            candidates.append((mtime, size, p))
                        except Exception:
                            pass

        # Sort candidate files by oldest modification time first (FIFO)
        candidates.sort(key=lambda x: x[0])

        files_deleted = 0
        bytes_freed = 0
        deleted_names = []

        for mtime, size, file_path in candidates:
            if not dry_run:
                try:
                    file_path.unlink(missing_ok=True)
                    files_deleted += 1
                    bytes_freed += size
                    deleted_names.append(file_path.name)
                except Exception as e:
                    logger.warning(f"Could not delete file {file_path}: {e}")
            else:
                files_deleted += 1
                bytes_freed += size
                deleted_names.append(file_path.name)

            # Check if freed enough bytes
            updated_status = self.get_storage_status()
            if updated_status["percent_used"] <= max_target_used_pct:
                break

        logger.info(f"[STORAGE-WATCHDOG] Purge finished: {files_deleted} files removed, {bytes_freed / (1024**2):.2f} MB freed.")

        return {
            "purge_executed": True,
            "dry_run": dry_run,
            "files_pruned": files_deleted,
            "bytes_freed": bytes_freed,
            "mb_freed": round(bytes_freed / (1024**2), 2),
            "target_used_pct": max_target_used_pct,
            "resulting_status": self.get_storage_status(),
        }
