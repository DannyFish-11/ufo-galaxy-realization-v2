"""
galaxy_gateway/android/handlers/delegated_signal.py

Canonical gateway handler for Android delegated execution signals
(message type ``delegated_execution_signal``, introduced in PR-16).

This handler is the **single authoritative entry-point** for inbound
``delegated_execution_signal`` messages.  It:

1. Calls :func:`~core.android_delegated_signal_ingress.ingest_delegated_execution_signal`
   — the PR-16 canonical ingress path.
2. Logs the reconciliation outcome at DEBUG level (success or skip).
3. PR-5A: For ``result``-kind signals, forwards the outcome to
   :meth:`~core.runtime.source_dispatch_orchestrator.SourceDispatchOrchestrator.consume_android_behavioral_result`
   — the stable consumer endpoint on the source side.
4. Returns an ACK response.

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

# PR-5A: stable Android behavioral result consumer binding.
try:
    from core.runtime.source_dispatch_orchestrator import (
        SourceDispatchOrchestrator as _SourceDispatchOrchestrator,
    )

    _android_result_consumer = _SourceDispatchOrchestrator()
except Exception:  # pragma: no cover  # noqa: BLE001
    _android_result_consumer = None  # type: ignore[assignment]

# PR-10-V2: unified Android delegated runtime audit recorder.
try:
    from core.android_delegated_runtime_audit import (
        record_delegated_execution_signal as _audit_delegated_signal,
    )
except ImportError:  # pragma: no cover
    _audit_delegated_signal = None  # type: ignore[assignment]


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

    PR-5A: When the ingested signal is a ``result``-kind signal that was
    successfully reconciled, the outcome is forwarded to
    :meth:`~core.runtime.source_dispatch_orchestrator.SourceDispatchOrchestrator.consume_android_behavioral_result`
    so the source-side orchestrator is the stable consumer.

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
                _sk_val = env.signal_kind.value if hasattr(env.signal_kind, "value") else str(env.signal_kind)
                _phase = outcome.record.phase.value if outcome.record and hasattr(outcome.record.phase, "value") else "?"
                logger.debug(
                    "PR-16 delegated signal ingested: signal_kind=%s "
                    "contract_id=%r session_id=%r signal_id=%r emission_seq=%s "
                    "→ phase=%s",
                    _sk_val,
                    env.contract_id,
                    env.session_id,
                    env.signal_id,
                    env.emission_seq,
                    _phase,
                )

                # PR-10-V2: unified audit record.
                if _audit_delegated_signal is not None:
                    try:
                        _audit_delegated_signal(
                            task_id=env.task_id if hasattr(env, "task_id") else "",
                            session_id=env.session_id,
                            trace_id=env.trace_id if hasattr(env, "trace_id") else "",
                            device_id=device_id,
                            contract_id=env.contract_id,
                            signal_kind=_sk_val,
                            signal_id=env.signal_id if hasattr(env, "signal_id") else "",
                            emission_seq=env.emission_seq if hasattr(env, "emission_seq") else None,
                            phase=_phase,
                            was_updated=True,
                        )
                    except Exception as _ae:  # pragma: no cover  # noqa: BLE001
                        logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)

                # PR-5A: Forward result-kind signals to the stable consumer.
                if _android_result_consumer is not None:
                    try:
                        if _sk_val == "result":
                            _android_result_consumer.consume_android_behavioral_result(
                                outcome,
                                source=f"android_bridge:{device_id}",
                            )
                    except Exception as _consumer_exc:  # pragma: no cover  # noqa: BLE001
                        logger.debug(
                            "PR-5A android_result_consumer skipped (non-fatal): %s",
                            _consumer_exc,
                        )

            elif outcome.reject_reason:
                logger.debug(
                    "PR-16 delegated signal skipped: device_id=%s reason=%s",
                    device_id,
                    outcome.reject_reason,
                )
                # PR-10-V2: record rejected signals too so the audit trail is complete.
                if _audit_delegated_signal is not None:
                    try:
                        _env = outcome.envelope
                        _sk_val = _env.signal_kind.value if _env and hasattr(_env.signal_kind, "value") else ""
                        _audit_delegated_signal(
                            task_id=_env.task_id if _env and hasattr(_env, "task_id") else "",
                            session_id=_env.session_id if _env else "",
                            trace_id=_env.trace_id if _env and hasattr(_env, "trace_id") else "",
                            device_id=device_id,
                            contract_id=_env.contract_id if _env else "",
                            signal_kind=_sk_val,
                            was_updated=False,
                            reject_reason=outcome.reject_reason,
                        )
                    except Exception as _ae:  # pragma: no cover  # noqa: BLE001
                        logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)
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
