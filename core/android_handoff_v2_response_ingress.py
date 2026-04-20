"""core/android_handoff_v2_response_ingress.py
================================================
PR-H (V2 配套): V2-Side Ingress Handler for Android HandoffEnvelopeV2 Responses.

Background
----------
PR-31 introduced :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` as
the canonical handoff envelope.  PR-H extends the protocol to support
**Android native consumption**: V2 dispatches a ``handoff_dispatch`` AIP
message carrying the full V2 envelope, and Android replies with one of:

- ``handoff_ack``     — receipt confirmed; execution starting
- ``handoff_result``  — execution completed successfully
- ``handoff_failure`` — execution failed; error detail supplied

Without a dedicated V2-side ingress handler, these response messages flow
into the gateway unrecognised and V2 remains in a "black hole" state —
it dispatched the handoff but never learns the outcome.

This module closes that gap by providing:

1. :class:`~core.android_handoff_v2_response_ingress.HandoffV2ResponseRuntime` —
   injectable runtime that holds the in-process pending-response registry.
   Allows tests and production code to wire up the same ingress path with
   different backing stores.

2. :func:`extract_handoff_response_envelope` (re-exported) — delegates to
   :func:`~contracts.android_handoff_response.extract_handoff_response_envelope`
   so callers need only import from this module.

3. :func:`ingest_android_handoff_response` — canonical ingress entry-point:
   a. Extracts a typed :class:`~contracts.android_handoff_response.AndroidHandoffResponseEnvelope`.
   b. Correlates the response to the originating dispatch via ``handoff_id``
      (preferred), ``task_id`` (fallback), or ``session_id`` (last resort).
   c. Resolves the waiting Future (if any) and sets its result / exception.
   d. Returns an :class:`HandoffV2ResponseOutcome` with the correlated envelope
      and disposition.

4. :class:`HandoffV2ResponseOutcome` — typed result of an ingestion attempt.

Ten policy sentinels documenting canonical ingress rules.

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Single canonical ingress path** — all Android handoff v2 responses flow
  through :func:`ingest_android_handoff_response`.
- **Identity-preserving** — ``handoff_id``, ``trace_id``, ``task_id``,
  ``session_id``, and ``device_id`` are carried verbatim from the response.
- **Non-destructive on miss** — if no matching pending dispatch is found the
  outcome carries ``was_correlated=False`` and a descriptive reject reason;
  no phantom state is created.
- **Thread-safe registry** — the default singleton registry is protected by
  a threading lock; async callers may supply an alternate runtime.

Public API
----------
Dataclass::

    HandoffV2ResponseOutcome

Class::

    HandoffV2ResponseRuntime

Functions::

    extract_handoff_response_envelope(message) → AndroidHandoffResponseEnvelope
    ingest_android_handoff_response(message, *, runtime=None) → HandoffV2ResponseOutcome
    get_handoff_v2_response_runtime() → HandoffV2ResponseRuntime
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from contracts.android_handoff_response import (
    AndroidHandoffResponseEnvelope,
    HandoffResponseKind,
    extract_handoff_response_envelope,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ANDROID_HANDOFF_V2_RESPONSE_INGRESS_PR_H_SENTINEL: str = (
    "ANDROID_HANDOFF_V2_RESPONSE_INGRESS_PR_H::"
    "core.android_handoff_v2_response_ingress::"
    "pr-h-v2-companion::android-handoff-response-ingress::"
    "ack-result-failure-round-trip-closure"
)

HANDOFF_ID_CORRELATION_IS_PRIMARY_POLICY: str = (
    "POLICY::HANDOFF_ID_CORRELATION_IS_PRIMARY: "
    "V2 ingress MUST attempt to correlate by handoff_id first.  "
    "Fallback to task_id, then session_id, only when handoff_id is absent."
)

SINGLE_INGRESS_PATH_POLICY: str = (
    "POLICY::SINGLE_INGRESS_PATH: "
    "All Android handoff v2 response messages (handoff_ack, handoff_result, "
    "handoff_failure) MUST be processed through ingest_android_handoff_response.  "
    "No other path may correlate these messages to dispatch state."
)

NON_DESTRUCTIVE_ON_MISS_POLICY: str = (
    "POLICY::NON_DESTRUCTIVE_ON_MISS: "
    "If no matching pending dispatch is found for an inbound response, "
    "the ingress MUST return was_correlated=False with a descriptive "
    "reject_reason.  It MUST NOT create a phantom pending entry."
)

TERMINAL_RESPONSE_CLEARS_PENDING_POLICY: str = (
    "POLICY::TERMINAL_RESPONSE_CLEARS_PENDING: "
    "When a terminal response (result / failure / timeout / cancelled) is "
    "ingested and a matching pending callback is found, it MUST be cleared "
    "from the registry so subsequent duplicate messages are treated as misses."
)

ACK_DOES_NOT_CLEAR_PENDING_POLICY: str = (
    "POLICY::ACK_DOES_NOT_CLEAR_PENDING: "
    "An ack response is a receipt confirmation only.  "
    "It MUST NOT clear the pending callback registry entry; "
    "the entry must persist until a terminal response arrives."
)

UNKNOWN_KIND_IS_LOGGED_NOT_REJECTED_POLICY: str = (
    "POLICY::UNKNOWN_KIND_IS_LOGGED_NOT_REJECTED: "
    "A response with response_kind=unknown is logged at WARNING level but "
    "not hard-rejected.  The outcome carries was_correlated=False so callers "
    "can apply their own fallback logic."
)

INGRESS_IS_EXCEPTION_SAFE_POLICY: str = (
    "POLICY::INGRESS_IS_EXCEPTION_SAFE: "
    "ingest_android_handoff_response MUST NOT propagate exceptions to the "
    "caller.  All internal errors are caught, logged at ERROR level, and "
    "surfaced in HandoffV2ResponseOutcome.reject_reason."
)

RESPONSE_ENVELOPE_IS_ALWAYS_RETURNED_POLICY: str = (
    "POLICY::RESPONSE_ENVELOPE_IS_ALWAYS_RETURNED: "
    "HandoffV2ResponseOutcome.envelope is always populated (never None) so "
    "callers can always inspect the extracted response regardless of whether "
    "correlation succeeded."
)

HANDOFF_V2_RESPONSE_INGRESS_IS_ADDITIVE_POLICY: str = (
    "POLICY::HANDOFF_V2_RESPONSE_INGRESS_IS_ADDITIVE: "
    "This module does not modify any prior module.  It adds a new ingress "
    "path that sits alongside the existing delegated_execution_signal path."
)


# ---------------------------------------------------------------------------
# HandoffV2ResponseRuntime
# ---------------------------------------------------------------------------


class HandoffV2ResponseRuntime:
    """Injectable runtime backing store for the handoff v2 response ingress.

    Holds two registries:
    - ``pending_by_handoff_id`` — maps ``handoff_id`` → callback
    - ``pending_by_task_id``    — maps ``task_id`` → callback (fallback)

    A *callback* is any callable that accepts an
    :class:`~contracts.android_handoff_response.AndroidHandoffResponseEnvelope`
    and returns nothing.  In production this is typically a function that
    resolves an ``asyncio.Future``; in tests it can be a simple lambda.

    Thread safety
    -------------
    All mutations are protected by a :class:`threading.Lock`.  This is
    compatible with both synchronous callers and ``asyncio``-based callers
    (the lock is never held across an ``await``).
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self.pending_by_handoff_id: Dict[str, Callable[[AndroidHandoffResponseEnvelope], None]] = {}
        self.pending_by_task_id: Dict[str, Callable[[AndroidHandoffResponseEnvelope], None]] = {}

    def register(
        self,
        handoff_id: str,
        callback: Callable[[AndroidHandoffResponseEnvelope], None],
        *,
        task_id: Optional[str] = None,
    ) -> None:
        """Register a pending dispatch and its result callback.

        Parameters
        ----------
        handoff_id:
            The ``handoff_id`` of the dispatched HandoffEnvelopeV2.
        callback:
            Callable invoked when a terminal response for this dispatch arrives.
        task_id:
            Optional fallback correlation key.
        """
        with self._lock:
            if handoff_id:
                self.pending_by_handoff_id[handoff_id] = callback
            if task_id:
                self.pending_by_task_id[task_id] = callback

    def resolve(
        self,
        envelope: AndroidHandoffResponseEnvelope,
        *,
        clear: bool = True,
    ) -> Optional[Callable[[AndroidHandoffResponseEnvelope], None]]:
        """Resolve a pending callback for the given response envelope.

        Tries ``handoff_id`` first, then ``task_id``.  When *clear* is True
        (default for terminal responses) the matched entry is removed from the
        registry.

        Returns the matched callback or None if no match was found.
        """
        with self._lock:
            cb: Optional[Callable[[AndroidHandoffResponseEnvelope], None]] = None
            key_used: str = ""

            if envelope.handoff_id:
                cb = self.pending_by_handoff_id.get(envelope.handoff_id)
                if cb is not None:
                    key_used = f"handoff_id={envelope.handoff_id!r}"
                    if clear:
                        self.pending_by_handoff_id.pop(envelope.handoff_id, None)

            if cb is None and envelope.task_id:
                cb = self.pending_by_task_id.get(envelope.task_id)
                if cb is not None:
                    key_used = f"task_id={envelope.task_id!r}"
                    if clear:
                        self.pending_by_task_id.pop(envelope.task_id, None)

            if cb is not None:
                logger.debug(
                    "handoff_v2 response resolved: key=%s kind=%s device=%s",
                    key_used,
                    envelope.response_kind,
                    envelope.device_id,
                )
            return cb


