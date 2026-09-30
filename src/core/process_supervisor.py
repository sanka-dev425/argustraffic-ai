"""
ArgusTraffic AI - Erlang/OTP Style Worker Process & Thread Supervisor
Supervises background camera worker loops, watchdog daemons, and video streaming sinks.
Detects silent thread deaths or hung tasks and automatically resurrects them.
"""

import atexit
from dataclasses import dataclass
from enum import Enum
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("argustraffic.supervisor")


class WorkerState(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRASHED = "CRASHED"
    STOPPED = "STOPPED"


@dataclass
class SupervisedWorker:
    name: str
    target_func: Callable
    args: tuple
    kwargs: dict
    thread: Optional[threading.Thread]
    state: WorkerState
    last_heartbeat: float
    restart_count: int
    max_restarts: int
    heartbeat_timeout_seconds: float


class WorkerSupervisor:
    """
    Central Fault-Tolerant Supervisor.
    """

    def __init__(self, supervisor_interval_seconds: float = 1.0):
        self.supervisor_interval_seconds = supervisor_interval_seconds
        self.workers: Dict[str, SupervisedWorker] = {}
        self._lock = threading.Lock()
        self.running = True

        self.supervisor_thread = threading.Thread(
            target=self._supervision_loop,
            daemon=True,
            name="Argus-ProcessSupervisor",
        )
        self.supervisor_thread.start()
        atexit.register(self.shutdown)
        logger.info("[SUPERVISOR] Process & Thread Supervisor Tree online.")

    def register_worker(
        self,
        name: str,
        target_func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        max_restarts: int = 10,
        heartbeat_timeout_seconds: float = 5.0,
    ):
        """Registers a worker and spawns its initial thread."""
        kwargs = kwargs or {}
        with self._lock:
            worker = SupervisedWorker(
                name=name,
                target_func=target_func,
                args=args,
                kwargs=kwargs,
                thread=None,
                state=WorkerState.STARTING,
                last_heartbeat=time.time(),
                restart_count=0,
                max_restarts=max_restarts,
                heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            )
            self._spawn_worker(worker)
            self.workers[name] = worker
            logger.info(f"[SUPERVISOR] Registered supervised worker '{name}'.")

    def _spawn_worker(self, worker: SupervisedWorker):
        """Launches a worker inside a supervised thread."""
        def wrapped_target(*a, **kw):
            try:
                worker.state = WorkerState.HEALTHY
                worker.last_heartbeat = time.time()
                worker.target_func(*a, **kw)
            except Exception as e:
                logger.critical(f"[SUPERVISOR] Supervised worker '{worker.name}' crashed: {e}", exc_info=True)
                worker.state = WorkerState.CRASHED

        t = threading.Thread(target=wrapped_target, args=worker.args, kwargs=worker.kwargs, daemon=True, name=f"Worker-{worker.name}")
        worker.thread = t
        worker.last_heartbeat = time.time()
        t.start()

    def record_heartbeat(self, name: str):
        """Called by active workers to keep watchdog heartbeat updated."""
        with self._lock:
            if name in self.workers:
                self.workers[name].last_heartbeat = time.time()
                self.workers[name].state = WorkerState.HEALTHY

    def _supervision_loop(self):
        """Continuous watchdog monitor."""
        while self.running:
            time.sleep(self.supervisor_interval_seconds)
            now = time.time()

            with self._lock:
                for name, worker in list(self.workers.items()):
                    if not self.running:
                        break

                    is_alive = worker.thread.is_alive() if worker.thread else False
                    elapsed_since_hb = now - worker.last_heartbeat

                    # Check for dead thread or heartbeat timeout
                    if not is_alive or elapsed_since_hb > worker.heartbeat_timeout_seconds:
                        if worker.restart_count < worker.max_restarts:
                            worker.restart_count += 1
                            logger.warning(
                                f"[SUPERVISOR] Worker '{name}' failed (alive={is_alive}, silent_timeout={elapsed_since_hb:.1f}s). "
                                f"Resurrecting worker (Attempt {worker.restart_count}/{worker.max_restarts})..."
                            )
                            self._spawn_worker(worker)
                        else:
                            worker.state = WorkerState.CRASHED
                            logger.critical(f"[SUPERVISOR] Worker '{name}' exceeded maximum restart threshold ({worker.max_restarts}). Halting resurrection.")

    def get_supervisor_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                name: {
                    "state": w.state.value,
                    "is_alive": w.thread.is_alive() if w.thread else False,
                    "last_heartbeat_ago_sec": round(time.time() - w.last_heartbeat, 2),
                    "restart_count": w.restart_count,
                    "max_restarts": w.max_restarts,
                }
                for name, w in self.workers.items()
            }

    def shutdown(self):
        self.running = False
        logger.info("[SUPERVISOR] Supervisor stopped.")
