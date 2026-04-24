"""
galaxy_gateway/android/handlers/reconciliation_signal.py

Canonical gateway handler for Android reconciliation signals
(message type ``reconciliation_signal``, introduced in PR-7-V2 / PR-06-Android).

This handler is the **single authoritative entry-point** for inbound
``reconciliation_signal`` messages.  It:

1. Calls :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
   — the participant truth ingress path — so that Android-originated
   reconciliation state is applied to V2 canonical tracking records.
2. Logs the reconciliation outcome at DEBUG level.
3. Returns an ACK response.

Responsibility boundary
-----------------------
``reconciliation_signal`` is an *explicit state reconciliation push* from the
Android RuntimeController; it is **not** a delegated execution lifecycle event.
Its handling MUST NOT duplicate terminal event processing already applied by
``delegated_execution_signal`` (``handle_delegated_execution_signal``).
The participant truth ingress enforces V2 terminal-wins policy, so duplicate
signals for already-terminal records are safely rejected.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-7-V2: participant truth ingress binding
try:
    from core.android_participant_truth_ingress import (
        ingest_android_participant_truth_message as _ingest_participant_truth,
    )
except ImportError:  # pragma: no cover
    _ingest_participant_truth = None  # type: ignore[assignment]


async def handle_reconciliation_signal(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle inbound ``reconciliation_signal`` message.

    Routes the message through the
    :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
    participant truth ingress path so that Android-originated reconciliation
    state is applied to V2 canonical tracking records.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``reconciliation_signal`` message dict.

    Returns
    -------
    dict
        ACK response sent back to the Android runtime.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())

    if _ingest_participant_truth is not None:
        try:
            outcome = _ingest_participant_truth(message)
            if outcome.was_reconciled:
                env = outcome.envelope
                logger.debug(
                    "PR-7-V2 reconciliation signal ingested: truth_kind=%s "
                    "contract_id=%r session_id=%r device_id=%r "
                    "canonical_update=%r → phase=%s",
                    env.truth_kind.value if env else "?",
                    env.contract_id if env else "",
                    env.session_id if env else "",
                    device_id,
                    outcome.canonical_update,
                    outcome.tracking_record_phase,
                )
            elif outcome.reject_reason:
                logger.debug(
                    "PR-7-V2 reconciliation signal skipped: device_id=%s reason=%s",
                    device_id,
                    outcome.reject_reason,
                )
        except Exception as exc:  # pragma: no cover  # noqa: BLE001
            logger.warning(
                "PR-7-V2 reconciliation signal ingestion failed: "
                "device_id=%s exc=%s",
                device_id,
                exc,
            )
    else:  # pragma: no cover
        logger.debug(
            "PR-7-V2 participant truth ingress unavailable (import failed): "
            "device_id=%s",
            device_id,
        )

    return {
        "version": "3.0",
        "type": "reconciliation_signal_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
    }
