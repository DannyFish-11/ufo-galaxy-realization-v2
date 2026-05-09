"""core/android_runtime_transition_reducer.py
==============================================
PR-11-V2: Canonical Android Delegated Runtime Transition Reducer.

Background
----------
After PR-10-V2 added unified observability and PR-4V2 established the
participant truth ingress path, the V2 orchestration layer holds:

* An execution tracker (:mod:`core.delegated_runtime_execution_tracker`,
  PR-10) that models delegated task phase at a low level.
* A dispatch binding (:mod:`core.android_runtime_dispatch_binding`, PR-11)
  that models the *targeting* identity of a specific dispatch.
* A participant truth ingress (:mod:`core.android_participant_truth_ingress`,
  PR-4V2) that reconciles Android-reported truth into V2 canonical state.
* A session-level state model
  (:mod:`core.android_participant_session_state`, PR-11-V2) that tracks the
  top-level lifecycle phase of a participant session.

However, the logic that maps an **incoming signal** (handoff result, takeover
response, reconciliation signal, execution signal) to the correct state
transition is currently duplicated across:

* individual gateway handlers, each resolving its own signal type,
* the participant truth ingress module, which internally maps truth kinds to
  ``AcknowledgmentSignal`` values and applies them,
* the result normalizer, which additionally applies a terminal deduplication
  guard.

This means that multiple modules independently decide *which session-level
phase transition* a given signal implies.  When a new signal type is added or
existing semantics change, all these sites must be updated in sync.

This module provides a **single canonical reducer** that:

1. Accepts a raw incoming signal descriptor — typed as
   :class:`AndroidRuntimeSignalInput` — together with the current
   :class:`~core.android_participant_session_state.AndroidParticipantSessionRecord`.

2. Maps the signal to the correct
   :class:`~core.android_participant_session_state.AndroidParticipantSessionSignal`.

3. Returns an :class:`AndroidRuntimeTransitionResult` that carries:

   * the updated (or unchanged) session record,
   * a boolean ``was_transitioned`` flag,
   * the resolved ``next_signal`` (or ``None``),
   * a ``transition_description`` for audit / logging.

4. Provides a family of convenience helpers — one per signal domain:

   * :func:`reduce_handoff_result` — for handoff_ack / handoff_result /
     handoff_failure signals from the Android runtime.
   * :func:`reduce_takeover_response` — for TAKEOVER_RESPONSE signals.
   * :func:`reduce_reconciliation_signal` — for reconciliation_signal
     messages.
   * :func:`reduce_execution_signal` — for delegated_execution_signal
     messages (ACK / PROGRESS / RESULT / ERROR / TIMEOUT / CANCELLED).
   * :func:`reduce_participant_truth` — for explicit participant truth kinds
     (cancel / failure / result / task_phase).

5. Does NOT call any gateway handler or modify any external tracker.  It is
   a **pure function family** that computes next state from current state +
   signal.  Callers persist the returned record via
   :func:`~core.android_participant_session_state.record_participant_session`.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Pure reduction** — no side-effects on external modules; return value
  carries all information the caller needs.
- **Single responsibility** — the reducer is the *only* place where
  signal-to-session-signal mapping lives.  All other code delegates here.
- **Non-raising** — all helpers catch exceptions and return safe fallback
  :class:`AndroidRuntimeTransitionResult` values.
- **Explicit over implicit** — each mapping case is enumerated; no
  heuristic inference.

Public API
----------
Sentinels::

    ANDROID_RUNTIME_TRANSITION_REDUCER_AUTHORITY
    ANDROID_RUNTIME_TRANSITION_REDUCER_CONTRACT_VERSION

Dataclass::

    AndroidRuntimeSignalInput
    AndroidRuntimeTransitionResult

Functions::

    reduce_android_runtime_signal(record, signal_input) -> AndroidRuntimeTransitionResult
    reduce_handoff_result(record, *, response_type, ...) -> AndroidRuntimeTransitionResult
    reduce_takeover_response(record, *, accepted, ...) -> AndroidRuntimeTransitionResult
    reduce_reconciliation_signal(record, *, truth_kind, was_reconciled, ...) -> AndroidRuntimeTransitionResult
    reduce_execution_signal(record, *, signal_kind, ...) -> AndroidRuntimeTransitionResult
    reduce_participant_truth(record, *, truth_kind, was_reconciled, ...) -> AndroidRuntimeTransitionResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.AndroidRuntimeTransitionReducer")

# ---------------------------------------------------------------------------
# Lazy imports from peer modules — guarded for loadability
# ---------------------------------------------------------------------------

try:
    from core.android_participant_session_state import (
        AndroidParticipantSessionPhase,
        AndroidParticipantSessionRecord,
        AndroidParticipantSessionSignal,
        advance_participant_session,
    )

    _SESSION_STATE_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _SESSION_STATE_AVAILABLE = False
    AndroidParticipantSessionPhase = None  # type: ignore[assignment,misc]
    AndroidParticipantSessionRecord = None  # type: ignore[assignment,misc]
    AndroidParticipantSessionSignal = None  # type: ignore[assignment,misc]
    advance_participant_session = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_RUNTIME_TRANSITION_REDUCER_AUTHORITY: str = (
    "ANDROID_RUNTIME_TRANSITION_REDUCER_AUTHORITY::"
    "core.android_runtime_transition_reducer is the canonical authority for "
    "mapping incoming Android delegated runtime signals to V2 participant "
    "session phase transitions.  All signal-to-session-signal mapping "
    "lives exclusively in this module."
)

ANDROID_RUNTIME_TRANSITION_REDUCER_CONTRACT_VERSION: str = "1.0"

# Policy sentinels

REDUCER_IS_PURE_FUNCTION_POLICY: str = (
    "POLICY::REDUCER_IS_PURE_FUNCTION: reduce_android_runtime_signal() and "
    "all domain-specific helpers are pure functions.  They compute the next "
    "session state from (current state, signal input) and return a typed "
    "result.  They do NOT write to any ring buffer, tracker, or audit log.  "
    "Callers are responsible for persisting the returned record."
)

REDUCER_IS_SINGLE_MAPPING_AUTHORITY_POLICY: str = (
    "POLICY::REDUCER_IS_SINGLE_MAPPING_AUTHORITY: The signal-to-session-phase "
    "mapping that converts an incoming wire signal (handoff result, takeover "
    "response, reconciliation signal, execution signal) into an "
    "AndroidParticipantSessionSignal MUST live only in this module.  "
    "Duplicating this mapping in gateway handlers or ingress modules is "
    "prohibited."
)

REDUCER_NON_RAISING_POLICY: str = (
    "POLICY::REDUCER_NON_RAISING: All reduction functions MUST catch "
    "exceptions and return a safe AndroidRuntimeTransitionResult with "
    "was_transitioned=False.  They must never propagate exceptions to callers."
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidRuntimeSignalInput:
    """Typed descriptor for a single incoming Android delegated runtime signal.

    Callers populate only the fields relevant to the signal domain.

    Attributes
    ----------
    signal_domain
        High-level domain of the signal: ``handoff``, ``takeover``,
        ``reconciliation``, ``execution``, or ``participant_truth``.
    signal_type
        Domain-specific signal type string (e.g. ``handoff_ack``,
        ``accepted``, ``cancel``, ``ack``).
    was_successful
        Generic success flag.  Interpretation is signal-domain-specific.
    truth_kind
        For ``reconciliation`` / ``participant_truth`` domains — the
        :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`
        value string.
    was_reconciled
        For ``reconciliation`` / ``participant_truth`` — whether the ingress
        successfully reconciled the truth into V2 canonical state.
    reject_reason
        Non-empty when the signal was rejected by an upstream ingress layer.
    metadata
        Opaque extra fields.
    """

    signal_domain: str = ""
    signal_type: str = ""
    was_successful: bool = False
    truth_kind: str = ""
    was_reconciled: bool = False
    reject_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AndroidRuntimeTransitionResult:
    """Result of a single Android runtime signal reduction.

    Attributes
    ----------
    record
        The (potentially updated) :class:`AndroidParticipantSessionRecord`.
        Identical to the input *record* when no transition occurred.
    was_transitioned
        ``True`` if the session phase was actually advanced by this signal.
    next_signal
        The :class:`AndroidParticipantSessionSignal` that was applied, or
        ``None`` if no transition occurred.
    transition_description
        Human-readable summary of the transition (or no-op reason) for audit.
    """

    record: Any  # AndroidParticipantSessionRecord — Any to avoid hard dep
    was_transitioned: bool = False
    next_signal: Optional[Any] = None  # AndroidParticipantSessionSignal
    transition_description: str = ""


# ---------------------------------------------------------------------------
# Internal mapping helpers
# ---------------------------------------------------------------------------

# Handoff response type → session signal
_HANDOFF_TYPE_TO_SIGNAL: Dict[str, Any] = {}  # populated after import guard below
_EXECUTION_KIND_TO_SIGNAL: Dict[str, Any] = {}
_TRUTH_KIND_TO_SIGNAL: Dict[str, Any] = {}
_EXPLICIT_RECONCILIATION_REJECT_REASONS = {
    "stale_rejected",
    "out_of_order_rejected",
    "reconnect_delayed_rejected",
    "conflict_center_truth_retained",
    "duplicate_ignored",
}

if _SESSION_STATE_AVAILABLE:
    _HANDOFF_TYPE_TO_SIGNAL = {
        "handoff_ack": AndroidParticipantSessionSignal.execution_started,
        "handoff_result": AndroidParticipantSessionSignal.result_success,
        "handoff_failure": AndroidParticipantSessionSignal.result_failure,
        "handoff_envelope_v2_result": AndroidParticipantSessionSignal.result_success,
    }

    _EXECUTION_KIND_TO_SIGNAL = {
        "ack": AndroidParticipantSessionSignal.execution_started,
        "progress": AndroidParticipantSessionSignal.execution_progressed,
        "partial_result": AndroidParticipantSessionSignal.execution_progressed,
        "final_result": AndroidParticipantSessionSignal.result_success,
        "error": AndroidParticipantSessionSignal.result_failure,
        "timeout": AndroidParticipantSessionSignal.result_failure,
        "cancelled": AndroidParticipantSessionSignal.result_cancelled,
    }

    _TRUTH_KIND_TO_SIGNAL = {
        "result": AndroidParticipantSessionSignal.result_success,
        "failure": AndroidParticipantSessionSignal.result_failure,
        "cancel": AndroidParticipantSessionSignal.result_cancelled,
        "task_phase": AndroidParticipantSessionSignal.reconciliation_started,
        "status": AndroidParticipantSessionSignal.execution_progressed,
        "session_snapshot": AndroidParticipantSessionSignal.execution_progressed,
        "readiness_assessment": AndroidParticipantSessionSignal.execution_progressed,
        "runtime_state": AndroidParticipantSessionSignal.execution_progressed,
    }


def _apply(
    record: Any,
    signal: Any,
    description: str,
) -> "AndroidRuntimeTransitionResult":
    """Attempt the transition and return a typed result."""
    if not _SESSION_STATE_AVAILABLE or advance_participant_session is None:
        return AndroidRuntimeTransitionResult(
            record=record,
            was_transitioned=False,
            transition_description="session_state_module_unavailable",
        )
    updated = advance_participant_session(record, signal)
    transitioned = updated is not record
    return AndroidRuntimeTransitionResult(
        record=updated,
        was_transitioned=transitioned,
        next_signal=signal if transitioned else None,
        transition_description=description if transitioned else f"noop:{description}",
    )


def _normalize_reconciliation_reject_reason(reject_reason: str) -> str:
    reason = str(reject_reason or "").strip().lower()
    if not reason:
        return "unknown_reject_reason"
    for known in _EXPLICIT_RECONCILIATION_REJECT_REASONS:
        if known in reason:
            return known
    return reason


# ---------------------------------------------------------------------------
# Domain-specific reduction helpers
# ---------------------------------------------------------------------------


def reduce_handoff_result(
    record: Any,
    *,
    response_type: str = "",
    was_successful: bool = False,
    **_kwargs: Any,
) -> "AndroidRuntimeTransitionResult":
    """Reduce a handoff-response signal to a session phase transition.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    response_type:
        Android handoff response type string: ``handoff_ack``,
        ``handoff_result``, ``handoff_failure``,
        ``handoff_envelope_v2_result``.
    was_successful:
        Whether the handoff was acknowledged/completed successfully (used as
        fallback when ``response_type`` is unrecognised).
    """
    try:
        sig = _HANDOFF_TYPE_TO_SIGNAL.get(response_type.lower() if response_type else "")
        if sig is None:
            # Fallback based on success flag
            if _SESSION_STATE_AVAILABLE:
                sig = (
                    AndroidParticipantSessionSignal.execution_started
                    if was_successful
                    else AndroidParticipantSessionSignal.result_failure
                )
            else:
                return AndroidRuntimeTransitionResult(
                    record=record, was_transitioned=False,
                    transition_description="session_state_unavailable",
                )
        return _apply(record, sig, f"handoff_result:{response_type}→{sig.value}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("reduce_handoff_result: failed (non-fatal): %s", exc)
        return AndroidRuntimeTransitionResult(
            record=record, was_transitioned=False,
            transition_description=f"reduce_handoff_result_error:{exc}",
        )


def reduce_takeover_response(
    record: Any,
    *,
    accepted: bool = False,
    takeover_id: str = "",
    **_kwargs: Any,
) -> "AndroidRuntimeTransitionResult":
    """Reduce a TAKEOVER_RESPONSE to a session phase transition.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    accepted:
        ``True`` if the Android runtime accepted the takeover.
    takeover_id:
        Takeover identifier from the TAKEOVER_REQUEST.
    """
    try:
        if not _SESSION_STATE_AVAILABLE:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description="session_state_unavailable",
            )
        sig = (
            AndroidParticipantSessionSignal.takeover_accepted
            if accepted
            else AndroidParticipantSessionSignal.takeover_rejected
        )
        decision = "accepted" if accepted else "rejected"
        return _apply(
            record,
            sig,
            f"takeover_response:{decision}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("reduce_takeover_response: failed (non-fatal): %s", exc)
        return AndroidRuntimeTransitionResult(
            record=record, was_transitioned=False,
            transition_description=f"reduce_takeover_response_error:{exc}",
        )


def reduce_reconciliation_signal(
    record: Any,
    *,
    truth_kind: str = "",
    was_reconciled: bool = False,
    reject_reason: str = "",
    **_kwargs: Any,
) -> "AndroidRuntimeTransitionResult":
    """Reduce a reconciliation_signal to a session phase transition.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    truth_kind:
        The ``AndroidParticipantTruthKind`` value string from the ingress
        outcome envelope.
    was_reconciled:
        Whether the ingress successfully reconciled the signal.
    reject_reason:
        Non-empty if the signal was rejected.
    """
    try:
        if not _SESSION_STATE_AVAILABLE:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description="session_state_unavailable",
            )
        if not was_reconciled:
            normalized_reject = _normalize_reconciliation_reject_reason(reject_reason)
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description=f"reconciliation_signal_not_reconciled:{normalized_reject}",
            )
        sig = _TRUTH_KIND_TO_SIGNAL.get(truth_kind.lower() if truth_kind else "")
        if sig is None:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description=f"reconciliation_signal_unknown_truth_kind:{truth_kind}",
            )
        return _apply(record, sig, f"reconciliation_signal:{truth_kind}→{sig.value}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("reduce_reconciliation_signal: failed (non-fatal): %s", exc)
        return AndroidRuntimeTransitionResult(
            record=record, was_transitioned=False,
            transition_description=f"reduce_reconciliation_signal_error:{exc}",
        )


def reduce_execution_signal(
    record: Any,
    *,
    signal_kind: str = "",
    was_updated: bool = False,
    reject_reason: str = "",
    **_kwargs: Any,
) -> "AndroidRuntimeTransitionResult":
    """Reduce a ``delegated_execution_signal`` to a session phase transition.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    signal_kind:
        The ``AndroidSignalKind`` / ``DelegatedSignalKind`` string value
        (e.g. ``"ack"``, ``"progress"``, ``"final_result"``).
    was_updated:
        Whether the underlying execution tracker was actually updated.
    reject_reason:
        Non-empty if the signal was rejected by the execution reconciler.
    """
    try:
        if not _SESSION_STATE_AVAILABLE:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description="session_state_unavailable",
            )
        if not was_updated:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description=f"execution_signal_not_updated:{reject_reason}",
            )
        sig = _EXECUTION_KIND_TO_SIGNAL.get(signal_kind.lower() if signal_kind else "")
        if sig is None:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description=f"execution_signal_unknown_kind:{signal_kind}",
            )
        return _apply(record, sig, f"execution_signal:{signal_kind}→{sig.value}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("reduce_execution_signal: failed (non-fatal): %s", exc)
        return AndroidRuntimeTransitionResult(
            record=record, was_transitioned=False,
            transition_description=f"reduce_execution_signal_error:{exc}",
        )


def reduce_participant_truth(
    record: Any,
    *,
    truth_kind: str = "",
    was_reconciled: bool = False,
    reject_reason: str = "",
    **_kwargs: Any,
) -> "AndroidRuntimeTransitionResult":
    """Reduce an Android participant truth update to a session phase transition.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    truth_kind:
        ``AndroidParticipantTruthKind`` value string from the truth envelope.
    was_reconciled:
        Whether the participant truth ingress reconciled the update.
    reject_reason:
        Non-empty if reconciliation was rejected.
    """
    try:
        if not _SESSION_STATE_AVAILABLE:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description="session_state_unavailable",
            )
        if not was_reconciled:
            normalized_reject = _normalize_reconciliation_reject_reason(reject_reason)
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description=f"participant_truth_not_reconciled:{normalized_reject}",
            )
        sig = _TRUTH_KIND_TO_SIGNAL.get(truth_kind.lower() if truth_kind else "")
        if sig is None:
            return AndroidRuntimeTransitionResult(
                record=record, was_transitioned=False,
                transition_description=f"participant_truth_unknown_kind:{truth_kind}",
            )
        return _apply(record, sig, f"participant_truth:{truth_kind}→{sig.value}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("reduce_participant_truth: failed (non-fatal): %s", exc)
        return AndroidRuntimeTransitionResult(
            record=record, was_transitioned=False,
            transition_description=f"reduce_participant_truth_error:{exc}",
        )


# ---------------------------------------------------------------------------
# Unified entry-point
# ---------------------------------------------------------------------------


def reduce_android_runtime_signal(
    record: Any,
    signal_input: "AndroidRuntimeSignalInput",
) -> "AndroidRuntimeTransitionResult":
    """Reduce *signal_input* against *record* and return the transition result.

    This is the **unified entry-point** that dispatches to the appropriate
    domain-specific helper based on ``signal_input.signal_domain``.

    Parameters
    ----------
    record:
        Current :class:`AndroidParticipantSessionRecord`.
    signal_input:
        :class:`AndroidRuntimeSignalInput` describing the incoming signal.

    Returns
    -------
    AndroidRuntimeTransitionResult
        Always returns a valid result; never raises.
    """
    try:
        domain = (signal_input.signal_domain or "").lower().strip()

        if domain == "handoff":
            return reduce_handoff_result(
                record,
                response_type=signal_input.signal_type,
                was_successful=signal_input.was_successful,
            )
        if domain == "takeover":
            return reduce_takeover_response(
                record,
                accepted=signal_input.was_successful,
                takeover_id=signal_input.metadata.get("takeover_id", ""),
            )
        if domain == "reconciliation":
            return reduce_reconciliation_signal(
                record,
                truth_kind=signal_input.truth_kind or signal_input.signal_type,
                was_reconciled=signal_input.was_reconciled,
                reject_reason=signal_input.reject_reason,
            )
        if domain == "execution":
            return reduce_execution_signal(
                record,
                signal_kind=signal_input.signal_type,
                was_updated=signal_input.was_reconciled,
                reject_reason=signal_input.reject_reason,
            )
        if domain == "participant_truth":
            return reduce_participant_truth(
                record,
                truth_kind=signal_input.truth_kind or signal_input.signal_type,
                was_reconciled=signal_input.was_reconciled,
                reject_reason=signal_input.reject_reason,
            )

        return AndroidRuntimeTransitionResult(
            record=record,
            was_transitioned=False,
            transition_description=f"unknown_signal_domain:{domain}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("reduce_android_runtime_signal: failed (non-fatal): %s", exc)
        return AndroidRuntimeTransitionResult(
            record=record,
            was_transitioned=False,
            transition_description=f"reduce_android_runtime_signal_error:{exc}",
        )
