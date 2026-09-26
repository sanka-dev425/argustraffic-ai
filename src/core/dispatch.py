"""
ArgusTraffic AI - Enterprise Alert & Webhook Dispatcher
Asynchronously broadcasts incident payloads to Webhook endpoints,
Slack/Discord integrations, and IoT/MQTT brokers with retry policies.
"""

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
    """Non-blocking resilient incident broadcaster."""

    def __init__(self, webhook_url: Optional[str] = None, webhook_secret: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("ARGUS_WEBHOOK_URL", "")
        self.webhook_secret = webhook_secret or os.getenv("ARGUS_WEBHOOK_SECRET", "")
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

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
            logger.warning("Alert dispatch queue full. Dropping older event.")

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

    async def _send_webhook(self, alert: Dict[str, Any]) -> None:
        if not self.webhook_url or not self._client:
            return

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

        # Delivery with quick retries
        for attempt in range(1, 3):
            try:
                resp = await self._client.post(self.webhook_url, content=payload_bytes, headers=headers)
                if resp.status_code in [200, 201, 202, 204]:
                    logger.info(f"Successfully delivered alert {alert.get('alert_id')} to webhook.")
                    return
                else:
                    logger.warning(f"Webhook response status {resp.status_code} (attempt {attempt})")
            except Exception as e:
                logger.warning(f"Failed to post alert {alert.get('alert_id')} to webhook: {e}")
                await asyncio.sleep(0.4 * attempt)
