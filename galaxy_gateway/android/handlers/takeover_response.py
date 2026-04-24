"""
galaxy_gateway/android/handlers/takeover_response.py

Canonical gateway handler for Android takeover response messages
(message type ``takeover_response``).

This handler is the **single authoritative entry-point** for every inbound
Android takeover response:

- ``accepted = True``   — Android accepted the takeover request
- ``accepted = False``  — Android rejected the takeover request

The handler:

1. Extracts the ``takeover_id`` / ``task_id`` / ``session_id`` correlation keys
   and the ``accepted`` decision from the message payload.
2. Records the accept/reject outcome in the module-level
   :data:`TAKEOVER_RESPONSE_REGISTRY` — a lightweight in-memory tracking store
   that callers can query for the latest decision per ``takeover_id``.
3. Attempts to patch the decision into the UnifiedDeviceManager (UDM) canonical
   state under the key ``"takeover_response"`` so that the decision is visible
   in at least one durable tracking path.
4. Logs the outcome at INFO / WARNING level for observability.
5. Returns a typed ACK response to the Android runtime.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level tracking store — the canonical in-memory accept/reject registry
# ---------------------------------------------------------------------------

#: Maps ``takeover_id`` → latest :class:`TakeoverResponseRecord`.
#: Provides a queryable state surface for callers (flow state, eligibility audit,
#: test assertions) without requiring a persistent backend.
TAKEOVER_RESPONSE_REGISTRY: Dict[str, "TakeoverResponseRecord"] = {}


class TakeoverResponseRecord:
    """Immutable record of a single Android takeover response decision.

    Attributes
    ----------
    takeover_id:
        Correlation key matching the originating ``takeover_request``.
    accepted:
        ``True`` if Android accepted; ``False`` if rejected.
    device_id:
        Originating Android device identifier.
    task_id:
        Propagated from the takeover request.  May be empty.
    session_id:
        Propagated from the takeover request.  May be empty.
    reject_reason:
        Human-readable rejection reason supplied by Android.  Empty for accepts.
    received_at:
        Unix timestamp (seconds) when this record was created.
    raw_message:
        Reference to the raw inbound message for debugging.
    """

    __slots__ = (
        "takeover_id",
        "accepted",
        "device_id",
        "task_id",
        "session_id",
        "reject_reason",
        "received_at",
        "raw_message",
    )

    def __init__(
        self,
        *,
        takeover_id: str,
        accepted: bool,
        device_id: str,
        task_id: str = "",
        session_id: str = "",
        reject_reason: str = "",
        raw_message: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.takeover_id = takeover_id
        self.accepted = accepted
        self.device_id = device_id
        self.task_id = task_id
        self.session_id = session_id
        self.reject_reason = reject_reason
        self.received_at = time.time()
        self.raw_message = raw_message

    def __repr__(self) -> str:  # pragma: no cover
        decision = "accepted" if self.accepted else f"rejected({self.reject_reason!r})"
        return (
            f"TakeoverResponseRecord("
            f"takeover_id={self.takeover_id!r}, "
            f"decision={decision}, "
            f"device_id={self.device_id!r})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_payload_field(message: Dict[str, Any], *keys: str) -> Any:
    """Return the first non-None value found by checking top-level then payload."""
    for key in keys:
        val = message.get(key)
        if val is not None:
            return val
    payload = message.get("payload") or {}
    for key in keys:
        val = payload.get(key)
        if val is not None:
            return val
    return None


def _record_to_udm(device_id: str, record: TakeoverResponseRecord) -> None:
    """Best-effort patch of the takeover decision into UDM canonical state."""
    try:
        from core.unified.device_manager import UnifiedDeviceManager
        UnifiedDeviceManager().upsert_device_state(
            device_id,
            {
                "takeover_response": {
                    "takeover_id": record.takeover_id,
                    "accepted": record.accepted,
                    "reject_reason": record.reject_reason,
                    "task_id": record.task_id,
                    "session_id": record.session_id,
                    "received_at": record.received_at,
                }
            },
            source="android_takeover_response",
        )
    except Exception as exc:  # pragma: no cover
        logger.debug(
            "takeover_response: UDM state patch failed (non-fatal): "
            "device_id=%s takeover_id=%s exc=%s",
            device_id,
            record.takeover_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

async def handle_takeover_response(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle an inbound Android ``takeover_response`` message.

    Registered for the ``takeover_response`` message type in the
    :class:`~galaxy_gateway.android_bridge.AndroidBridge` default handler table.

    The handler:

    1. Extracts ``takeover_id``, ``accepted``, ``task_id``, ``session_id``,
       and optional ``reject_reason`` from the message / payload.
    2. Writes a :class:`TakeoverResponseRecord` to the module-level
       :data:`TAKEOVER_RESPONSE_REGISTRY`.
    3. Best-effort patches the decision into UDM canonical state.
    4. Logs the outcome at INFO (accepted) or WARNING (rejected) level.
    5. Returns an ACK response to the Android runtime.

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
    device_id: str = message.get("device_id") or "unknown"
    message_id: str = message.get("message_id") or str(uuid.uuid4())

    takeover_id: str = str(
        _extract_payload_field(message, "takeover_id") or ""
    )
    task_id: str = str(_extract_payload_field(message, "task_id") or "")
    session_id: str = str(_extract_payload_field(message, "session_id") or "")

    # ``accepted`` may arrive as bool or as 0/1 — normalise to bool.
    raw_accepted = _extract_payload_field(message, "accepted")
    if raw_accepted is None:
        # Default to rejected when the field is absent.
        accepted: bool = False
    else:
        accepted = bool(raw_accepted)

    reject_reason: str = str(
        _extract_payload_field(message, "reject_reason", "reason") or ""
    )
    if accepted:
        reject_reason = ""

    record = TakeoverResponseRecord(
        takeover_id=takeover_id,
        accepted=accepted,
        device_id=device_id,
        task_id=task_id,
        session_id=session_id,
        reject_reason=reject_reason,
        raw_message=message,
    )

    # --- 1. Write to in-memory tracking store ---
    if takeover_id:
        TAKEOVER_RESPONSE_REGISTRY[takeover_id] = record

    # --- 2. Write to UDM canonical state ---
    _record_to_udm(device_id, record)

    # --- 3. Log outcome ---
    if accepted:
        logger.info(
            "takeover_response: ACCEPTED — takeover_id=%r device_id=%s "
            "task_id=%r session_id=%r",
            takeover_id,
            device_id,
            task_id,
            session_id,
        )
    else:
        logger.warning(
            "takeover_response: REJECTED — takeover_id=%r device_id=%s "
            "task_id=%r reason=%r",
            takeover_id,
            device_id,
            task_id,
            reject_reason,
        )

    return {
        "version": "3.0",
        "type": "takeover_response_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
        "payload": {
            "takeover_id": takeover_id,
            "accepted": accepted,
        },
    }
