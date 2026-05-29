"""
galaxy_gateway/android/handlers/takeover_request.py

Canonical gateway handler for Android-originated TAKEOVER_REQUEST messages.

This handler is the **single authoritative entry-point** for every inbound
TAKEOVER_REQUEST from Android.  When an Android device wants to take over
control of the V2 desktop side, it sends this message.

Processing flow:
1. Extract wire fields from the inbound message.
2. Validate the takeover request (device eligibility, session state).
3. Delegate to the lifecycle coordinator for session-state management.
4. Emit AIP v3 TAKEOVER_REQUEST for cross-system observability.
5. Return a typed TAKEOVER_RESPONSE to the Android runtime.

Expected payload from Android::

    {
        "type": "takeover_request",
        "device_id": "<android_device_id>",
        "message_id": "<uuid>",
        "takeover_id": "<uuid>",
        "source_device_id": "<android_device_id>",
        "target_device_id": "v2_desktop",     # or specific device
        "task_context": {...},                # optional: task state to transfer
        "urgency": "normal",                  # normal | high | critical
        "constraints": [...],                 # optional capability constraints
        "session_id": "<optional>",
        "trace_id": "<optional>",
    }
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# Lifecycle coordinator — handles session-state reduction, tracking, and audit.
try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator as _get_lifecycle_coordinator,
    )
except ImportError:  # pragma: no cover
    _get_lifecycle_coordinator = None  # type: ignore[assignment]

# PR-AIPV3: Unified AIP v3 emission for cross-system observability.
try:
    from core.schemas.aip_v3 import TakeoverRequestMsg, TakeoverResponseMsg  # noqa: F401
    from core.nats_bus import get_nats_bus  # noqa: F401
    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_session_id(*, device_id: str, session_id: str) -> str:
    """Resolve canonical runtime session id for takeover requests."""
    if session_id:
        return session_id
    try:
        from core.attached_runtime_session_registry import (
            lookup_session_by_device as _lookup,
        )

        entry = _lookup(device_id)
        if entry is not None:
            return str(getattr(entry, "runtime_session_id", device_id))
    except Exception:
        pass
    return device_id


def _validate_takeover_request(message: Dict[str, Any]) -> tuple[bool, str]:
    """Validate an inbound takeover request.

    Returns ``(is_valid, rejection_reason)``.
    """
    device_id = message.get("device_id", "")
    if not device_id:
        return False, "missing_device_id"

    source_device_id = message.get("source_device_id", "")
    if not source_device_id:
        return False, "missing_source_device_id"

    # Check if source_device is registered in UDM
    try:
        from core.unified.device_manager import get_udm

        udm = get_udm()
        device = udm.get_device(source_device_id)
        if device is None:
            return False, f"source_device {source_device_id} not registered in UDM"
        if getattr(device, "status", "").lower() not in ("online", "active", "busy"):
            return False, f"source_device {source_device_id} status is {getattr(device, 'status', 'unknown')}"
    except Exception as exc:
        logger.debug("takeover_request: UDM validation skipped: %s", exc)

    return True, ""


def _emit_aip_v3_takeover_request(
    device_id: str,
    source_device_id: str,
    target_device_id: str,
    takeover_id: str,
    urgency: str,
    trace_id: str,
    task_context: Dict[str, Any],
) -> None:
    """Emit TAKEOVER_REQUEST AIP v3 message for cross-system observability.

    Best-effort: never raises.
    """
    if not _AIPV3_AVAILABLE:
        return
    try:
        import asyncio

        msg = TakeoverRequestMsg(
            device_id=target_device_id or "v2_desktop",
            source_device_id=source_device_id,
            target_device_id=target_device_id or "v2_desktop",
            urgency=urgency,
            trace_id=trace_id,
            task_context=dict(task_context) if task_context else {},
        )
        nats = get_nats_bus()
        if nats.is_connected():
            asyncio.get_event_loop().create_task(nats.publish_takeover_request(msg))
        else:
            logger.debug("AIPV3 takeover_request: %s", msg.model_dump_json(exclude_none=True))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


async def handle_takeover_request(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle an inbound Android ``takeover_request`` message.

    This is the **canonical entry-point** for Android-originated takeover
    requests.  Android sends this when it wants to take control of the V2
    desktop side (or another device).

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``takeover_request`` message dict.

    Returns
    -------
    dict
        TAKEOVER_RESPONSE sent back to the Android runtime.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    takeover_id = message.get("takeover_id") or f"takr_{uuid.uuid4().hex[:8]}"
    source_device_id = message.get("source_device_id", device_id)
    target_device_id = message.get("target_device_id", "v2_desktop")
    urgency = message.get("urgency", "normal")
    constraints = message.get("constraints", [])
    task_context = message.get("task_context", message.get("payload", {}).get("task_context", {}))
    session_id: str = _resolve_session_id(
        device_id=device_id,
        session_id=message.get("session_id", ""),
    )
    trace_id = message.get("trace_id", "")

    logger.info(
        "takeover_request: from=%s target=%s takeover_id=%s urgency=%s",
        source_device_id,
        target_device_id,
        takeover_id,
        urgency,
    )

    # Step 1: Validate the request
    is_valid, rejection_reason = _validate_takeover_request(message)

    # Step 2: Emit AIP v3 TAKEOVER_REQUEST for cross-system observability
    _emit_aip_v3_takeover_request(
        device_id=device_id,
        source_device_id=source_device_id,
        target_device_id=target_device_id,
        takeover_id=takeover_id,
        urgency=urgency,
        trace_id=trace_id,
        task_context=task_context if isinstance(task_context, dict) else {},
    )

    # Step 3: Delegate to lifecycle coordinator
    coordinator_accepted = is_valid
    coordinator_reason = rejection_reason if not is_valid else ""

    if is_valid and _get_lifecycle_coordinator is not None:
        try:
            outcome = _get_lifecycle_coordinator().on_takeover_requested(
                session_id=session_id,
                takeover_id=takeover_id,
                requesting_device_id=source_device_id,
                target_device_id=target_device_id,
                urgency=urgency,
                constraints=list(constraints) if isinstance(constraints, list) else [],
                task_context=task_context if isinstance(task_context, dict) else {},
                trace_id=trace_id,
            )
            coordinator_accepted = getattr(outcome, "accepted", True)
            coordinator_reason = getattr(outcome, "reason", "")
            logger.debug(
                "takeover_request: coordinator outcome accepted=%s reason=%s",
                coordinator_accepted,
                coordinator_reason,
            )
        except Exception as exc:
            logger.debug(
                "takeover_request: coordinator call failed (non-fatal): %s", exc
            )
            coordinator_reason = f"coordinator_error:{exc}"

    # Step 4: Build and return TAKEOVER_RESPONSE
    accepted = is_valid and coordinator_accepted
    decision_label = "accepted" if accepted else "rejected"
    logger.info(
        "takeover_request: decision=%s takeover_id=%s device=%s reason=%s",
        decision_label,
        takeover_id,
        source_device_id,
        coordinator_reason or rejection_reason,
    )

    return {
        "version": "3.0",
        "type": "takeover_response",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
        "takeover_id": takeover_id,
        "accepted": accepted,
        "reason": coordinator_reason or rejection_reason,
        "timestamp": int(time.time() * 1000),
    }
