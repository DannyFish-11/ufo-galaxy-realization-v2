"""
Galaxy — Node NATS Heartbeat Sender (Phase C)
=============================================

Lightweight helper for Galaxy Python nodes to:
1. Send a one-shot ``galaxy.workers.register`` message on startup.
2. Periodically emit ``galaxy.workers.heartbeat`` every ``interval_s`` seconds.

Usage (inside a node's FastAPI lifespan)::

    from core.nats_heartbeat import NodeHeartbeatSender, start_node_heartbeat

    # Simple one-liner (registers + starts background heartbeat loop)
    _hb_task = await start_node_heartbeat(
        worker_id="node-04-router",
        device_type="router",
        capabilities=["routing", "discovery"],
        platform="python",
    )
    # In shutdown:
    _hb_task.cancel()

Configuration (env vars):
  GALAXY_NATS_URL              — NATS server URL
  GALAXY_HEARTBEAT_INTERVAL    — heartbeat interval in seconds (default 10)
  GALAXY_WORKER_VERSION        — worker version string (default "1.0.0")
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import socket
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nats_heartbeat")

_HEARTBEAT_INTERVAL_S = int(os.getenv("GALAXY_HEARTBEAT_INTERVAL", "10"))
_WORKER_VERSION = os.getenv("GALAXY_WORKER_VERSION", "1.0.0")


class NodeHeartbeatSender:
    """Sends periodic NATS heartbeats for a Galaxy Python node.

    Operates in silent no-op mode when NATS is not connected, so that
    nodes remain functional without a live NATS server.
    """

    def __init__(
        self,
        worker_id: str,
        device_type: str = "router",
        capabilities: Optional[List[str]] = None,
        platform_name: str = "",
        worker_version: str = _WORKER_VERSION,
        interval_s: int = _HEARTBEAT_INTERVAL_S,
        stats_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        trace_id: str = "",
    ) -> None:
        """
        Args:
            worker_id:       Unique identifier for this node (e.g. "node-04-router").
            device_type:     Device type matching DeviceType enum (e.g. "router").
            capabilities:    List of capability strings to advertise.
            platform_name:   Override platform string; auto-detected if empty.
            worker_version:  Version string for the node.
            interval_s:      Heartbeat emission interval in seconds.
            stats_fn:        Optional callable returning runtime metrics dict
                             (keys: cpu_usage_percent, memory_usage_percent, etc.).
            trace_id:        Optional TaskEnvelope trace_id for session correlation.
                             A new UUID is generated when not provided.
        """
        self._worker_id = worker_id
        self._device_type = device_type
        self._capabilities = capabilities or []
        self._platform = platform_name or platform.system().lower()
        self._worker_version = worker_version
        self._interval_s = interval_s
        self._stats_fn = stats_fn
        # A consistent trace_id is carried across registration and all heartbeats
        # so observers can correlate a worker session with the TaskEnvelope that
        # triggered its registration.
        self._trace_id: str = trace_id or str(uuid.uuid4())
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def register(self) -> dict:
        """Send a one-shot WorkerRegistration message to NATS."""
        try:
            from core.nats_bus import nats_bus

            if not nats_bus.is_connected():
                logger.debug(
                    "NodeHeartbeatSender[%s]: NATS not connected, skipping registration",
                    self._worker_id,
                )
                return {"success": False, "reason": "nats_not_connected"}

            from core.schemas.contracts import (
                WorkerCapabilityModel,
                WorkerRegistrationModel,
                TimestampModel,
            )
            from datetime import datetime, timezone

            caps = [
                WorkerCapabilityModel(name=c, version=self._worker_version)
                for c in self._capabilities
            ]
            reg = WorkerRegistrationModel(
                worker_id=self._worker_id,
                hostname=socket.gethostname(),
                device_type=self._device_type,
                platform=self._platform,
                os_version=platform.version(),
                worker_version=self._worker_version,
                capabilities=caps,
                registered_at=TimestampModel(
                    seconds=int(datetime.now(timezone.utc).timestamp())
                ),
            )
            result = await nats_bus._publish(
                "galaxy.workers.register",
                reg.model_dump(mode="json", exclude_none=True),
            )
            if result.get("success"):
                logger.info(
                    "NodeHeartbeatSender[%s]: registered (device_type=%s)",
                    self._worker_id,
                    self._device_type,
                )
            return result
        except Exception as exc:
            logger.error(
                "NodeHeartbeatSender[%s]: registration error — %s", self._worker_id, exc
            )
            return {"success": False, "error": str(exc)}

    async def start(self) -> asyncio.Task:
        """Register node and launch the background heartbeat loop.

        Returns the asyncio.Task so callers can await/cancel it.
        """
        await self.register()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name=f"heartbeat-{self._worker_id}")
        return self._task

    async def stop(self) -> None:
        """Cancel the heartbeat loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._send_heartbeat()
            except Exception as exc:
                logger.debug(
                    "NodeHeartbeatSender[%s]: heartbeat error — %s", self._worker_id, exc
                )
            await asyncio.sleep(self._interval_s)

    async def _send_heartbeat(self) -> None:
        from core.nats_bus import nats_bus

        if not nats_bus.is_connected():
            return

        from core.schemas.contracts import WorkerHeartbeatModel, TimestampModel
        from datetime import datetime, timezone

        stats = self._stats_fn() if self._stats_fn else {}

        hb = WorkerHeartbeatModel(
            worker_id=self._worker_id,
            status="idle",
            timestamp=TimestampModel(
                seconds=int(datetime.now(timezone.utc).timestamp())
            ),
            trace_id=self._trace_id,
            cpu_usage_percent=float(stats.get("cpu_usage_percent", 0.0)),
            memory_usage_percent=float(stats.get("memory_usage_percent", 0.0)),
        )
        await nats_bus.publish_heartbeat(hb)
        logger.debug("NodeHeartbeatSender[%s]: heartbeat sent (trace_id=%s)", self._worker_id, self._trace_id)


# ── Convenience function ─────────────────────────────────────────────────────


async def start_node_heartbeat(
    worker_id: str,
    device_type: str = "router",
    capabilities: Optional[List[str]] = None,
    platform_name: str = "",
    worker_version: str = _WORKER_VERSION,
    interval_s: int = _HEARTBEAT_INTERVAL_S,
    stats_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    trace_id: str = "",
) -> asyncio.Task:
    """Create a :class:`NodeHeartbeatSender`, register the node, and start the
    heartbeat loop.  Returns the background :class:`asyncio.Task`.

    Silently no-ops if NATS is not connected, so nodes remain functional.

    Args:
        trace_id: Optional TaskEnvelope trace_id for session correlation.
                  A fresh UUID is generated when not provided.
    """
    # Ensure NATS bus is connected if URL is configured
    try:
        from core.nats_bus import nats_bus

        if not nats_bus.is_connected() and os.getenv("GALAXY_NATS_URL"):
            await nats_bus.connect()
    except Exception as exc:
        logger.debug("start_node_heartbeat: NATS connect attempt failed — %s", exc)

    sender = NodeHeartbeatSender(
        worker_id=worker_id,
        device_type=device_type,
        capabilities=capabilities,
        platform_name=platform_name,
        worker_version=worker_version,
        interval_s=interval_s,
        stats_fn=stats_fn,
        trace_id=trace_id,
    )
    return await sender.start()
