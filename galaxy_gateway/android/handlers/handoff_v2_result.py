"""
galaxy_gateway/android/handlers/handoff_v2_result.py

PR-02-V2: Canonical gateway handler for Android HandoffEnvelopeV2 uplink responses.

This handler is the **single authoritative entry-point** for every inbound
Android handoff v2 response message:

- ``handoff_ack``              — receipt confirmed; execution starting
- ``handoff_result``           — execution completed successfully
- ``handoff_failure``          — execution failed; error detail supplied
- ``handoff_envelope_v2_result`` — future unified uplink wire type

Without this handler the response messages fell into the ``handle_unregistered``
catch-all and the handoff chain had no uplink — V2 dispatched but never learned
the outcome.

This module closes the gap by wiring the three uplink message types to:

1. :func:`~core.android_handoff_v2_response_ingress.ingest_android_handoff_response`
   — correlates the response to the originating dispatch via handoff_id / task_id /
   session_id, resolves any waiting Future, invokes the registered callback, and
   advances the binding / tracking / delegated flow state.
2. **PR-1 P0 Completion Closure**: For terminal responses (result / failure), calls
   :meth:`~galaxy_gateway.device_router.DeviceRouter.handle_task_result` to set
   ``task_events[task_id]``, waking any ``dispatch_to_websocket`` awaiter.  This
   ensures that cross-device handoff completions drive orchestration continuation
   rather than relying on a 30-second timeout.
3. Logs the outcome at DEBUG / WARNING level.
4. Returns a typed ACK response to the Android runtime.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-02-V2: canonical ingress binding — top-level import so tests can patch() it
# and so an import failure degrades gracefully without crashing the gateway.
try:
    from core.android_handoff_v2_response_ingress import (
        ingest_android_handoff_response as _ingest_handoff_response,
    )
except ImportError:  # pragma: no cover
    _ingest_handoff_response = None  # type: ignore[assignment]

# PR-10-V2: unified Android delegated runtime audit recorder.
try:
    from core.android_delegated_runtime_audit import (
        record_handoff_v2_result as _audit_handoff_v2_result,
    )
except ImportError:  # pragma: no cover
    _audit_handoff_v2_result = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

async def handle_handoff_v2_result(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle an inbound Android HandoffEnvelopeV2 uplink response.

    Registered for ``handoff_ack``, ``handoff_result``, ``handoff_failure``,
    and ``handoff_envelope_v2_result`` message types in the
    :class:`~galaxy_gateway.android_bridge.AndroidBridge` default handler table.

    The handler delegates all processing to
    :func:`~core.android_handoff_v2_response_ingress.ingest_android_handoff_response`
    which:

    - Extracts a typed
      :class:`~contracts.android_handoff_response.AndroidHandoffResponseEnvelope`.
    - Correlates the response to the originating dispatch via ``handoff_id``
      (preferred), ``task_id`` (fallback), or ``session_id`` (last resort).
    - For **terminal** responses (result / failure / timeout / cancelled):
      resolves and removes the pending registry entry, invokes the callback.
    - For **ack** responses: resolves the pending registry entry without
      removing it (a terminal response is still expected).
    - Returns a :class:`~core.android_handoff_v2_response_ingress.HandoffV2ResponseOutcome`.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound message dict for the handoff response.

    Returns
    -------
    dict
        ACK response sent back to the Android runtime.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    msg_type = message.get("type", "unknown")

    if _ingest_handoff_response is not None:
        try:
            outcome = _ingest_handoff_response(message)
            if outcome.was_correlated:
                env = outcome.envelope
                logger.debug(
                    "PR-02-V2 handoff_v2 ingress: correlated kind=%s "
                    "handoff_id=%r device=%s callback_invoked=%s",
                    env.response_kind,
                    env.handoff_id,
                    device_id,
                    outcome.callback_invoked,
                )
                # PR-1 P0 Completion Closure: for terminal responses (result /
                # failure / timeout / cancelled), wake the dispatch_to_websocket
                # awaiter by calling DeviceRouter.handle_task_result().  Without
                # this call the awaiter blocked on task_events[task_id].wait()
                # would only complete via a 30-second timeout — never via real
                # completion.
                _env_task_id = env.task_id if hasattr(env, "task_id") else ""
                _is_terminal = getattr(env, "is_terminal", False)
                if _env_task_id and _is_terminal:
                    try:
                        from galaxy_gateway.device_router import (
                            device_router as _device_router,
                        )

                        _completion_result = {
                            "success": str(getattr(env, "response_kind", "")).endswith("result"),
                            "result": message.get("payload") or message.get("result"),
                            "task_id": _env_task_id,
                            "handoff_id": env.handoff_id if hasattr(env, "handoff_id") else "",
                            "device_id": device_id,
                            "response_kind": str(getattr(env, "response_kind", "")),
                            "via": "handoff_v2_result",
                        }
                        await _device_router.handle_task_result(_env_task_id, _completion_result)
                        logger.debug(
                            "PR-1 P0: handoff_v2 terminal → device_router.handle_task_result "
                            "task_id=%r kind=%s",
                            _env_task_id,
                            getattr(env, "response_kind", ""),
                        )
                    except Exception as _dr_exc:
                        logger.debug(
                            "PR-1 P0: device_router.handle_task_result skipped "
                            "(non-fatal): task_id=%r exc=%s",
                            _env_task_id,
                            _dr_exc,
                        )
                # PR-10-V2: unified audit record.
                if _audit_handoff_v2_result is not None:
                    try:
                        _audit_handoff_v2_result(
                            task_id=env.task_id if hasattr(env, "task_id") else "",
                            session_id=env.session_id if hasattr(env, "session_id") else "",
                            trace_id=env.trace_id if hasattr(env, "trace_id") else "",
                            device_id=device_id,
                            handoff_id=env.handoff_id if hasattr(env, "handoff_id") else "",
                            response_kind=str(env.response_kind),
                            was_correlated=True,
                            callback_invoked=outcome.callback_invoked,
                        )
                    except Exception as _ae:  # pragma: no cover  # noqa: BLE001
                        logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)
            else:
                logger.warning(
                    "PR-02-V2 handoff_v2 ingress miss: device=%s type=%s reason=%s",
                    device_id,
                    msg_type,
                    outcome.reject_reason,
                )
                # PR-10-V2: record correlation misses so missing responses are traceable.
                if _audit_handoff_v2_result is not None:
                    try:
                        _env = outcome.envelope
                        _audit_handoff_v2_result(
                            task_id=_env.task_id if _env and hasattr(_env, "task_id") else "",
                            session_id=_env.session_id if _env and hasattr(_env, "session_id") else "",
                            trace_id=_env.trace_id if _env and hasattr(_env, "trace_id") else "",
                            device_id=device_id,
                            handoff_id=_env.handoff_id if _env and hasattr(_env, "handoff_id") else "",
                            response_kind=str(_env.response_kind) if _env and hasattr(_env, "response_kind") else "",
                            was_correlated=False,
                            reject_reason=outcome.reject_reason or "",
                        )
                    except Exception as _ae:  # pragma: no cover  # noqa: BLE001
                        logger.debug("PR-10-V2 audit skip (non-fatal): %s", _ae)
        except Exception as exc:  # pragma: no cover
            logger.debug(
                "PR-02-V2 handoff_v2 ingestion failed (non-fatal): "
                "device_id=%s type=%s exc=%s",
                device_id,
                msg_type,
                exc,
            )
    else:  # pragma: no cover
        logger.warning(
            "PR-02-V2 handoff_v2 ingress unavailable (import failed): "
            "device_id=%s type=%s",
            device_id,
            msg_type,
        )

    return {
        "version": "3.0",
        "type": "handoff_v2_result_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
    }
