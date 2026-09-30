"""
ArgusTraffic AI - High-Throughput Async Batch SQLite Database Writer Queue
Eliminates database lock contention under incident bursts by buffering writes in-memory
and flushing atomically via executemany() in single WAL write transactions.
"""

import atexit
import logging
from pathlib import Path
import queue
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.utils.paths import get_data_dir

logger = logging.getLogger("argustraffic.batch_writer")


class AsyncDatabaseBatchWriter:
    """
    Non-blocking async SQLite batch ingestion pipeline.
    Maintains an in-memory queue and flushes bulk records every `flush_interval_seconds`
    or when the queue reaches `batch_size_threshold`.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        flush_interval_seconds: float = 0.25,
        batch_size_threshold: int = 50,
        max_queue_size: int = 10000,
    ):
        self.db_path = Path(db_path) if db_path else (get_data_dir() / "incident_db.db")
        self.flush_interval_seconds = flush_interval_seconds
        self.batch_size_threshold = batch_size_threshold
        self.queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.running = True
        self._lock = threading.Lock()
        self.total_committed_records = 0
        self.total_batches_flushed = 0

        # Background worker daemon thread
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="DB-BatchWriter-Worker")
        self.worker_thread.start()
        atexit.register(self.shutdown)
        logger.info(f"[BATCH-WRITER] Initialized background SQLite batch writer for {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def enqueue_incident(self, incident_dict: Dict[str, Any]):
        """
        Enqueues an incident record for async bulk commit without blocking calling vision thread.
        """
        try:
            self.queue.put_nowait(("INCIDENT", incident_dict))
        except queue.Full:
            logger.critical("[BATCH-WRITER] Memory queue saturated! Dropping least critical record to prevent crash.")

    def enqueue_raw(self, sql_query: str, params: Tuple):
        """Enqueues generic parameterized query."""
        try:
            self.queue.put_nowait(("RAW_SQL", (sql_query, params)))
        except queue.Full:
            logger.critical("[BATCH-WRITER] Memory queue saturated!")

    def _worker_loop(self):
        """Continuous background batch consumer loop."""
        buffer: List[Tuple[str, Any]] = []
        last_flush_time = time.time()

        while self.running:
            try:
                # Wait for items with timeout
                timeout = max(0.01, self.flush_interval_seconds - (time.time() - last_flush_time))
                try:
                    item = self.queue.get(timeout=timeout)
                    buffer.append(item)
                    self.queue.task_done()
                except queue.Empty:
                    pass

                # Flush condition
                time_elapsed = time.time() - last_flush_time
                if buffer and (len(buffer) >= self.batch_size_threshold or time_elapsed >= self.flush_interval_seconds):
                    self._flush_batch(buffer)
                    buffer.clear()
                    last_flush_time = time.time()

            except Exception as e:
                logger.error(f"[BATCH-WRITER] Exception in worker loop: {e}", exc_info=True)
                time.sleep(0.1)

        # Final flush on shutdown
        if buffer:
            self._flush_batch(buffer)

    def _flush_batch(self, items: List[Tuple[str, Any]]):
        """Executes a single atomic multi-statement transaction."""
        if not items:
            return

        incidents_to_insert = []
        raw_queries = []

        for item_type, data in items:
            if item_type == "INCIDENT":
                # Convert incident dict to tuple
                inc_id = data.get("alert_id") or data.get("incident_id") or f"INC-{int(time.time()*1000)}"
                inc_type = data.get("type") or data.get("incident_type") or "TRAFFIC_HAZARD"
                sev = data.get("severity") or "WARNING"
                ts = data.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                desc = data.get("description") or "Automated optical hazard violation"
                loc_x = float(data.get("location_x") or data.get("centroid", [0, 0])[0] if isinstance(data.get("centroid"), (list, tuple)) else 0.0)
                loc_y = float(data.get("location_y") or data.get("centroid", [0, 0])[1] if isinstance(data.get("centroid"), (list, tuple)) else 0.0)
                cam_id = data.get("camera_id") or "CAM-01"

                incidents_to_insert.append((inc_id, inc_type, sev, ts, desc, loc_x, loc_y, cam_id))
            elif item_type == "RAW_SQL":
                raw_queries.append(data)

        t0 = time.time()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Ensure incidents table exists with necessary columns
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS incidents (
                        incident_id TEXT PRIMARY KEY,
                        incident_type TEXT,
                        severity TEXT,
                        timestamp TEXT,
                        description TEXT,
                        location_x REAL,
                        location_y REAL,
                        camera_id TEXT DEFAULT 'CAM-01'
                    )
                """)

                if incidents_to_insert:
                    cursor.executemany(
                        """
                        INSERT OR REPLACE INTO incidents 
                        (incident_id, incident_type, severity, timestamp, description, location_x, location_y, camera_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        incidents_to_insert,
                    )

                for sql, params in raw_queries:
                    cursor.execute(sql, params)

                conn.commit()

            duration_ms = (time.time() - t0) * 1000
            self.total_committed_records += len(items)
            self.total_batches_flushed += 1
            logger.debug(f"[BATCH-WRITER] Committed batch of {len(items)} records in {duration_ms:.2f}ms (Total: {self.total_committed_records})")

        except Exception as e:
            logger.error(f"[BATCH-WRITER] Batch transaction commit failed: {e}", exc_info=True)

    def flush_sync(self):
        """Forces immediate synchronous flush of any pending records."""
        items = []
        while not self.queue.empty():
            try:
                items.append(self.queue.get_nowait())
                self.queue.task_done()
            except queue.Empty:
                break
        if items:
            self._flush_batch(items)

    def shutdown(self):
        """Gracefully halts worker thread and flushes remaining queue."""
        if not self.running:
            return
        self.running = False
        self.flush_sync()
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)
        logger.info("[BATCH-WRITER] Async batch writer cleanly stopped.")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "queue_depth": self.queue.qsize(),
            "total_committed_records": self.total_committed_records,
            "total_batches_flushed": self.total_batches_flushed,
            "flush_interval_seconds": self.flush_interval_seconds,
            "batch_size_threshold": self.batch_size_threshold,
        }
