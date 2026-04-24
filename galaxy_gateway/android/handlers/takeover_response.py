"""
galaxy_gateway/android/handlers/takeover_response.py

Canonical gateway handler for Android takeover responses
(message type ``takeover_response``).

This handler is the **single authoritative entry-point** for every inbound
Android takeover response message.  Android sends a ``takeover_response``
after the V2 side has issued a ``takeover_request`` downlink.

The payload shape expected from Android::

    {
        "type": "takeover_response",
        "device_id": "<device_id>",
        "message_id": "<uuid>",
        "takeover_id": "<uuid>",          # correlates to the request
        "accepted": true | false,
        "reason": "<optional human-readable string>",
        "session_id": "<optional>",
    }

Processing delegates to the lifecycle coordinator which performs:
1.  Persists the takeover decision to :mod:`core.takeover_tracking`.
2.  Reduces the participant session phase via the transition reducer.
3.  Persists the updated session record.
4.  Records a unified audit event.
5.  Returns a typed ACK back to the Android runtime.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-11-V2: lifecycle coordinator — all tracking, state, and audit logic is
# performed by the coordinator.  This handler extracts wire fields and
# delegates to the coordinator rather than wiring individual modules directly.
try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator as _get_lifecycle_coordinator,
    )
except ImportError:  # pragma: no cover
    _get_lifecycle_coordinator = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

async def handle_takeover_response(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle an inbound Android ``takeover_response`` message.

    Registered for :attr:`~galaxy_gateway.protocol.aip_v3.MessageType.TAKEOVER_RESPONSE`
    in :meth:`~galaxy_gateway.android_bridge.AndroidBridge._register_default_handlers`.

    All lifecycle processing (tracking, session state reduction, audit) is
    performed by the lifecycle coordinator.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``takeover_response`` message dict.

    Returns
    -------
    dict
        ACK response sent back to the Android runtime.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    takeover_id = message.get("takeover_id", "")
    accepted: bool = bool(message.get("accepted", False))
    reason: str = message.get("reason") or ""
    session_id: str = message.get("session_id") or ""

    decision_label = "accepted" if accepted else "rejected"
    logger.info(
        "takeover_response: device=%s takeover_id=%r decision=%s reason=%r",
        device_id,
        takeover_id,
        decision_label,
        reason,
    )

    if _get_lifecycle_coordinator is not None:
        try:
            outcome = _get_lifecycle_coordinator().on_takeover_response(
                session_id=session_id,
                takeover_id=takeover_id,
                device_id=device_id,
                accepted=accepted,
                reason=reason,
                task_id=message.get("task_id") or message.get("payload", {}).get("task_id") or "",
                trace_id=message.get("trace_id") or "",
            )
            logger.debug(
                "takeover_response: coordinator outcome was_handled=%s "
                "phase_before=%r phase_after=%r was_transitioned=%s",
                outcome.was_handled,
                outcome.phase_before,
                outcome.phase_after,
                outcome.was_transitioned,
            )
        except Exception as exc:  # pragma: no cover  # noqa: BLE001
            logger.debug(
                "takeover_response: coordinator call failed (non-fatal): "
                "takeover_id=%r device_id=%s exc=%s",
                takeover_id,
                device_id,
                exc,
            )
    else:  # pragma: no cover
        logger.debug(
            "takeover_response: lifecycle coordinator unavailable "
            "(import failed): takeover_id=%r device_id=%s",
            takeover_id,
            device_id,
        )

    return {
        "version": "3.0",
        "type": "takeover_response_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
        "takeover_id": takeover_id,
        "accepted": accepted,
    }
