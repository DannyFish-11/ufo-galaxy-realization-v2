"""
galaxy_gateway/android/handlers/delegated_signal.py

Canonical gateway handler for Android delegated execution signals
(message type ``delegated_execution_signal``, introduced in PR-16).

This handler is the **single authoritative entry-point** for inbound
``delegated_execution_signal`` messages.  It:

1. Calls :func:`~core.android_delegated_signal_ingress.ingest_delegated_execution_signal`
   — the PR-16 canonical ingress path.
2. Logs the reconciliation outcome at DEBUG level (success or skip).
3. Returns an ACK response.

It does **not** fall back to the PR-13 ``reconcile_inbound_message``
compatibility path; that path is only for legacy message types.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-16: canonical ingress binding — top-level import so tests can patch() it
# and so the import failure is handled gracefully.
try:
    from core.android_delegated_signal_ingress import (
        ingest_delegated_execution_signal as _ingest_delegated_signal,
    )
except ImportError:  # pragma: no cover
    _ingest_delegated_signal = None  # type: ignore[assignment]


async def handle_delegated_execution_signal(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle inbound ``delegated_execution_signal`` message.

    This is the canonical gateway handler for Android delegated execution
    lifecycle signals.  It routes the message through the PR-16
    :func:`~core.android_delegated_signal_ingress.ingest_delegated_execution_signal`
    ingress path and returns an ACK response.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``delegated_execution_signal`` message dict.

    Returns
    -------
    dict
        ACK response sent back to the Android runtime.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())

    if _ingest_delegated_signal is not None:
        try:
            outcome = _ingest_delegated_signal(message)
            if outcome.was_updated:
                env = outcome.envelope
                logger.debug(
                    "PR-16 delegated signal ingested: signal_kind=%s "
                    "contract_id=%r session_id=%r signal_id=%r emission_seq=%s "
                    "→ phase=%s",
                    env.signal_kind.value,
                    env.contract_id,
                    env.session_id,
                    env.signal_id,
                    env.emission_seq,
                    outcome.record.phase.value if outcome.record else "?",
                )
            elif outcome.reject_reason:
                logger.debug(
                    "PR-16 delegated signal skipped: device_id=%s reason=%s",
                    device_id,
                    outcome.reject_reason,
                )
        except Exception as exc:  # pragma: no cover
            logger.debug(
                "PR-16 delegated signal ingestion failed (non-fatal): device_id=%s exc=%s",
                device_id,
                exc,
            )
    else:  # pragma: no cover
        logger.debug(
            "PR-16 delegated signal ingress unavailable (import failed): device_id=%s",
            device_id,
        )

    return {
        "version": "3.0",
        "type": "delegated_execution_signal_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
    }
