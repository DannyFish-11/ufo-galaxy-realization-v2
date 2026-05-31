"""core/android_result_normalizer.py
=====================================
PR-08-V2: Unified Android Result Normalization and Canonical Reconciliation
Entry Point.

Background
----------
Prior PR packages established per-message-type ingress paths for Android
result and state signals:

* ``task_result``                — ``_try_reconcile`` + ``_try_ingest_participant_truth``
  in ``galaxy_gateway.android.handlers.task_lifecycle``
* ``goal_execution_result``      — ``_reconcile_goal_result`` in
  ``galaxy_gateway.android.handlers.goal_execution`` (participant truth
  ingress was absent — closed by this PR)
* ``delegated_execution_signal`` — ``ingest_delegated_execution_signal`` via
  ``galaxy_gateway.android.handlers.delegated_signal``
* ``handoff_ack/result/failure/handoff_envelope_v2_result`` —
  ``ingest_android_handoff_response`` via
  ``galaxy_gateway.android.handlers.handoff_v2_result``
* ``reconciliation_signal``      — ``ingest_android_participant_truth_message``
  via ``galaxy_gateway.android.handlers.reconciliation_signal``

These paths each advance V2 canonical state independently, creating a risk of
duplicate terminal-state accounting when multiple signals representing the
same terminal outcome arrive for the same contract / session (e.g. a
``task_result`` and a ``reconciliation_signal`` for the same contract_id
arriving within milliseconds of each other).

This module provides:

1. :class:`AndroidResultCategory` — canonical responsibility-boundary
   classification for each Android message type:

   * ``user_visible_business_result`` — messages that carry a user-visible
     execution outcome (``task_result``, ``goal_execution_result``).
   * ``runtime_lifecycle_signal`` — messages that carry a runtime execution
     lifecycle event (``delegated_execution_signal``).
   * ``reconciliation_authoritative_update`` — messages that are an explicit
     V2-side reconciliation push or handoff outcome (``reconciliation_signal``,
     ``handoff_ack``, ``handoff_result``, ``handoff_failure``,
     ``handoff_envelope_v2_result``).

2. :class:`AndroidResultNormalizerOutcome` — typed, immutable result of one
   normalization attempt.

3. :func:`classify_android_result_message` — maps a raw message dict to its
   :class:`AndroidResultCategory`.

4. :func:`normalize_android_result` — the unified entry-point: classifies the
   message, applies the process-local terminal-state deduplication guard, routes
   to the appropriate canonical ingress function, and returns a typed
   :class:`AndroidResultNormalizerOutcome`.

   The canonical ingress functions called are the SAME functions already used
   by individual gateway handlers; this module is **additive** — it does not
   replace any existing path.

5. Six policy sentinels documenting responsibility-boundary rules.

6. One PR sentinel (``ANDROID_RESULT_NORMALIZER_PR8V2_SENTINEL``).

Deduplication design
--------------------
The underlying ingress modules (participant truth ingress, delegated signal
ingress, handoff response ingress) all implement V2-terminal-wins guards that
reject reconciliation when the tracking record is already in a terminal phase.
This module adds a **normalization-level idempotency guard** that is keyed on
the canonical identity (``contract_id`` preferred, ``session_id`` fallback):

* When any *terminal* signal for an identity is successfully committed via
  ``normalize_android_result``, the identity is recorded in
  ``_committed_terminal_identities``.
* Subsequent ``normalize_android_result`` calls for the same identity return
  a deduplicated outcome (``was_deduplicated=True``) without re-invoking the
  ingress path.
* This prevents double-accounting when ``task_result`` and
  ``reconciliation_signal`` (or any other pair of terminal signals) arrive
  simultaneously for the same delegated execution.

The guard is process-local and bounded (``_DEDUP_CAPACITY`` slots, LRU-evict)
so it never grows without bound.

Design principles
-----------------
- **Additive only** — does not modify any existing module or handler.
- **Single routing table** — ``_MESSAGE_TYPE_TO_CATEGORY`` is the single
  authority mapping Android wire types to responsibility categories.
- **Non-blocking on import failure** — all canonical ingress imports are
  guarded; the module degrades gracefully if dependencies are absent.
- **Transparent** — the ``AndroidResultNormalizerOutcome`` exposes the
  underlying ingress outcome so callers can inspect it.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger_name = "Galaxy.AndroidResultNormalizer"

try:
    import logging as _logging

    _logger = _logging.getLogger(logger_name)
except Exception as exc:
    _logger.debug("Fallback triggered: %s", exc)
    _logger = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Canonical ingress bindings — guarded imports
# ---------------------------------------------------------------------------

try:
    from core.android_participant_truth_ingress import (
        ingest_android_participant_truth_message as _ingest_participant_truth,
    )

    _PARTICIPANT_TRUTH_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _ingest_participant_truth = None  # type: ignore[assignment]
    _PARTICIPANT_TRUTH_AVAILABLE = False

try:
    from core.android_delegated_signal_ingress import (
        ingest_delegated_execution_signal as _ingest_delegated_signal,
    )

    _DELEGATED_SIGNAL_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _ingest_delegated_signal = None  # type: ignore[assignment]
    _DELEGATED_SIGNAL_AVAILABLE = False

try:
    from core.android_handoff_v2_response_ingress import (
        ingest_android_handoff_response as _ingest_handoff_response,
    )

    _HANDOFF_RESPONSE_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _ingest_handoff_response = None  # type: ignore[assignment]
    _HANDOFF_RESPONSE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ANDROID_RESULT_NORMALIZER_AUTHORITY: str = (
    "core.android_result_normalizer::PR8V2::"
    "unified-android-result-normalization-and-canonical-reconciliation-entry"
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

ANDROID_RESULT_NORMALIZER_PR8V2_SENTINEL: str = (
    "android_result_normalizer::package=PR8V2::"
    "pr=unify-android-result-messages-into-participant-truth-and-canonical-reconciliation::"
    "authority=ANDROID_RESULT_NORMALIZER_AUTHORITY"
)

# ---------------------------------------------------------------------------
# Policy sentinels — responsibility-boundary documentation
# ---------------------------------------------------------------------------

UNIFIED_NORMALIZATION_ENTRY_POLICY: str = (
    "POLICY::UNIFIED_NORMALIZATION_ENTRY: "
    "normalize_android_result is the single convergence entry-point for all "
    "Android result and state signal message types.  Gateway handlers may call "
    "it in addition to (or instead of) their per-message-type ingress calls to "
    "obtain a typed, auditable normalization record."
)

CATEGORY_BOUNDARY_IS_AUTHORITATIVE_POLICY: str = (
    "POLICY::CATEGORY_BOUNDARY_IS_AUTHORITATIVE: "
    "AndroidResultCategory is the single authority for the responsibility "
    "boundary between user_visible_business_result (task_result, "
    "goal_execution_result), runtime_lifecycle_signal "
    "(delegated_execution_signal), and reconciliation_authoritative_update "
    "(reconciliation_signal, handoff_ack/result/failure, "
    "handoff_envelope_v2_result).  This classification governs routing "
    "decisions and observability labelling."
)

TERMINAL_DEDUP_PREVENTS_DOUBLE_ACCOUNTING_POLICY: str = (
    "POLICY::TERMINAL_DEDUP_PREVENTS_DOUBLE_ACCOUNTING: "
    "When any terminal signal (result/failure/cancel) for a given "
    "contract_id/session_id identity is successfully committed through "
    "normalize_android_result, subsequent terminal signals for the same "
    "identity are deduplicated (was_deduplicated=True) without re-invoking "
    "the ingress path.  This prevents the same task from being recorded as "
    "terminal multiple times when multiple Android message types carry the "
    "same terminal outcome."
)

PARTICIPANT_TRUTH_IS_CONVERGENCE_TARGET_POLICY: str = (
    "POLICY::PARTICIPANT_TRUTH_IS_CONVERGENCE_TARGET: "
    "user_visible_business_result messages (task_result, goal_execution_result) "
    "are routed to the participant truth ingress "
    "(ingest_android_participant_truth_message) with truth_kind='result'.  "
    "The participant truth ingress is the canonical convergence target for "
    "these message types."
)

HANDOFF_RESPONSE_ROUTES_VIA_RESPONSE_INGRESS_POLICY: str = (
    "POLICY::HANDOFF_RESPONSE_ROUTES_VIA_RESPONSE_INGRESS: "
    "reconciliation_authoritative_update messages that originate from handoff "
    "v2 responses (handoff_ack, handoff_result, handoff_failure, "
    "handoff_envelope_v2_result) are routed to "
    "ingest_android_handoff_response.  reconciliation_signal messages are "
    "routed to ingest_android_participant_truth_message so they are reconciled "
    "into participant truth and canonical tracking records."
)

ADDITIVE_NON_DESTRUCTIVE_NORMALIZER_POLICY: str = (
    "POLICY::ADDITIVE_NON_DESTRUCTIVE_NORMALIZER: "
    "The normalizer is additive — it does not replace or modify existing "
    "handler paths.  All routing delegates to the same canonical ingress "
    "functions already called by the gateway handlers.  A failed or "
    "unavailable normalizer call never disrupts existing behaviour."
)

# ---------------------------------------------------------------------------
# AndroidResultCategory enum
# ---------------------------------------------------------------------------


class AndroidResultCategory(str, Enum):
    """Canonical responsibility-boundary classification for Android result messages.

    Values
    ------
    user_visible_business_result
        Messages that carry a user-visible execution outcome.
        Examples: ``task_result``, ``goal_execution_result``.
    runtime_lifecycle_signal
        Messages that carry a runtime execution lifecycle event.
        Examples: ``delegated_execution_signal``.
    reconciliation_authoritative_update
        Messages that are an explicit V2-side reconciliation push or handoff
        outcome.
        Examples: ``reconciliation_signal``, ``handoff_ack``,
        ``handoff_result``, ``handoff_failure``, ``handoff_envelope_v2_result``.
    unknown
        Unrecognised message type; normalization is skipped.
    """

    user_visible_business_result = "user_visible_business_result"
    runtime_lifecycle_signal = "runtime_lifecycle_signal"
    reconciliation_authoritative_update = "reconciliation_authoritative_update"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Message-type → category mapping (single authority table)
# ---------------------------------------------------------------------------

_MESSAGE_TYPE_TO_CATEGORY: Dict[str, AndroidResultCategory] = {
    # User-visible business results
    "task_result": AndroidResultCategory.user_visible_business_result,
    "goal_execution_result": AndroidResultCategory.user_visible_business_result,
    # Android error-path alias — goal_result carries the same user-visible
    # business result as goal_execution_result (different wire name used on
    # failure/cancellation paths in some Android flows).
    "goal_result": AndroidResultCategory.user_visible_business_result,
    # Runtime lifecycle signals
    "delegated_execution_signal": AndroidResultCategory.runtime_lifecycle_signal,
    # Reconciliation-authoritative updates
    "reconciliation_signal": AndroidResultCategory.reconciliation_authoritative_update,
    "handoff_ack": AndroidResultCategory.reconciliation_authoritative_update,
    "handoff_result": AndroidResultCategory.reconciliation_authoritative_update,
    "handoff_failure": AndroidResultCategory.reconciliation_authoritative_update,
    "handoff_envelope_v2_result": AndroidResultCategory.reconciliation_authoritative_update,
}

# truth_kind injected for user_visible_business_result types routed to
# the participant truth ingress.
_BUSINESS_RESULT_TRUTH_KIND: str = "result"

# ---------------------------------------------------------------------------
# AndroidResultNormalizerOutcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidResultNormalizerOutcome:
    """Typed, immutable result of one Android result normalization attempt.

    Attributes
    ----------
    message_type
        The ``type`` field from the inbound message dict (empty if absent).
    category
        The :class:`AndroidResultCategory` assigned to this message.
    was_normalized
        True iff the message was successfully routed to a canonical ingress
        function and the ingress call completed without exception.
    was_deduplicated
        True iff the message was skipped because an earlier terminal signal for
        the same identity (contract_id/session_id) was already committed through
        this normalizer.
    participant_truth_outcome
        The outcome returned by ``ingest_android_participant_truth_message``
        when the routing path invokes participant truth ingress.  None for
        other routing paths.
    signal_reconcile_outcome
        The outcome returned by ``ingest_delegated_execution_signal`` when the
        routing path invokes the delegated signal ingress.  None for other paths.
    handoff_response_outcome
        The outcome returned by ``ingest_android_handoff_response`` when the
        routing path invokes the handoff response ingress.  None for other paths.
    reject_reason
        Non-empty string when normalization was skipped or rejected.
    source_message_id
        ``message_id`` from the inbound message dict (empty if absent).
    committed_terminal_identity
        The identity string (contract_id or session_id) that was recorded as
        terminal by this normalization call.  Empty when no terminal identity
        was committed (non-terminal signal, or dedup skip, or missing key).
    """

    message_type: str = ""
    category: AndroidResultCategory = AndroidResultCategory.unknown
    was_normalized: bool = False
    was_deduplicated: bool = False
    participant_truth_outcome: Optional[Any] = None
    signal_reconcile_outcome: Optional[Any] = None
    handoff_response_outcome: Optional[Any] = None
    reject_reason: str = ""
    source_message_id: str = ""
    committed_terminal_identity: str = ""
    normalizer_envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def is_accepted(self) -> bool:
        """Return True iff normalization succeeded (was_normalized and no reject_reason)."""
        return self.was_normalized and not self.reject_reason

    def to_dict(self) -> Dict[str, Any]:
        pt_dict = (
            self.participant_truth_outcome.to_dict()
            if self.participant_truth_outcome is not None
            and hasattr(self.participant_truth_outcome, "to_dict")
            else None
        )
        sr_dict = (
            self.signal_reconcile_outcome.to_dict()
            if self.signal_reconcile_outcome is not None
            and hasattr(self.signal_reconcile_outcome, "to_dict")
            else None
        )
        hr_dict = (
            self.handoff_response_outcome.to_dict()
            if self.handoff_response_outcome is not None
            and hasattr(self.handoff_response_outcome, "to_dict")
            else None
        )
        return {
            "message_type": self.message_type,
            "category": self.category.value,
            "was_normalized": self.was_normalized,
            "was_deduplicated": self.was_deduplicated,
            "reject_reason": self.reject_reason,
            "source_message_id": self.source_message_id,
            "committed_terminal_identity": self.committed_terminal_identity,
            "normalizer_envelope_id": self.normalizer_envelope_id,
            "participant_truth_outcome": pt_dict,
            "signal_reconcile_outcome": sr_dict,
            "handoff_response_outcome": hr_dict,
        }


# ---------------------------------------------------------------------------
# Terminal-state deduplication guard
# ---------------------------------------------------------------------------

# 1024 slots provides a comfortable buffer for concurrent Android device
# connections (typically 1–10 devices) each generating multiple delegated
# execution contracts over a session lifetime, while remaining small enough
# to have negligible memory cost (~100 bytes per entry × 1024 = ~100 KB max).
_DEDUP_CAPACITY: int = 1024

# Keys are canonical identity strings (contract_id or session_id).
# Values are (timestamp, message_type) tuples recording when the first
# terminal signal for this identity was committed.
_committed_terminal_identities: OrderedDict = OrderedDict()

# Terminal truth kinds that trigger dedup recording
_TERMINAL_TRUTH_KINDS: frozenset = frozenset(
    {"result", "failure", "cancel", "reconciliation_signal"}
)

# Terminal handoff response kinds that trigger dedup recording
_TERMINAL_HANDOFF_KINDS: frozenset = frozenset({"result", "failure"})


def _extract_identity_key(message: Dict[str, Any]) -> str:
    """Return the canonical identity key for dedup purposes.

    Prefers ``contract_id`` (delegated contract identity) over ``session_id``
    (session identity).  Checks both top-level and ``payload`` sub-dict.
    Returns empty string when no suitable key is found.
    """
    payload: Dict[str, Any] = message.get("payload", {}) or {}
    contract_id = (
        str(message.get("contract_id") or payload.get("contract_id") or "").strip()
    )
    if contract_id:
        return f"contract:{contract_id}"
    session_id = (
        str(
            message.get("session_id")
            or payload.get("session_id")
            or message.get("runtime_session_id")
            or payload.get("runtime_session_id")
            or ""
        ).strip()
    )
    if session_id:
        return f"session:{session_id}"
    return ""


def _dedup_is_committed(identity_key: str) -> bool:
    """Return True iff a terminal signal for *identity_key* was already committed."""
    if not identity_key:
        return False
    return identity_key in _committed_terminal_identities


def _dedup_commit(identity_key: str, message_type: str) -> None:
    """Record *identity_key* as having a committed terminal signal.

    Uses LRU eviction when the guard is at capacity.
    """
    if not identity_key:
        return
    if identity_key in _committed_terminal_identities:
        # Already committed — move to end (most recently used)
        _committed_terminal_identities.move_to_end(identity_key)
        return
    if len(_committed_terminal_identities) >= _DEDUP_CAPACITY:
        _committed_terminal_identities.popitem(last=False)
    _committed_terminal_identities[identity_key] = (time.time(), message_type)


def reset_terminal_dedup_guard() -> None:
    """Clear the terminal-state deduplication guard.

    Intended for test isolation only; must not be called in production paths.
    """
    _committed_terminal_identities.clear()


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


def classify_android_result_message(message: Dict[str, Any]) -> AndroidResultCategory:
    """Return the :class:`AndroidResultCategory` for *message*.

    Reads the ``type`` field from the message dict.  Returns
    :attr:`AndroidResultCategory.unknown` for unrecognised or missing types.
    """
    msg_type = str(message.get("type") or "").strip().lower()
    return _MESSAGE_TYPE_TO_CATEGORY.get(msg_type, AndroidResultCategory.unknown)


# ---------------------------------------------------------------------------
# Routing helpers (internal)
# ---------------------------------------------------------------------------


def _route_business_result(
    message: Dict[str, Any],
    *,
    runtime: Optional[Any],
    registry: Optional[Any],
) -> Optional[Any]:
    """Route a user_visible_business_result message to participant truth ingress."""
    if _ingest_participant_truth is None:
        return None
    enriched = dict(message)
    enriched.setdefault("truth_kind", _BUSINESS_RESULT_TRUTH_KIND)
    return _ingest_participant_truth(enriched, runtime=runtime, registry=registry)


def _route_delegated_signal(
    message: Dict[str, Any],
    *,
    runtime: Optional[Any],
) -> Optional[Any]:
    """Route a runtime_lifecycle_signal message to delegated signal ingress."""
    if _ingest_delegated_signal is None:
        return None
    return _ingest_delegated_signal(message, runtime=runtime)


def _route_reconciliation_signal(
    message: Dict[str, Any],
    *,
    runtime: Optional[Any],
    registry: Optional[Any],
) -> Optional[Any]:
    """Route a reconciliation_signal message to participant truth ingress."""
    if _ingest_participant_truth is None:
        return None
    return _ingest_participant_truth(message, runtime=runtime, registry=registry)


def _route_handoff_response(
    message: Dict[str, Any],
) -> Optional[Any]:
    """Route a handoff response message to the handoff v2 response ingress."""
    if _ingest_handoff_response is None:
        return None
    return _ingest_handoff_response(message)


# ---------------------------------------------------------------------------
# Terminal signal detection helpers
# ---------------------------------------------------------------------------


def _is_terminal_participant_truth_outcome(outcome: Any) -> bool:
    """Return True iff the participant truth outcome committed a terminal state."""
    if outcome is None:
        return False
    if not getattr(outcome, "was_reconciled", False):
        return False
    envelope = getattr(outcome, "envelope", None)
    if envelope is None:
        return False
    truth_kind = getattr(envelope, "truth_kind", None)
    if truth_kind is None:
        return False
    kind_val = truth_kind.value if hasattr(truth_kind, "value") else str(truth_kind)
    return kind_val in _TERMINAL_TRUTH_KINDS


def _is_terminal_signal_reconcile_outcome(outcome: Any) -> bool:
    """Return True iff the delegated signal outcome committed a terminal phase."""
    if outcome is None:
        return False
    if not getattr(outcome, "was_updated", False):
        return False
    record = getattr(outcome, "record", None)
    if record is None:
        return False
    phase = getattr(record, "phase", None)
    if phase is None:
        return False
    if hasattr(phase, "is_terminal"):
        return bool(phase.is_terminal())
    phase_val = str(phase).lower()
    return any(t in phase_val for t in ("completed", "failed", "timed_out", "cancelled"))


def _is_terminal_handoff_outcome(outcome: Any) -> bool:
    """Return True iff the handoff response outcome committed a terminal response."""
    if outcome is None:
        return False
    if not getattr(outcome, "was_correlated", False):
        return False
    envelope = getattr(outcome, "envelope", None)
    if envelope is None:
        return False
    kind = getattr(envelope, "response_kind", None)
    kind_val = str(kind).lower() if kind is not None else ""
    return kind_val in _TERMINAL_HANDOFF_KINDS


# ---------------------------------------------------------------------------
# Public API: normalize_android_result
# ---------------------------------------------------------------------------


def normalize_android_result(
    message: Dict[str, Any],
    *,
    runtime: Optional[Any] = None,
    registry: Optional[Any] = None,
) -> AndroidResultNormalizerOutcome:
    """Unified entry-point for Android result and state signal normalization.

    Classifies *message* by its ``type`` field, applies the terminal-state
    deduplication guard, routes to the appropriate canonical ingress function,
    and returns a typed :class:`AndroidResultNormalizerOutcome`.

    Parameters
    ----------
    message:
        Raw inbound Android message dict.
    runtime:
        Optional execution tracking runtime override (for test isolation).
    registry:
        Optional session registry override (for test isolation).

    Returns
    -------
    AndroidResultNormalizerOutcome
    """
    msg_type = str(message.get("type") or "").strip()
    source_message_id = str(message.get("message_id") or "")
    category = classify_android_result_message(message)

    if category == AndroidResultCategory.unknown:
        _log_debug(
            "normalize_android_result: unknown message type=%r — skipping",
            msg_type,
        )
        return AndroidResultNormalizerOutcome(
            message_type=msg_type,
            category=category,
            was_normalized=False,
            reject_reason=f"unknown_message_type:{msg_type}",
            source_message_id=source_message_id,
        )

    # ------------------------------------------------------------------
    # Terminal-state deduplication guard
    # ------------------------------------------------------------------
    identity_key = _extract_identity_key(message)
    if identity_key and _dedup_is_committed(identity_key):
        _log_debug(
            "normalize_android_result: terminal dedup guard hit "
            "type=%r identity=%r — skipping",
            msg_type,
            identity_key,
        )
        return AndroidResultNormalizerOutcome(
            message_type=msg_type,
            category=category,
            was_normalized=False,
            was_deduplicated=True,
            reject_reason="terminal_dedup:already_committed",
            source_message_id=source_message_id,
        )

    # ------------------------------------------------------------------
    # Route to canonical ingress
    # ------------------------------------------------------------------
    participant_truth_outcome = None
    signal_reconcile_outcome = None
    handoff_response_outcome = None
    was_normalized = False
    reject_reason = ""
    committed_terminal_identity = ""

    try:
        if category == AndroidResultCategory.user_visible_business_result:
            participant_truth_outcome = _route_business_result(
                message, runtime=runtime, registry=registry
            )
            if participant_truth_outcome is not None:
                was_normalized = True
                # Commit terminal identity if applicable
                if identity_key and _is_terminal_participant_truth_outcome(
                    participant_truth_outcome
                ):
                    _dedup_commit(identity_key, msg_type)
                    committed_terminal_identity = identity_key
            else:
                reject_reason = "participant_truth_ingress_unavailable"

        elif category == AndroidResultCategory.runtime_lifecycle_signal:
            signal_reconcile_outcome = _route_delegated_signal(
                message, runtime=runtime
            )
            if signal_reconcile_outcome is not None:
                was_normalized = True
                # Commit terminal identity if applicable
                if identity_key and _is_terminal_signal_reconcile_outcome(
                    signal_reconcile_outcome
                ):
                    _dedup_commit(identity_key, msg_type)
                    committed_terminal_identity = identity_key
            else:
                reject_reason = "delegated_signal_ingress_unavailable"

        elif category == AndroidResultCategory.reconciliation_authoritative_update:
            msg_type_lower = msg_type.lower()
            if msg_type_lower == "reconciliation_signal":
                participant_truth_outcome = _route_reconciliation_signal(
                    message, runtime=runtime, registry=registry
                )
                if participant_truth_outcome is not None:
                    was_normalized = True
                    if identity_key and _is_terminal_participant_truth_outcome(
                        participant_truth_outcome
                    ):
                        _dedup_commit(identity_key, msg_type)
                        committed_terminal_identity = identity_key
                else:
                    reject_reason = "participant_truth_ingress_unavailable"
            else:
                # handoff_ack / handoff_result / handoff_failure /
                # handoff_envelope_v2_result
                handoff_response_outcome = _route_handoff_response(message)
                if handoff_response_outcome is not None:
                    was_normalized = True
                    if identity_key and _is_terminal_handoff_outcome(
                        handoff_response_outcome
                    ):
                        _dedup_commit(identity_key, msg_type)
                        committed_terminal_identity = identity_key
                else:
                    reject_reason = "handoff_response_ingress_unavailable"

    except Exception as exc:  # noqa: BLE001
        _logger.debug("Fallback triggered: %s", exc)
        was_normalized = False
        reject_reason = f"ingress_exception:{type(exc).__name__}:{exc}"
        _log_debug(
            "normalize_android_result: ingress exception type=%r exc=%s",
            msg_type,
            exc,
        )

    _log_debug(
        "normalize_android_result: type=%r category=%s was_normalized=%s "
        "was_deduplicated=False committed_terminal=%r",
        msg_type,
        category.value,
        was_normalized,
        committed_terminal_identity,
    )

    return AndroidResultNormalizerOutcome(
        message_type=msg_type,
        category=category,
        was_normalized=was_normalized,
        was_deduplicated=False,
        participant_truth_outcome=participant_truth_outcome,
        signal_reconcile_outcome=signal_reconcile_outcome,
        handoff_response_outcome=handoff_response_outcome,
        reject_reason=reject_reason,
        source_message_id=source_message_id,
        committed_terminal_identity=committed_terminal_identity,
    )


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def _log_debug(msg: str, *args: Any) -> None:
    if _logger is not None:
        try:
            _logger.debug(msg, *args)
        except Exception as exc:
            _logger.debug("Suppressed: %s", exc)
