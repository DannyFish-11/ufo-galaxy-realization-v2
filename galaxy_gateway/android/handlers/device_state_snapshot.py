"""
galaxy_gateway/android/handlers/device_state_snapshot.py
=========================================================
PR-RT: Android Runtime-State Transparency Uplink Handlers.

Handles two Android→V2 uplink message types that carry structured runtime-state
projections from the Android side into the V2 control plane:

DEVICE_STATE_SNAPSHOT (``MessageType.DEVICE_STATE_SNAPSHOT``)
    A periodic snapshot of the complete Android device runtime state, covering:
    * native runtime availability (llamaCpp / NCNN)
    * active inference runtime type
    * model identity, runtime type, checksum
    * readiness state (model_ready, accessibility_ready, overlay_ready)
    * local-loop configuration
    * offline queue depth / replay state
    * fallback ladder tier
    * warmup result / runtime health score

DEVICE_EXECUTION_EVENT (``MessageType.DEVICE_EXECUTION_EVENT``)
    A per-step execution phase event emitted during delegated execution on the
    Android side, carrying: flow_id, task_id, phase, step_index, blocking_state,
    blocking_reason, and timing metadata.

Both handlers delegate immediately to :mod:`core.android_device_state_store`
and return a structured ACK to the Android device.

Authority
---------
These handlers are the **canonical gateway ingress** for Android runtime-state
transparency data.  After this module absorbs the message, the data is
available at:

* ``GET /api/v1/operator/devices/ecosystem`` — multi-device snapshot summary
* ``GET /api/v1/operator/devices/ecosystem/{device_id}`` — per-device snapshot
* ``GET /api/v1/operator/devices/execution-events`` — recent execution events
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_device_state_snapshot(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Handle inbound ``device_state_snapshot`` message (PR-RT).

    Absorbs the Android device runtime-state snapshot into
    :mod:`core.android_device_state_store` and returns a structured ACK.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``device_state_snapshot`` AIP v3 message dict.

    Returns
    -------
    dict
        ACK response dict sent back to the Android device.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    payload = message.get("payload") or {}

    try:
        from core.android_device_state_store import absorb_device_state_snapshot
        snap = absorb_device_state_snapshot(device_id, payload)
        logger.debug(
            "device_state_snapshot absorbed: device_id=%s model_ready=%s "
            "active_runtime=%s fallback_tier=%s",
            device_id,
            snap.model_ready,
            snap.active_runtime_type,
            snap.current_fallback_tier,
        )
    except ImportError:
        logger.error(
            "device_state_snapshot: core.android_device_state_store not available; "
            "snapshot from %s discarded",
            device_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to absorb device_state_snapshot from %s: %s",
            device_id, exc,
        )

    return {
        "type": "device_state_snapshot_ack",
        "device_id": device_id,
        "status": "absorbed",
        "correlation_id": message_id,
    }


async def handle_device_execution_event(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Handle inbound ``device_execution_event`` message (PR-RT).

    Absorbs the Android execution phase event into
    :mod:`core.android_device_state_store` (which also forwards to
    :class:`~core.flow_level_operator_surface.FlowLevelOperatorSurface` when
    the event carries a ``flow_id``) and returns a structured ACK.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``device_execution_event`` AIP v3 message dict.

    Returns
    -------
    dict
        ACK response dict sent back to the Android device.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    payload = message.get("payload") or {}

    try:
        from core.android_device_state_store import absorb_device_execution_event
        evt = absorb_device_execution_event(device_id, payload)
        logger.debug(
            "device_execution_event absorbed: device_id=%s flow=%s phase=%s step=%d",
            device_id,
            evt.flow_id,
            evt.phase,
            evt.step_index,
        )
    except ImportError:
        logger.error(
            "device_execution_event: core.android_device_state_store not available; "
            "event from %s discarded",
            device_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to absorb device_execution_event from %s: %s",
            device_id, exc,
        )

    return {
        "type": "device_execution_event_ack",
        "device_id": device_id,
        "status": "absorbed",
        "correlation_id": message_id,
    }
