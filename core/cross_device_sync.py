"""
core/cross_device_sync.py
=========================
PR-CROSS-DEVICE-SYNC: Cross-Device State Synchronization.

When DesktopPresenceRuntime tristate changes (SILENT→LIMINAL→MANIFEST),
this module actively pushes AIP v3 STATE_EVENT messages to all connected
Android devices via WebSocket.

This is NOT request-response. It is proactive broadcast.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CrossDeviceSync")

# PR-AIPV3
try:
    from core.schemas.aip_v3 import StateEventMsg  # noqa: F401
    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False


def emit_cross_device_phase_sync(
    old_phase: str,
    new_phase: str,
    session_id: str,
    source: str = "desktop_presence_runtime",
    trace_id: str = "",
) -> None:
    """Fire-and-forget: push phase change to all connected Android devices.

    Called synchronously from RuntimeSession.advance().
    Uses asyncio.create_task so it never blocks the caller.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _async_push_phase_to_all_devices(
                old_phase=old_phase,
                new_phase=new_phase,
                session_id=session_id,
                source=source,
                trace_id=trace_id,
            )
        )
    except RuntimeError:
        # No running loop — log and skip
        logger.debug("CrossDeviceSync: no event loop, skipping push")


async def _async_push_phase_to_all_devices(
    old_phase: str,
    new_phase: str,
    session_id: str,
    source: str,
    trace_id: str,
) -> None:
    """Async: push phase change to all connected Android devices."""
    try:
        from galaxy_gateway.android_bridge import (  # noqa: PLC0415
            android_bridge as _bridge,
        )

        # Build AIP v3 STATE_EVENT message
        msg: Dict[str, Any] = {
            "type": "state_event",
            "event_category": "phase",
            "event_action": new_phase,
            "device_id": "v2_desktop",
            "timestamp": int(time.time() * 1000),
            "session_id": session_id,
            "trace_id": trace_id or session_id,
            "_aip_version": "3.0",
            # Detailed payload
            "payload": {
                "from_phase": old_phase,
                "to_phase": new_phase,
                "source": source,
                "sync_type": "cross_device_broadcast",
            },
            # Legacy backward-compatible fields
            "phase": new_phase,
        }

        # Send to all connected devices
        sent = 0
        skipped = 0
        for device_id, device in _bridge._devices.items():
            if device.websocket is not None and getattr(device, "connected", False):
                try:
                    await device.websocket.send_json(msg)
                    sent += 1
                except Exception as exc:
                    logger.debug(
                        "CrossDeviceSync: failed to push to %s: %s", device_id, exc
                    )
            else:
                skipped += 1

        if sent:
            logger.info(
                "CrossDeviceSync: phase %s→%s pushed to %d device(s) (%d offline)",
                old_phase,
                new_phase,
                sent,
                skipped,
            )

    except Exception as exc:
        logger.debug("CrossDeviceSync: push failed (non-fatal): %s", exc)


async def push_task_state_to_device(
    device_id: str,
    task_status: str,
    task_result: Optional[str] = None,
    task_error: Optional[str] = None,
    session_id: str = "",
    trace_id: str = "",
) -> bool:
    """Push task state update to a specific Android device.

    Used by OpenClawd execution chain to notify Android of task progress.
    """
    try:
        from galaxy_gateway.android_bridge import (  # noqa: PLC0415
            android_bridge as _bridge,
        )

        device = _bridge._devices.get(device_id)
        if device is None or device.websocket is None:
            return False

        msg: Dict[str, Any] = {
            "type": "state_event",
            "event_category": "task",
            "event_action": task_status,
            "device_id": "v2_desktop",
            "timestamp": int(time.time() * 1000),
            "session_id": session_id,
            "trace_id": trace_id,
            "_aip_version": "3.0",
            "payload": {
                "task_status": task_status,
                "task_result": task_result,
                "task_error": task_error,
            },
        }

        await device.websocket.send_json(msg)
        return True

    except Exception as exc:
        logger.debug("CrossDeviceSync: task push to %s failed: %s", device_id, exc)
        return False
