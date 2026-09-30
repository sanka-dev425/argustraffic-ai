from collections import deque
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("argustraffic.dispatch")


class AlertDispatcher:
    """Non-blocking resilient incident broadcaster with Exponential Backoff and Dead Letter Queue."""

    def __init__(self, webhook_url: Optional[str] = None, webhook_secret: Optional[str] = None, max_queue_size: int = 2000):
        self.webhook_url = webhook_url or os.getenv("ARGUS_WEBHOOK_URL", "")
        self.webhook_secret = webhook_secret or os.getenv("ARGUS_WEBHOOK_SECRET", "")
        self._max_queue_size = max_queue_size
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.dead_letter_queue: deque = deque(maxlen=500)
        self._worker_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self.total_delivered: int = 0
        self.total_failed: int = 0

    def start(self) -> None:
        """Starts the background worker queue if an event loop is running."""
        if self._worker_task is None:
            try:
                loop = asyncio.get_running_loop()
                self._client = httpx.AsyncClient(timeout=4.0)
                self._worker_task = loop.create_task(self._process_queue())
                logger.info("Alert Dispatcher background worker started.")
            except RuntimeError:
                # No running event loop at import time; will initialize on first async dispatch or server startup
                pass

    async def stop(self) -> None:
        """Flushes and cleanly stops dispatcher."""
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    def dispatch(self, alert_dict: Dict[str, Any]) -> None:
        """Enqueues alert for asynchronous delivery without blocking the vision loop."""
        if not self.webhook_url:
            return
        if self._worker_task is None:
            self.start()
        try:
            self._queue.put_nowait(alert_dict)
        except asyncio.QueueFull:
            try:
                # Discard oldest event to make room for newest high-priority incident
                self._queue.get_nowait()
                self._queue.put_nowait(alert_dict)
                logger.warning("Alert dispatch queue saturated (maxsize reached). Evicted oldest item.")
            except Exception:
                logger.warning("Alert dispatch queue full. Dropping event.")

    async def _process_queue(self) -> None:
        while True:
            try:
                alert = await self._queue.get()
                await self._send_webhook(alert)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing alert dispatch queue: {e}")
                await asyncio.sleep(0.5)

    async def _send_webhook(self, alert: Dict[str, Any]) -> bool:
        if not self.webhook_url or not self._client:
            return False

        payload_bytes = json.dumps(alert).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ArgusTraffic-AI-Dispatcher/1.0",
        }

        # HMAC Signature for webhook payload tamper protection
        if self.webhook_secret:
            signature = hmac.new(
                self.webhook_secret.encode("utf-8"),
                payload_bytes,
                hashlib.sha256,
            ).hexdigest()
            headers["X-Argus-Signature-256"] = f"sha256={signature}"

        # Delivery with Exponential Backoff Retries (Attempts 1 to 3)
        last_err = None
        for attempt in range(1, 4):
            try:
                resp = await self._client.post(self.webhook_url, content=payload_bytes, headers=headers)
                if resp.status_code in [200, 201, 202, 204]:
                    self.total_delivered += 1
                    logger.info(f"Successfully delivered alert {alert.get('alert_id')} to webhook.")
                    return True
                else:
                    last_err = f"HTTP {resp.status_code}"
                    logger.warning(f"Webhook response status {resp.status_code} (attempt {attempt}/3)")
            except Exception as e:
                last_err = str(e)
                logger.warning(f"Failed to post alert {alert.get('alert_id')} to webhook (attempt {attempt}/3): {e}")
            
            if attempt < 3:
                backoff = 0.25 * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        # All attempts exhausted: Move to Dead Letter Queue (DLQ)
        self.total_failed += 1
        dlq_entry = {
            "alert": alert,
            "failed_at": time.time(),
            "failed_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": last_err or "Max retries exhausted",
            "attempts": 3,
        }
        self.dead_letter_queue.append(dlq_entry)
        logger.error(f"[DISPATCH-DLQ] Alert {alert.get('alert_id')} permanently moved to Dead Letter Queue: {last_err}")
        return False

    def get_dead_letter_queue(self) -> List[Dict[str, Any]]:
        """Returns the list of buffered undelivered alerts."""
        return list(self.dead_letter_queue)

    async def drain_dead_letter_queue(self) -> int:
        """Attempts redelivery of all DLQ items."""
        if not self.dead_letter_queue:
            return 0
        items = list(self.dead_letter_queue)
        self.dead_letter_queue.clear()
        redelivered = 0
        for entry in items:
            alert = entry.get("alert", {})
            success = await self._send_webhook(alert)
            if success:
                redelivered += 1
        return redelivered

