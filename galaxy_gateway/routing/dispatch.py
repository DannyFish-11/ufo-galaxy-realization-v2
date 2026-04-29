"""galaxy_gateway/routing/dispatch.py — Dispatch execution mechanics.

This module owns the mechanics of *sending* a command or task payload to a
device via its active transport session (WebSocket).  It is intentionally
separate from device *selection* (choosing which device) and routing *policy*
(analysing what the command needs).

Separation of concerns
-----------------------
- ``build_aip_message`` — construct an AIP v3 command message envelope.
- ``dispatch_to_websocket`` — send a pre-built message and await the result
  event, handling timeouts and lifecycle registry integration.

These helpers are extracted from ``DeviceRouter.send_command_to_device``.
``DeviceRouter`` continues to expose the same public API; it now delegates
the message-building and send/wait steps here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

DISPATCH_AUTHORITY = "galaxy_gateway.routing.dispatch"
"""Sentinel string identifying this module as the dispatch-mechanics authority."""


# ---------------------------------------------------------------------------
# AIP v3 message construction
# ---------------------------------------------------------------------------


def build_aip_message(
    device_id: str,
    task_id: str,
    trace_id: str,
    command: str,
    payload: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an AIP v3 command message envelope ready for WebSocket dispatch.

    All device-targeted messages sent by the routing layer must conform to
    AIP v3 format.  This function is the single place where that envelope is
    assembled, ensuring consistency across all dispatch paths.

    Args:
        device_id:  Target device identifier.
        task_id:    Task identifier (for tracing and result correlation).
        trace_id:   Distributed trace identifier.
        command:    Command name / action label.
        payload:    Optional additional parameters merged into the payload.
        message_id: Optional explicit message ID; a new UUID is generated when
                    omitted.

    Returns:
        Dict conforming to AIP v3 message schema with keys:
        ``version``, ``message_id``, ``type``, ``device_id``, ``task_id``,
        ``trace_id``, ``timestamp``, ``payload``.
    """
    return {
        "version": "3.0",
        "message_id": message_id or str(uuid.uuid4()),
        "type": "command",
        "device_id": device_id,
        "task_id": task_id,
        "trace_id": trace_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "payload": {
            "command": command,
            **(payload or {}),
        },
    }


# ---------------------------------------------------------------------------
# WebSocket send + result-event wait
# ---------------------------------------------------------------------------


async def dispatch_to_websocket(
    device: Any,
    message: Dict[str, Any],
    task_id: str,
    task_events: Dict[str, asyncio.Event],
    task_results: Dict[str, Dict],
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Send *message* via *device*'s WebSocket and wait for a result event.

    This function covers the terminal send-and-wait step that was previously
    inlined inside ``DeviceRouter.send_command_to_device``.  It:

    1. Sends the serialised *message* via ``device.websocket.send``.
    2. Registers the task with the canonical lifecycle registry (if available).
    3. Waits for the corresponding ``asyncio.Event`` to be set by the result
       handler, up to *timeout* seconds.
    4. Returns the result dict or a structured error response.

    Args:
        device:      Device object with a live ``websocket`` attribute.
        message:     Pre-built AIP v3 message dict (from ``build_aip_message``).
        task_id:     Task identifier used to correlate the result event.
        task_events: Shared mapping of ``task_id → asyncio.Event`` maintained
                     by ``DeviceRouter``.
        task_results: Shared mapping of ``task_id → result dict`` maintained
                      by ``DeviceRouter``.
        timeout:     Seconds to wait for the result before declaring a timeout.

    Returns:
        Result dict on success, or ``{"success": False, "error": ...}`` on
        send failure or timeout.  Successful results always carry ``"via":
        "device_router"``.
    """
    trace_id = message.get("trace_id", "")
    device_id = message.get("device_id", getattr(device, "device_id", ""))

    # ── Send ─────────────────────────────────────────────────────────────────
    try:
        await device.websocket.send(json.dumps(message))
        logger.debug(
            "dispatch_to_websocket sent | device=%s task_id=%s trace_id=%s",
            device_id,
            task_id,
            trace_id,
        )
    except Exception as _send_exc:
        logger.warning(
            "dispatch_to_websocket send failed | device=%s error=%s",
            device_id,
            _send_exc,
        )
        return {
            "success": False,
            "result": None,
            "error": str(_send_exc),
            "task_id": task_id,
            "trace_id": trace_id,
            "via": "device_router",
        }

    # ── Register with lifecycle registry (best-effort) ───────────────────────
    try:
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry as _get_lcr,
            LifecycleOwner as _LCOwner,
        )

        class _EnvProxy:
            task_id: str
            trace_id: str
            target: str
            tool_name: str
            timeout: float

        _ep = _EnvProxy()
        _ep.task_id = task_id
        _ep.trace_id = trace_id
        _ep.target = device_id
        _ep.tool_name = (message.get("payload") or {}).get("command", "")
        _ep.timeout = timeout
        _get_lcr().register(
            _ep,
            owner=_LCOwner.DEVICE_DISPATCH,
            metadata={"source": "routing.dispatch.dispatch_to_websocket"},
        )
    except Exception as _lcr_err:
        logger.debug(
            "dispatch_to_websocket: lifecycle registry register skipped — %s",
            _lcr_err,
        )

    # ── Wait for result event ─────────────────────────────────────────────────
    event = asyncio.Event()
    task_events[task_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        if task_id in task_results:
            result = task_results.pop(task_id)
            result.setdefault("via", "device_router")
            result.setdefault("trace_id", trace_id)
            try:
                from core.task_envelope_lifecycle_registry import (
                    get_lifecycle_registry as _get_lcr2,
                )

                _get_lcr2().complete(task_id, result)
            except Exception:
                pass
            return result
        # Event was set but no result stored — treat as acknowledged success.
        return {
            "success": True,
            "result": f"command sent to {device_id}",
            "task_id": task_id,
            "trace_id": trace_id,
            "via": "device_router",
        }
    except asyncio.TimeoutError:
        logger.warning(
            "dispatch_to_websocket timeout | device=%s task_id=%s",
            device_id,
            task_id,
        )
        try:
            from core.task_envelope_lifecycle_registry import (
                get_lifecycle_registry as _get_lcr3,
            )

            _get_lcr3().fail(task_id, "dispatch_to_websocket timeout")
        except Exception:
            pass
        return {
            "success": False,
            "result": None,
            "error": "timeout",
            "task_id": task_id,
            "trace_id": trace_id,
            "via": "device_router",
        }
    finally:
        task_events.pop(task_id, None)
