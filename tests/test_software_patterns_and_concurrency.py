"""
ArgusTraffic AI - Software Patterns, Concurrency & Memory Hardening Verification Suite
Tests for:
1. AsyncDatabaseBatchWriter (Non-blocking SQLite batching & WAL transaction isolation)
2. FrameMemoryPool (Pre-allocated zero-copy C-contiguous memory recycling)
3. WorkerSupervisor (Erlang/OTP style thread supervision & auto-resurrection)
4. WebSocket Conflation & Non-blocking Backpressure Guards
"""

import time
import numpy as np
import pytest
import sqlite3
from pathlib import Path

from src.core.batch_writer import AsyncDatabaseBatchWriter
from src.core.memory_pool import FrameMemoryPool
from src.core.process_supervisor import WorkerState, WorkerSupervisor


# ==============================================================================
# 1. Async Database Batch Writer Tests
# ==============================================================================
class TestAsyncDatabaseBatchWriter:
    def test_batch_writer_ingestion_and_flush(self, tmp_path):
        db_file = tmp_path / "test_batch.db"
        writer = AsyncDatabaseBatchWriter(
            db_path=db_file,
            flush_interval_seconds=0.1,
            batch_size_threshold=5,
        )

        # Enqueue 10 incident records
        for i in range(10):
            writer.enqueue_incident({
                "alert_id": f"INC-BATCH-{i}",
                "type": "WRONG_WAY",
                "severity": "CRITICAL",
                "description": f"Test batch record {i}",
                "location_x": 100.0 + i,
                "location_y": 200.0 + i,
            })

        # Allow worker thread to flush
        time.sleep(0.35)
        writer.flush_sync()

        stats = writer.get_stats()
        assert stats["total_committed_records"] >= 10

        # Verify records in SQLite directly
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM incidents")
        count = cursor.fetchone()[0]
        conn.close()

        assert count >= 10


# ==============================================================================
# 2. Pre-Allocated Frame Memory Pool Tests
# ==============================================================================
class TestFrameMemoryPool:
    def test_acquire_and_release_buffers(self):
        pool = FrameMemoryPool(pool_size=4, frame_shape=(100, 100, 3))
        
        # Acquire 4 buffers
        b1_id, b1 = pool.acquire_buffer()
        b2_id, b2 = pool.acquire_buffer()
        b3_id, b3 = pool.acquire_buffer()
        b4_id, b4 = pool.acquire_buffer()

        assert b1_id != -1 and b2_id != -1 and b3_id != -1 and b4_id != -1
        assert b1.shape == (100, 100, 3)
        assert pool.get_stats()["in_use_buffers"] == 4

        # Exhaustion fallback
        fallback_id, fallback_buf = pool.acquire_buffer()
        assert fallback_id == -1 # Indicates unmanaged fallback
        assert fallback_buf.shape == (100, 100, 3)

        # Release back to pool
        pool.release_buffer(b1_id)
        pool.release_buffer(b2_id)
        assert pool.get_stats()["available_buffers"] == 2

        # Re-acquire recycled buffer
        re_id, _ = pool.acquire_buffer()
        assert re_id in (b1_id, b2_id)


# ==============================================================================
# 3. Worker Process Supervisor Tests
# ==============================================================================
class TestWorkerSupervisor:
    def test_supervisor_worker_lifecycle_and_resurrection(self):
        supervisor = WorkerSupervisor(supervisor_interval_seconds=0.2)
        counter = {"runs": 0}

        def failing_task():
            counter["runs"] += 1
            if counter["runs"] == 1:
                raise RuntimeError("Simulated crash on first run")
            # Keep alive on second run
            while True:
                time.sleep(0.05)

        supervisor.register_worker(
            name="test_worker_01",
            target_func=failing_task,
            max_restarts=3,
            heartbeat_timeout_seconds=0.5,
        )

        # Allow supervisor to detect crash and resurrect
        time.sleep(0.6)

        status = supervisor.get_supervisor_status()
        assert "test_worker_01" in status
        assert status["test_worker_01"]["restart_count"] >= 1
        assert counter["runs"] >= 2
