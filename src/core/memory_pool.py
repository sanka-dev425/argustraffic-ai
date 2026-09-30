"""
ArgusTraffic AI - Zero-Copy Pre-Allocated Frame Memory Pool
Eliminates memory heap fragmentation and Garbage Collection (GC) pauses
by recycling a fixed pool of C-contiguous pre-allocated NumPy array buffers.
"""

import logging
import threading
from typing import List, Optional, Tuple
import numpy as np

logger = logging.getLogger("argustraffic.memory_pool")


class FrameMemoryPool:
    """
    Thread-safe static pre-allocated memory buffer pool for high-rate video frame pipelines.
    """

    def __init__(
        self,
        pool_size: int = 16,
        frame_shape: Tuple[int, int, int] = (720, 1280, 3),
        dtype=np.uint8,
    ):
        self.pool_size = pool_size
        self.frame_shape = frame_shape
        self.dtype = dtype
        self._lock = threading.Lock()

        # Pre-allocate contiguous array buffers in RAM
        self._buffers: List[np.ndarray] = [
            np.zeros(frame_shape, dtype=dtype, order="C") for _ in range(pool_size)
        ]
        self._available_indices: List[int] = list(range(pool_size))
        self._total_borrows = 0
        self._total_returns = 0
        self._pool_exhaustions = 0

        logger.info(f"[MEM-POOL] Pre-allocated {pool_size} frames of shape {frame_shape} ({dtype}) in C-contiguous RAM.")

    def acquire_buffer(self) -> Tuple[int, np.ndarray]:
        """
        Acquires a pre-allocated buffer from pool.
        Returns (buffer_id, numpy_buffer).
        """
        with self._lock:
            if not self._available_indices:
                self._pool_exhaustions += 1
                # Fallback on-demand allocation if all buffers in pool are checked out
                return -1, np.zeros(self.frame_shape, dtype=self.dtype, order="C")

            buf_id = self._available_indices.pop()
            self._total_borrows += 1
            return buf_id, self._buffers[buf_id]

    def release_buffer(self, buffer_id: int):
        """
        Returns buffer back to pool for zero-allocation reuse.
        """
        if buffer_id < 0 or buffer_id >= self.pool_size:
            return  # Fallback buffer dropped to GC

        with self._lock:
            if buffer_id not in self._available_indices:
                self._available_indices.append(buffer_id)
                self._total_returns += 1

    def get_stats(self):
        with self._lock:
            return {
                "pool_size": self.pool_size,
                "available_buffers": len(self._available_indices),
                "in_use_buffers": self.pool_size - len(self._available_indices),
                "total_borrows": self._total_borrows,
                "total_returns": self._total_returns,
                "pool_exhaustions": self._pool_exhaustions,
            }
