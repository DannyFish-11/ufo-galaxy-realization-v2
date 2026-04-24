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

Processing:
1.  Extracts ``takeover_id`` and ``accepted`` from the message.
2.  Updates the takeover tracking state (via
    :func:`~core.takeover_tracking.record_takeover_response` when available).
3.  Logs the accept/reject decision at DEBUG/INFO level.
4.  Returns a typed ACK back to the Android runtime.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tracking integration — optional; degrades gracefully when unavailable.
#
# ``core.takeover_tracking`` is the intended future integration point for
# recording takeover accept/reject decisions into a persistent tracking state.
# The module does not yet exist in the codebase; the try/except block ensures
# the handler degrades gracefully until it is implemented.  When the module is
# available it is expected to expose::
#
#     def record_takeover_response(
#         *,
#         takeover_id: str,
#         device_id: str,
#         accepted: bool,
#         reason: str,
#         session_id: Optional[str],
#     ) -> None: ...
# ---------------------------------------------------------------------------

try:
    from core.takeover_tracking import record_takeover_response as _record_takeover_response
except ImportError:  # pragma: no cover
    _record_takeover_response = None  # type: ignore[assignment]

# PR-10-V2: unified Android delegated runtime audit recorder.
try:
    from core.android_delegated_runtime_audit import (
        record_takeover_response as _audit_takeover_response,
    )
except ImportError:  # pragma: no cover
    _audit_takeover_response = None  # type: ignore[assignment]


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

    # PR-10-V2: unified audit record.
    if _audit_takeover_response is not None:
        try:
            _audit_takeover_response(
                task_id=message.get("task_id") or message.get("payload", {}).get("task_id") or "",
                session_id=session_id,
                trace_id=message.get("trace_id") or "",
                device_id=device_id,
                takeover_id=takeover_id,
                accepted=accepted,
                reason=reason,
            )
        except Exception as _ae:  # pragma: no cover  # noqa: BLE001
            logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)

    # Feed into tracking state when the integration module is available.
    if _record_takeover_response is not None:
        try:
            _record_takeover_response(
                takeover_id=takeover_id,
                device_id=device_id,
                accepted=accepted,
                reason=reason,
                session_id=session_id or None,
            )
            logger.debug(
                "takeover_response: tracking updated takeover_id=%r accepted=%s",
                takeover_id,
                accepted,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug(
                "takeover_response: tracking update failed (non-fatal): "
                "takeover_id=%r device_id=%s exc=%s",
                takeover_id,
                device_id,
                exc,
            )
    else:  # pragma: no cover
        logger.debug(
            "takeover_response: tracking unavailable (import failed): "
            "takeover_id=%r device_id=%s",
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
