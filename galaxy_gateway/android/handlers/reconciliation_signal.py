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

# PR-10-V2: unified Android delegated runtime audit recorder.
try:
    from core.android_delegated_runtime_audit import (
        record_reconciliation_signal as _audit_reconciliation_signal,
    )
except ImportError:  # pragma: no cover
    _audit_reconciliation_signal = None  # type: ignore[assignment]


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
                _truth_kind = env.truth_kind.value if env and hasattr(env.truth_kind, "value") else "?"
                logger.debug(
                    "PR-7-V2 reconciliation signal ingested: truth_kind=%s "
                    "contract_id=%r session_id=%r device_id=%r "
                    "canonical_update=%r → phase=%s",
                    _truth_kind,
                    env.contract_id if env else "",
                    env.session_id if env else "",
                    device_id,
                    outcome.canonical_update,
                    outcome.tracking_record_phase,
                )
                # PR-10-V2: unified audit record.
                if _audit_reconciliation_signal is not None:
                    try:
                        _audit_reconciliation_signal(
                            task_id=env.task_id if env and hasattr(env, "task_id") else "",
                            session_id=env.session_id if env else "",
                            trace_id=env.trace_id if env and hasattr(env, "trace_id") else "",
                            device_id=device_id,
                            contract_id=env.contract_id if env else "",
                            truth_kind=_truth_kind,
                            phase=outcome.tracking_record_phase or "",
                            was_reconciled=True,
                            canonical_update=outcome.canonical_update or "",
                        )
                    except Exception as _ae:  # pragma: no cover  # noqa: BLE001
                        logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)
            elif outcome.reject_reason:
                logger.debug(
                    "PR-7-V2 reconciliation signal skipped: device_id=%s reason=%s",
                    device_id,
                    outcome.reject_reason,
                )
                # PR-10-V2: record rejected signals.
                if _audit_reconciliation_signal is not None:
                    try:
                        _env = outcome.envelope
                        _truth_kind = _env.truth_kind.value if _env and hasattr(_env.truth_kind, "value") else ""
                        _audit_reconciliation_signal(
                            task_id=_env.task_id if _env and hasattr(_env, "task_id") else "",
                            session_id=_env.session_id if _env else "",
                            trace_id=_env.trace_id if _env and hasattr(_env, "trace_id") else "",
                            device_id=device_id,
                            contract_id=_env.contract_id if _env else "",
                            truth_kind=_truth_kind,
                            was_reconciled=False,
                            reject_reason=outcome.reject_reason or "",
                        )
                    except Exception as _ae:  # pragma: no cover  # noqa: BLE001
                        logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)
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
