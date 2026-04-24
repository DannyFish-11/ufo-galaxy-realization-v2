"""
galaxy_gateway/android/handlers/delegated_signal.py

Canonical gateway handler for Android delegated execution signals
(message type ``delegated_execution_signal``, introduced in PR-16).

This handler is the **single authoritative entry-point** for inbound
``delegated_execution_signal`` messages.  It:

1. Delegates all lifecycle processing to the
   :class:`~core.android_delegated_runtime_lifecycle_coordinator.AndroidDelegatedRuntimeLifecycleCoordinator`
   via :func:`~core.android_delegated_runtime_lifecycle_coordinator.get_lifecycle_coordinator`.
2. Logs the reconciliation outcome at DEBUG level (success or skip).
3. Returns an ACK response.

The coordinator handles, in order:
- PR-16: delegated signal ingress and reconciliation.
- Session state reduction.
- PR-5A: For ``result``-kind signals, forwarding to
  :meth:`~core.runtime.source_dispatch_orchestrator.SourceDispatchOrchestrator.consume_android_behavioral_result`
  — the stable consumer endpoint on the source side.

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

# PR-11-V2: lifecycle coordinator — ingress, state reduction, and PR-5A result
# forwarding are all handled by the coordinator.  This handler delegates to it
# rather than wiring individual modules directly.
try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator as _get_lifecycle_coordinator,
    )
except ImportError:  # pragma: no cover
    _get_lifecycle_coordinator = None  # type: ignore[assignment]


async def handle_delegated_execution_signal(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle inbound ``delegated_execution_signal`` message.

    Delegates all lifecycle processing to
    :func:`~core.android_delegated_runtime_lifecycle_coordinator.get_lifecycle_coordinator`
    which invokes the PR-16 ingress path, reduces session state, and — for
    ``result``-kind signals — forwards to the PR-5A stable consumer.

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

    if _get_lifecycle_coordinator is not None:
        try:
            outcome = _get_lifecycle_coordinator().on_execution_signal(
                message=message,
                device_id=device_id,
            )
            if outcome.was_handled:
                logger.debug(
                    "delegated_execution_signal processed via coordinator: %s",
                    outcome.description,
                )
                if outcome.extra.get("result_consumer_called"):
                    logger.debug(
                        "delegated_execution_signal: PR-5A result consumer invoked "
                        "device_id=%s session_id=%r",
                        device_id,
                        outcome.session_id,
                    )
            else:
                logger.debug(
                    "delegated_execution_signal coordinator outcome not handled: "
                    "device_id=%s description=%s",
                    device_id,
                    outcome.description,
                )
        except Exception as exc:  # pragma: no cover  # noqa: BLE001
            logger.debug(
                "delegated_execution_signal coordinator call failed (non-fatal): "
                "device_id=%s exc=%s",
                device_id,
                exc,
            )
    else:  # pragma: no cover
        logger.debug(
            "delegated_execution_signal: lifecycle coordinator unavailable "
            "(import failed): device_id=%s",
            device_id,
        )

    return {
        "version": "3.0",
        "type": "delegated_execution_signal_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
    }