# ---------------------------------------------------------------------------
# Singleton runtime (overridable in tests)
# ---------------------------------------------------------------------------

_runtime_singleton: Optional[HandoffV2ResponseRuntime] = None
_runtime_singleton_lock: threading.Lock = threading.Lock()


def get_handoff_v2_response_runtime() -> HandoffV2ResponseRuntime:
    """Return the process-level singleton :class:`HandoffV2ResponseRuntime`.

    Creates the singleton on first call (thread-safe).  Tests that need
    isolation should construct a fresh :class:`HandoffV2ResponseRuntime` and
    pass it directly to :func:`ingest_android_handoff_response`.
    """
    global _runtime_singleton
    if _runtime_singleton is None:
        with _runtime_singleton_lock:
            if _runtime_singleton is None:
                _runtime_singleton = HandoffV2ResponseRuntime()
    return _runtime_singleton


# ---------------------------------------------------------------------------
# HandoffV2ResponseOutcome
# ---------------------------------------------------------------------------


@dataclass
class HandoffV2ResponseOutcome:
    """Typed result of an :func:`ingest_android_handoff_response` call.

    Attributes
    ----------
    envelope:
        The extracted :class:`~contracts.android_handoff_response.AndroidHandoffResponseEnvelope`.
        Always present; never None.
    was_correlated:
        True if the response was matched to a pending dispatch entry (either
        by ``handoff_id`` or ``task_id``).
    reject_reason:
        Non-empty string describing why correlation failed or why the response
        was treated as an unknown kind.  Empty when ``was_correlated`` is True.
    callback_invoked:
        True if a registered callback was called (only possible when
        ``was_correlated`` is True and the response is terminal).
    """

    envelope: AndroidHandoffResponseEnvelope
    was_correlated: bool = False
    reject_reason: str = ""
    callback_invoked: bool = False


