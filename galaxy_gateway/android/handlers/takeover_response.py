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

# ---------------------------------------------------------------------------
# Direct tracking hook — patchable module-level reference.
# Tests that verify tracking integration patch this symbol directly.
# ---------------------------------------------------------------------------
try:
    from core.takeover_tracking import (
        record_takeover_response as _record_takeover_response,
    )
except ImportError:  # pragma: no cover
    _record_takeover_response = None  # type: ignore[assignment]

try:
    from core.attached_runtime_session_registry import (
        lookup_session_by_device as _lookup_session_by_device,
    )
except ImportError:  # pragma: no cover
    _lookup_session_by_device = None  # type: ignore[assignment]

# PR-11-V2: lifecycle coordinator — session state reduction and audit are
# performed by the coordinator.  Tracking is called directly above so that
# it remains patchable in unit tests.
try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator as _get_lifecycle_coordinator,
    )
except ImportError:  # pragma: no cover
    _get_lifecycle_coordinator = None  # type: ignore[assignment]


def _resolve_session_id_for_takeover_response(
    *,
    device_id: str,
    session_id: str,
) -> str:
    """Resolve canonical runtime session id for takeover responses."""
    if session_id:
        return session_id
    if not device_id or _lookup_session_by_device is None:
        return ""
    try:
        entry = _lookup_session_by_device(device_id)
        if entry is not None and getattr(entry, "runtime_session_id", ""):
            return str(entry.runtime_session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "takeover_response: unable to resolve session_id from registry "
            "(non-fatal) device_id=%s exc=%s",
            device_id,
            exc,
        )
    return ""


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

    Processing order:

    1. Extract wire fields from *message*.
    2. Persist the takeover decision via :func:`~core.takeover_tracking.record_takeover_response`
       (``_record_takeover_response`` — directly patchable for unit tests).
    3. Delegate session-state reduction and audit to the lifecycle coordinator.
    4. Return a typed ACK to the Android runtime.

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
    session_id: str = _resolve_session_id_for_takeover_response(
        device_id=device_id,
        session_id=message.get("session_id") or "",
    )
    task_id: str = message.get("task_id") or message.get("payload", {}).get("task_id") or ""
    trace_id: str = message.get("trace_id") or ""

    decision_label = "accepted" if accepted else "rejected"
    logger.info(
        "takeover_response: device=%s takeover_id=%r decision=%s reason=%r",
        device_id,
        takeover_id,
        decision_label,
        reason,
    )

    # Step 1: persist takeover decision to the canonical tracking store.
    # This call is intentionally made directly (not via the coordinator) so
    # that unit tests can patch ``_record_takeover_response`` in this module
    # and verify tracking behaviour without having to mock the entire
    # coordinator chain.
    if _record_takeover_response is not None:
        try:
            _record_takeover_response(
                takeover_id=takeover_id,
                device_id=device_id,
                accepted=accepted,
                reason=reason,
                session_id=session_id or None,
                task_id=task_id,
                trace_id=trace_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "takeover_response: tracking call failed (non-fatal): "
                "takeover_id=%r device_id=%s exc=%s",
                takeover_id,
                device_id,
                exc,
            )

    # Step 2: delegate session-state reduction and audit to the coordinator.
    if _get_lifecycle_coordinator is not None:
        try:
            outcome = _get_lifecycle_coordinator().on_takeover_response(
                session_id=session_id,
                takeover_id=takeover_id,
                device_id=device_id,
                accepted=accepted,
                reason=reason,
                task_id=task_id,
                trace_id=trace_id,
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