# ---------------------------------------------------------------------------
# Canonical ingress entry-point
# ---------------------------------------------------------------------------


def ingest_android_handoff_response(
    message: Dict[str, Any],
    *,
    runtime: Optional[HandoffV2ResponseRuntime] = None,
) -> HandoffV2ResponseOutcome:
    """Canonical V2-side ingress for Android HandoffEnvelopeV2 responses (PR-H).

    Processes an inbound Android ``handoff_ack`` / ``handoff_result`` /
    ``handoff_failure`` message:

    1. Extracts a typed :class:`~contracts.android_handoff_response.AndroidHandoffResponseEnvelope`.
    2. Logs an early warning for ``response_kind=unknown`` and returns
       ``was_correlated=False``.
    3. Attempts correlation via ``handoff_id`` → ``task_id`` (in that order).
    4. For **terminal** responses (result / failure / timeout / cancelled):
       - Resolves and removes the pending registry entry.
       - Invokes the registered callback if found.
    5. For **ack** responses:
       - Resolves the pending registry entry **without** removing it
         (a terminal response is still expected).
       - Invokes the registered callback so callers can advance their
         lifecycle state machine.
    6. Returns a :class:`HandoffV2ResponseOutcome`.

    Parameters
    ----------
    message:
        Raw inbound Android message dict (top-level AIP envelope).
    runtime:
        Optional :class:`HandoffV2ResponseRuntime` instance for dependency
        injection.  Defaults to the process-level singleton.

    Returns
    -------
    HandoffV2ResponseOutcome
        Always returned; never raises.
    """
    _runtime = runtime if runtime is not None else get_handoff_v2_response_runtime()

    try:
        envelope = extract_handoff_response_envelope(message)
    except Exception as exc:
        logger.error(
            "handoff_v2 ingress: failed to extract response envelope: %s", exc
        )
        # Produce a minimal unknown envelope so the outcome is still typed.
        envelope = AndroidHandoffResponseEnvelope(
            response_kind=HandoffResponseKind.unknown,
        )
        return HandoffV2ResponseOutcome(
            envelope=envelope,
            was_correlated=False,
            reject_reason=f"envelope extraction failed: {exc}",
        )

    # Warn on unknown kind but do not hard-reject.
    if envelope.response_kind == HandoffResponseKind.unknown:
        logger.warning(
            "handoff_v2 ingress: unknown response_kind handoff_id=%r device=%s",
            envelope.handoff_id,
            envelope.device_id,
        )
        return HandoffV2ResponseOutcome(
            envelope=envelope,
            was_correlated=False,
            reject_reason=(
                f"unknown response_kind; handoff_id={envelope.handoff_id!r} "
                f"device_id={envelope.device_id!r}"
            ),
        )

    # Determine whether to clear the pending entry after resolution.
    is_terminal = envelope.is_terminal

    try:
        callback = _runtime.resolve(envelope, clear=is_terminal)
    except Exception as exc:
        logger.error(
            "handoff_v2 ingress: runtime.resolve failed: %s", exc
        )
        return HandoffV2ResponseOutcome(
            envelope=envelope,
            was_correlated=False,
            reject_reason=f"registry resolve failed: {exc}",
        )

    if callback is None:
        reject_reason = (
            f"no pending dispatch found for handoff_id={envelope.handoff_id!r} "
            f"task_id={envelope.task_id!r} device_id={envelope.device_id!r}"
        )
        logger.debug("handoff_v2 ingress miss: %s", reject_reason)
        return HandoffV2ResponseOutcome(
            envelope=envelope,
            was_correlated=False,
            reject_reason=reject_reason,
        )

    # Invoke the callback.
    callback_invoked = False
    try:
        callback(envelope)
        callback_invoked = True
        logger.info(
            "handoff_v2 ingress: correlated kind=%s handoff_id=%r device=%s terminal=%s",
            envelope.response_kind,
            envelope.handoff_id,
            envelope.device_id,
            is_terminal,
        )
    except Exception as exc:
        logger.error(
            "handoff_v2 ingress: callback raised (non-fatal): "
            "handoff_id=%r kind=%s error=%s",
            envelope.handoff_id,
            envelope.response_kind,
            exc,
        )

    return HandoffV2ResponseOutcome(
        envelope=envelope,
        was_correlated=True,
        reject_reason="",
        callback_invoked=callback_invoked,
    )


__all__ = [
    # Sentinels
    "ANDROID_HANDOFF_V2_RESPONSE_INGRESS_PR_H_SENTINEL",
    "HANDOFF_ID_CORRELATION_IS_PRIMARY_POLICY",
    "SINGLE_INGRESS_PATH_POLICY",
    "NON_DESTRUCTIVE_ON_MISS_POLICY",
    "TERMINAL_RESPONSE_CLEARS_PENDING_POLICY",
    "ACK_DOES_NOT_CLEAR_PENDING_POLICY",
    "UNKNOWN_KIND_IS_LOGGED_NOT_REJECTED_POLICY",
    "INGRESS_IS_EXCEPTION_SAFE_POLICY",
    "RESPONSE_ENVELOPE_IS_ALWAYS_RETURNED_POLICY",
    "HANDOFF_V2_RESPONSE_INGRESS_IS_ADDITIVE_POLICY",
    # Runtime
    "HandoffV2ResponseRuntime",
    "get_handoff_v2_response_runtime",
    # Outcome
    "HandoffV2ResponseOutcome",
    # Re-exports from contracts
    "extract_handoff_response_envelope",
    # Canonical ingress
    "ingest_android_handoff_response",
]
