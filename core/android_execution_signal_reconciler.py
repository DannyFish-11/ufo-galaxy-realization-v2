"""core/android_execution_signal_reconciler.py
================================================
PR package 13 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Host-Side Android Execution Signal Reconciliation Binding.

Background
----------
After PR-11 established a canonical dispatch-binding record that ties an
attached Android runtime session to a delegated execution tracker (PR-10),
the host-side orchestration layer can both dispatch delegated work *and* track
it.  However, the actual reconciliation path — where inbound Android execution
signals (ACK / PROGRESS / RESULT / ERROR / TIMEOUT / CANCELLED) are ingested
and translated into canonical phase advances on the
:class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRecord`
— is absent.  Without this path:

* Signals from ``task_result``, ``task_progress``, ``task_end``,
  ``goal_execution_result``, and ``error`` message types flow through the
  gateway handlers but never update the host-side tracker.
* The identity fields (``contract_id``, ``session_id``, ``device_id``,
  ``trace_id``, ``task_id``) that are already present in inbound Android
  payloads are not harvested into a stable reconciliation envelope.
* Signal-to-phase mapping is implicit and duplicated across multiple ad-hoc
  handler sites.

PR-13 closes this gap on the MAIN-repo side by providing:

1. :class:`AndroidSignalKind` — canonical enum for the kind of inbound Android
   execution signal, directly aligned with
   :class:`~core.delegated_runtime_execution_tracker.AcknowledgmentSignal`
   semantics:
   ``ack`` / ``progress`` / ``partial_result`` / ``final_result`` /
   ``error`` / ``timeout`` / ``cancelled``.
2. :class:`AndroidExecutionSignalEnvelope` — typed, immutable record that
   harvests the canonical identity fields from an inbound Android message dict
   (``contract_id``, ``session_id``, ``device_id``, ``trace_id``,
   ``task_id``) together with the resolved :class:`AndroidSignalKind` and an
   opaque payload snapshot.  This is the single stable carrier between
   gateway-handler extraction and tracker reconciliation.
3. :class:`AndroidSignalReconcileOutcome` — typed result of a reconciliation
   attempt, carrying the (potentially updated) tracking record, a boolean flag
   indicating whether the record was actually mutated, and a reject reason when
   reconciliation was skipped.
4. :func:`normalize_android_message_to_signal_kind` — pure mapping function
   that converts a (``message_type``, ``status``) pair from an inbound Android
   AIP v3 message into the canonical :class:`AndroidSignalKind`.  A separate
   function keeps the mapping testable in isolation from I/O concerns.
5. :func:`extract_signal_envelope` — extracts
   :class:`AndroidExecutionSignalEnvelope` from an inbound raw message dict,
   resolving identity fields from both top-level message keys and the nested
   ``payload`` sub-dict (with top-level taking precedence for ``task_id`` and
   ``device_id``, nested ``payload`` taking precedence for
   ``contract_id``, ``session_id``, and ``trace_id`` which are delegated
   routing fields Android sends in payload).
6. :func:`reconcile_android_execution_signal` — the canonical reconciliation
   entry-point that accepts an :class:`AndroidExecutionSignalEnvelope`,
   resolves the tracking record by ``contract_id`` (preferred) or
   ``session_id`` (fallback), applies the signal via
   :func:`~core.delegated_runtime_execution_tracker.apply_acknowledgment_signal`
   or :func:`~core.delegated_runtime_execution_tracker.apply_result`, and
   returns an :class:`AndroidSignalReconcileOutcome`.
7. :func:`reconcile_inbound_message` — convenience wrapper combining
   :func:`extract_signal_envelope` + :func:`reconcile_android_execution_signal`
   so gateway handlers can reconcile an inbound message dict in one call.
8. Ten policy sentinels documenting canonical reconciliation rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Single canonical path** — all inbound Android execution signals are
  reconciled through :func:`reconcile_android_execution_signal`; no other
  path may update the execution tracker from Android signals.
- **Identity-preserving** — ``contract_id``, ``session_id``, ``device_id``,
  ``trace_id``, and ``task_id`` flow from the inbound message envelope into
  the tracker unchanged; the reconciler never synthesises identifiers.
- **Non-destructive on miss** — if no matching tracking record is found the
  function returns an outcome with ``was_updated=False`` and a descriptive
  ``reject_reason``; it never creates a phantom record.
- **Terminal-blocking** — signals arriving after a tracking record has reached
  a terminal phase are silently ignored (PR-10 policy
  ``TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY``).
- **Unknown-signal-safe** — unrecognised message types and statuses map to
  ``AndroidSignalKind.progress`` by default; this keeps the record alive
  without committing to a terminal state.

PR package numbering
--------------------
Package 13 of the post-533 dual-repo runtime unification master plan.
MAIN-repo side only.  Android-repo side (PR-12) wires delegated receipt into
the local takeover execution path; this module consumes the signals produced by
that path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Imports from prior PR packages
# ---------------------------------------------------------------------------

from core.delegated_runtime_execution_tracker import (
    AcknowledgmentSignal,
    DelegatedExecutionResult,
    DelegatedExecutionTrackingRecord,
    DelegatedExecutionTrackingRuntime,
    apply_acknowledgment_signal,
    apply_result,
    get_execution_tracking_runtime,
)

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY: str = (
    "core.android_execution_signal_reconciler::PR13::canonical-host-side-"
    "android-execution-signal-reconciliation-binding"
)

# ---------------------------------------------------------------------------
# Policy sentinels — document canonical reconciliation rules
# ---------------------------------------------------------------------------

RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID: "
    "A reconcile attempt MUST carry at least one of contract_id or session_id "
    "to resolve the canonical tracking record.  Envelopes with both fields "
    "empty are rejected immediately and returned with was_updated=False."
)

RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_SIGNAL_MAPPING_IS_CANONICAL: "
    "The mapping from inbound Android message type + status to "
    "AndroidSignalKind is defined exclusively in "
    "normalize_android_message_to_signal_kind().  No other site may perform "
    "this mapping independently."
)

RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS: "
    "When the resolved tracking record is already in a terminal phase "
    "(completed / failed / timed_out / cancelled) the reconciler returns the "
    "record unchanged with was_updated=False.  This is consistent with PR-10 "
    "TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY."
)

RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE: "
    "Identity fields (contract_id, session_id, device_id, trace_id, task_id) "
    "in the envelope are extracted verbatim from the inbound message and "
    "forwarded as-is.  The reconciler never synthesises or overwrites "
    "identity fields already on the tracking record."
)

RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS: "
    "An unrecognised (message_type, status) pair maps to AndroidSignalKind.progress "
    "so that the tracking record stays alive as in_progress rather than "
    "silently stalling or incorrectly advancing to a terminal state."
)

RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY: "
    "AIP v3 TaskStatus values are mapped canonically: "
    "PENDING→ack, RUNNING/CONTINUE→progress, COMPLETED→final_result, "
    "FAILED→error, CANCELLED→cancelled.  ResultStatus SUCCESS→final_result, "
    "FAILURE→error, TIMEOUT→timeout, SKIPPED/NONE→progress."
)

RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD: "
    "AndroidSignalKind.error maps to AcknowledgmentSignal.error, which "
    "advances the tracking record to the terminal failed phase.  No further "
    "signals will be accepted after this transition."
)

RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD: "
    "AndroidSignalKind.timeout maps to AcknowledgmentSignal.timeout, which "
    "advances the tracking record to the terminal timed_out phase.  No further "
    "signals will be accepted after this transition."
)

RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD: "
    "AndroidSignalKind.cancelled maps to AcknowledgmentSignal.cancelled, which "
    "advances the tracking record to the terminal cancelled phase.  No further "
    "signals will be accepted after this transition."
)

RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY: str = (
    "RECONCILER_POLICY::RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER: "
    "When the signal kind is final_result or error the reconciler calls "
    "apply_result() in addition to apply_acknowledgment_signal(), forwarding "
    "the envelope's payload snapshot as the result payload so that the tracking "
    "record carries a typed DelegatedExecutionResult."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY,
    RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY,
    RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY,
    RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY,
    RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY,
    RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY,
    RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY,
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL: str = (
    "android_execution_signal_reconciler::package=13::pr=post533-pr13-main::"
    "canonical-host-side-android-execution-signal-reconciliation-binding::"
    "authority=ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY"
)

# ---------------------------------------------------------------------------
# AndroidSignalKind enum
# ---------------------------------------------------------------------------


class AndroidSignalKind(str, Enum):
    """Canonical kind of inbound Android execution signal.

    This enum is the single mapping authority between raw Android AIP v3
    message type + status values and the
    :class:`~core.delegated_runtime_execution_tracker.AcknowledgmentSignal`
    semantics used by the PR-10 execution tracker.

    Values
    ------
    ack
        Initial receipt acknowledgment from the Android runtime; corresponds
        to ``AcknowledgmentSignal.ack``.
    progress
        In-progress heartbeat or status update; corresponds to
        ``AcknowledgmentSignal.progress``.
    partial_result
        An intermediate (partial) result payload is available; corresponds to
        ``AcknowledgmentSignal.partial_result``.
    final_result
        Execution has completed successfully; corresponds to
        ``AcknowledgmentSignal.final_result``.
    error
        The Android runtime reported an error; corresponds to
        ``AcknowledgmentSignal.error``.
    timeout
        A timeout was detected (either host-initiated or surfaced by Android);
        corresponds to ``AcknowledgmentSignal.timeout``.
    cancelled
        Execution was cancelled; corresponds to
        ``AcknowledgmentSignal.cancelled``.
    """

    ack = "ack"
    progress = "progress"
    partial_result = "partial_result"
    final_result = "final_result"
    error = "error"
    timeout = "timeout"
    cancelled = "cancelled"

    def to_ack_signal(self) -> AcknowledgmentSignal:
        """Return the canonical :class:`AcknowledgmentSignal` for this kind."""
        return AcknowledgmentSignal(self.value)

    def is_terminal(self) -> bool:
        """Return True iff this signal kind will advance the record to a terminal phase."""
        return self in (
            AndroidSignalKind.final_result,
            AndroidSignalKind.error,
            AndroidSignalKind.timeout,
            AndroidSignalKind.cancelled,
        )

    @classmethod
    def from_string(cls, value: str) -> "AndroidSignalKind":
        """Return the matching :class:`AndroidSignalKind` or ``progress`` as default."""
        if not isinstance(value, str):
            return cls.progress
        try:
            return cls(value.lower())
        except ValueError:
            return cls.progress


# ---------------------------------------------------------------------------
# AndroidExecutionSignalEnvelope dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidExecutionSignalEnvelope:
    """Immutable carrier of a single inbound Android execution signal.

    This dataclass is extracted from a raw inbound AIP v3 message dict by
    :func:`extract_signal_envelope` and consumed by
    :func:`reconcile_android_execution_signal`.  It carries:

    * The resolved :class:`AndroidSignalKind` (already mapped from
      message_type + status).
    * The canonical identity fields used to look up the host-side
      tracking record: ``contract_id``, ``session_id``, ``device_id``,
      ``trace_id``, ``task_id``.
    * Recovery-readiness metadata: ``signal_id`` (Android-assigned UUID),
      ``emission_seq`` (emission sequence counter), ``result_kind``
      (result discriminator for ``final_result`` / ``error`` signals).
    * An opaque ``payload`` snapshot forwarded to the tracker as signal
      payload or result payload.
    * An ``envelope_id`` for tracing / audit purposes (auto-generated UUID).

    Attributes
    ----------
    signal_kind
        The resolved :class:`AndroidSignalKind`.
    contract_id
        Handoff contract identifier from the inbound message (may be empty
        string when not present in the message).
    session_id
        Attached runtime session / runtime session identifier.
    device_id
        Source Android device identifier.
    trace_id
        Distributed trace identifier propagated from the delegated unit.
    task_id
        Task identifier from the inbound message.
    signal_id
        UUID assigned by the Android runtime to uniquely identify this
        specific signal emission.  Empty string when not present (legacy
        messages that pre-date Android PR-16 outbound transport).
    emission_seq
        Monotonically increasing emission sequence counter within the
        delegated execution lifetime.  0 when not present (legacy messages).
    result_kind
        String discriminator for ``final_result`` / ``error`` signal kinds
        that carries the original ``result_kind`` value (``"success"`` /
        ``"failure"`` / ``"unknown"``).  Empty string for non-result signals.
    payload
        Opaque payload snapshot from the inbound message.
    envelope_id
        Auto-generated UUID for this envelope instance (not sourced from the
        message; used for audit / correlation).
    received_at
        Unix timestamp when this envelope was created.
    """

    signal_kind: AndroidSignalKind = AndroidSignalKind.progress
    contract_id: str = ""
    session_id: str = ""
    device_id: str = ""
    trace_id: str = ""
    task_id: str = ""
    signal_id: str = ""
    emission_seq: int = 0
    result_kind: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    received_at: float = field(default_factory=time.time)

    def has_lookup_key(self) -> bool:
        """Return True iff at least one of contract_id or session_id is non-empty."""
        return bool(self.contract_id) or bool(self.session_id)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "signal_kind": self.signal_kind.value,
            "contract_id": self.contract_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "signal_id": self.signal_id,
            "emission_seq": self.emission_seq,
            "result_kind": self.result_kind,
            "payload": dict(self.payload),
            "envelope_id": self.envelope_id,
            "received_at": self.received_at,
        }


# ---------------------------------------------------------------------------
# AndroidSignalReconcileOutcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidSignalReconcileOutcome:
    """Typed result of a single reconciliation attempt.

    Attributes
    ----------
    record
        The tracking record *after* reconciliation (may be the same object as
        before if was_updated is False).
    was_updated
        True iff the tracking record was actually mutated during this
        reconciliation attempt.
    reject_reason
        Non-empty string describing why reconciliation was skipped (no
        matching record found, both lookup keys absent, already terminal,
        etc.).  Empty string when reconciliation succeeded.
    envelope
        The :class:`AndroidExecutionSignalEnvelope` that was reconciled.
    """

    record: Optional[DelegatedExecutionTrackingRecord] = None
    was_updated: bool = False
    reject_reason: str = ""
    envelope: Optional[AndroidExecutionSignalEnvelope] = None

    def is_accepted(self) -> bool:
        """Return True iff reconciliation succeeded (was_updated and no reject_reason)."""
        return self.was_updated and not self.reject_reason

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "was_updated": self.was_updated,
            "reject_reason": self.reject_reason,
            "record": self.record.to_dict() if self.record is not None else None,
            "envelope": self.envelope.to_dict() if self.envelope is not None else None,
        }


# ---------------------------------------------------------------------------
# Signal-kind mapping table
# ---------------------------------------------------------------------------

# Mapping: (message_type_lower, task_status_lower) → AndroidSignalKind
#
# message_type is the AIP v3 MessageType string value.
# task_status is the AIP v3 TaskStatus / ResultStatus / raw "status" field value.
# Both keys are lowercased before lookup.  A None status is normalised to "".

_TYPE_STATUS_MAP: Dict[Tuple[str, str], AndroidSignalKind] = {
    # task_result
    ("task_result", "completed"):     AndroidSignalKind.final_result,
    ("task_result", "success"):       AndroidSignalKind.final_result,
    ("task_result", "failed"):        AndroidSignalKind.error,
    ("task_result", "failure"):       AndroidSignalKind.error,
    ("task_result", "cancelled"):     AndroidSignalKind.cancelled,
    ("task_result", "timeout"):       AndroidSignalKind.timeout,
    ("task_result", "running"):       AndroidSignalKind.progress,
    ("task_result", ""):              AndroidSignalKind.final_result,  # bare task_result → assume completion

    # task_progress
    ("task_progress", ""):            AndroidSignalKind.progress,
    ("task_progress", "running"):     AndroidSignalKind.progress,
    ("task_progress", "continue"):    AndroidSignalKind.progress,
    ("task_progress", "pending"):     AndroidSignalKind.ack,

    # task_end
    ("task_end", "completed"):        AndroidSignalKind.final_result,
    ("task_end", "success"):          AndroidSignalKind.final_result,
    ("task_end", "failed"):           AndroidSignalKind.error,
    ("task_end", "failure"):          AndroidSignalKind.error,
    ("task_end", "cancelled"):        AndroidSignalKind.cancelled,
    ("task_end", "timeout"):          AndroidSignalKind.timeout,
    ("task_end", ""):                 AndroidSignalKind.final_result,  # bare task_end → assume completion

    # goal_execution_result
    ("goal_execution_result", "completed"):  AndroidSignalKind.final_result,
    ("goal_execution_result", "success"):    AndroidSignalKind.final_result,
    ("goal_execution_result", "true"):       AndroidSignalKind.final_result,
    ("goal_execution_result", "failed"):     AndroidSignalKind.error,
    ("goal_execution_result", "failure"):    AndroidSignalKind.error,
    ("goal_execution_result", "false"):      AndroidSignalKind.error,
    ("goal_execution_result", "cancelled"):  AndroidSignalKind.cancelled,
    ("goal_execution_result", "timeout"):    AndroidSignalKind.timeout,
    ("goal_execution_result", ""):           AndroidSignalKind.final_result,

    # error
    ("error", ""):                    AndroidSignalKind.error,
    ("error", "timeout"):             AndroidSignalKind.timeout,
    ("error", "cancelled"):           AndroidSignalKind.cancelled,

    # agent_result
    ("agent_result", "completed"):    AndroidSignalKind.final_result,
    ("agent_result", "success"):      AndroidSignalKind.final_result,
    ("agent_result", "failed"):       AndroidSignalKind.error,
    ("agent_result", "failure"):      AndroidSignalKind.error,
    ("agent_result", "cancelled"):    AndroidSignalKind.cancelled,
    ("agent_result", "timeout"):      AndroidSignalKind.timeout,
    ("agent_result", ""):             AndroidSignalKind.final_result,

    # agent_status
    ("agent_status", "pending"):      AndroidSignalKind.ack,
    ("agent_status", "running"):      AndroidSignalKind.progress,
    ("agent_status", "continue"):     AndroidSignalKind.progress,
    ("agent_status", "completed"):    AndroidSignalKind.final_result,
    ("agent_status", "failed"):       AndroidSignalKind.error,
    ("agent_status", "cancelled"):    AndroidSignalKind.cancelled,
    ("agent_status", ""):             AndroidSignalKind.progress,

    # task_assign (host→Android) used as a receipt ACK in tests
    ("task_assign", "pending"):       AndroidSignalKind.ack,
    ("task_assign", ""):              AndroidSignalKind.ack,

    # parallel_result
    ("parallel_result", "completed"): AndroidSignalKind.final_result,
    ("parallel_result", "success"):   AndroidSignalKind.final_result,
    ("parallel_result", "failed"):    AndroidSignalKind.error,
    ("parallel_result", ""):          AndroidSignalKind.final_result,

    # delegated_execution_signal (PR-16 canonical ingress message type)
    # signal_kind is read directly from the payload field in this case;
    # these fallbacks handle the compat path via normalize_android_message_to_signal_kind.
    ("delegated_execution_signal", "ack"):        AndroidSignalKind.ack,
    ("delegated_execution_signal", "progress"):   AndroidSignalKind.progress,
    ("delegated_execution_signal", "result"):     AndroidSignalKind.final_result,
    ("delegated_execution_signal", "timeout"):    AndroidSignalKind.timeout,
    ("delegated_execution_signal", "cancelled"):  AndroidSignalKind.cancelled,
    ("delegated_execution_signal", "success"):    AndroidSignalKind.final_result,
    ("delegated_execution_signal", "failure"):    AndroidSignalKind.error,
    ("delegated_execution_signal", "completed"):  AndroidSignalKind.final_result,
    ("delegated_execution_signal", "failed"):     AndroidSignalKind.error,
    ("delegated_execution_signal", ""):           AndroidSignalKind.progress,
}

# Fallback: message_type only (status ignored / absent)
_TYPE_ONLY_MAP: Dict[str, AndroidSignalKind] = {
    "task_result":                  AndroidSignalKind.final_result,
    "task_end":                     AndroidSignalKind.final_result,
    "goal_execution_result":        AndroidSignalKind.final_result,
    "agent_result":                 AndroidSignalKind.final_result,
    "error":                        AndroidSignalKind.error,
    "task_progress":                AndroidSignalKind.progress,
    "agent_status":                 AndroidSignalKind.progress,
    "parallel_result":              AndroidSignalKind.final_result,
    "task_assign":                  AndroidSignalKind.ack,
    "device_register_ack":          AndroidSignalKind.ack,
    "heartbeat_ack":                AndroidSignalKind.ack,
    # PR-16 canonical ingress: bare delegated_execution_signal → progress (keep alive)
    "delegated_execution_signal":   AndroidSignalKind.progress,
}


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def normalize_android_message_to_signal_kind(
    message_type: str,
    status: Optional[str] = None,
) -> AndroidSignalKind:
    """Map an inbound Android AIP v3 ``(message_type, status)`` pair to a
    canonical :class:`AndroidSignalKind`.

    Parameters
    ----------
    message_type:
        AIP v3 message type string (e.g. ``"task_result"``, ``"error"``).
        Case-insensitive.
    status:
        The status field from the message or its payload (e.g. ``"completed"``,
        ``"failed"``).  ``None`` or empty string treated identically.

    Returns
    -------
    AndroidSignalKind
        Canonical signal kind.  Falls back to ``AndroidSignalKind.progress``
        for unrecognised pairs (per
        ``RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY``).
    """
    msg_type_key = (message_type or "").lower().strip()
    status_key = (status or "").lower().strip()

    # Try exact (type, status) pair first
    kind = _TYPE_STATUS_MAP.get((msg_type_key, status_key))
    if kind is not None:
        return kind

    # Try type-only fallback
    kind = _TYPE_ONLY_MAP.get(msg_type_key)
    if kind is not None:
        return kind

    # Default: keep record alive as in_progress
    return AndroidSignalKind.progress


def extract_signal_envelope(
    message: Dict[str, Any],
) -> AndroidExecutionSignalEnvelope:
    """Extract a canonical :class:`AndroidExecutionSignalEnvelope` from a raw
    inbound AIP v3 message dict.

    Identity-field extraction strategy
    -----------------------------------
    * ``device_id``, ``task_id`` — resolved from top-level keys first, then
      from ``payload`` sub-dict as fallback.  Top-level takes precedence
      because these fields are top-level in the AIP v3 envelope spec.
    * ``contract_id``, ``session_id``, ``trace_id`` — resolved from
      ``payload`` sub-dict first, then from top-level keys as fallback.
      These are delegated-routing fields that Android sends inside the
      payload (conforming to the PR-12 Android-side delegated receipt
      envelope convention).

    Signal-kind resolution
    ----------------------
    ``message_type`` is read from ``message["type"]`` (falling back to empty
    string).  ``status`` is resolved preferentially from the raw ``"status"``
    field at the top level, then from ``payload["status"]``, then from
    ``payload["success"]`` (coerced to ``"true"``/``"false"``).  The resolved
    pair is fed to :func:`normalize_android_message_to_signal_kind`.

    Parameters
    ----------
    message:
        Raw inbound AIP v3 message dict from the WebSocket gateway layer.

    Returns
    -------
    AndroidExecutionSignalEnvelope
        Populated envelope ready for :func:`reconcile_android_execution_signal`.
    """
    payload: Dict[str, Any] = message.get("payload") or {}

    # ---- message_type ----
    message_type: str = str(message.get("type") or "")

    # ---- status resolution ----
    status: str = (
        str(message.get("status") or "")
        or str(payload.get("status") or "")
    )
    if not status:
        success_val = payload.get("success")
        if success_val is not None:
            status = "true" if success_val else "false"

    # ---- signal kind ----
    signal_kind = normalize_android_message_to_signal_kind(message_type, status)

    # ---- device_id, task_id — top-level first ----
    device_id: str = (
        str(message.get("device_id") or "")
        or str(payload.get("device_id") or "")
    )
    task_id: str = (
        str(message.get("task_id") or "")
        or str(payload.get("task_id") or "")
    )

    # ---- contract_id, session_id, trace_id — payload first ----
    contract_id: str = (
        str(payload.get("contract_id") or "")
        or str(message.get("contract_id") or "")
    )
    session_id: str = (
        str(payload.get("session_id") or "")
        or str(payload.get("runtime_session_id") or "")
        or str(message.get("session_id") or "")
        or str(message.get("runtime_session_id") or "")
    )
    trace_id: str = (
        str(payload.get("trace_id") or "")
        or str(message.get("trace_id") or "")
    )

    # ---- signal_id, emission_seq, result_kind (PR-16 fields) — payload first ----
    signal_id: str = (
        str(payload.get("signal_id") or "")
        or str(message.get("signal_id") or "")
    )
    raw_emission_seq = (
        payload.get("emission_seq")
        if payload.get("emission_seq") is not None
        else message.get("emission_seq")
    )
    try:
        emission_seq: int = int(raw_emission_seq) if raw_emission_seq is not None else 0
    except (TypeError, ValueError):
        emission_seq = 0
    result_kind: str = (
        str(payload.get("result_kind") or "")
        or str(message.get("result_kind") or "")
    )

    # ---- payload snapshot — merge top-level extras + payload dict ----
    # Keys harvested from the payload sub-dict into the envelope snapshot.
    _PAYLOAD_CONTENT_KEYS = (
        "result", "details", "error", "error_message", "latency_ms",
        "step_count", "partial_result",
    )
    payload_snapshot: Dict[str, Any] = {}
    for key in _PAYLOAD_CONTENT_KEYS:
        if payload.get(key) is not None:
            payload_snapshot[key] = payload[key]
    if status:
        payload_snapshot["status"] = status
    if task_id:
        payload_snapshot["task_id"] = task_id
    if device_id:
        payload_snapshot["device_id"] = device_id
    if trace_id:
        payload_snapshot["trace_id"] = trace_id
    if contract_id:
        payload_snapshot["contract_id"] = contract_id

    return AndroidExecutionSignalEnvelope(
        signal_kind=signal_kind,
        contract_id=contract_id,
        session_id=session_id,
        device_id=device_id,
        trace_id=trace_id,
        task_id=task_id,
        signal_id=signal_id,
        emission_seq=emission_seq,
        result_kind=result_kind,
        payload=payload_snapshot,
    )


def reconcile_android_execution_signal(
    envelope: AndroidExecutionSignalEnvelope,
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> AndroidSignalReconcileOutcome:
    """Canonical reconciliation entry-point.

    Accepts an :class:`AndroidExecutionSignalEnvelope`, resolves the
    :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionTrackingRecord`
    by ``contract_id`` (preferred) or ``session_id`` (fallback), applies the
    appropriate signal, and returns an :class:`AndroidSignalReconcileOutcome`.

    Reconciliation steps
    --------------------
    1. Reject immediately if ``envelope.has_lookup_key()`` is False (both
       ``contract_id`` and ``session_id`` are empty).
    2. Look up the tracking record:
       a. By ``contract_id`` if non-empty (uses
          ``DelegatedExecutionTrackingRuntime.get_latest_for_contract``).
       b. By ``session_id`` as fallback (uses
          ``DelegatedExecutionTrackingRuntime.get_latest_for_session``).
    3. If no record is found, return outcome with ``was_updated=False``.
    4. If the record is already in a terminal phase, return it unchanged with
       ``was_updated=False``.
    5. Apply :func:`~core.delegated_runtime_execution_tracker.apply_acknowledgment_signal`
       with the envelope's :class:`AcknowledgmentSignal` equivalent.
    6. For ``final_result`` and ``error`` signal kinds, additionally call
       :func:`~core.delegated_runtime_execution_tracker.apply_result` to
       populate the typed :class:`~core.delegated_runtime_execution_tracker.DelegatedExecutionResult`
       (per ``RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY``).
    7. Return :class:`AndroidSignalReconcileOutcome` with the updated record and
       ``was_updated=True``.

    Parameters
    ----------
    envelope:
        The signal envelope to reconcile.
    runtime:
        Optional ring-buffer instance for test isolation.  Uses process
        singleton if None.

    Returns
    -------
    AndroidSignalReconcileOutcome
        Reconciliation result.
    """
    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()

    # Step 1 — reject without lookup key
    if not envelope.has_lookup_key():
        return AndroidSignalReconcileOutcome(
            record=None,
            was_updated=False,
            reject_reason=(
                "reconciliation requires at least one of contract_id or session_id; "
                "both are empty in this envelope"
            ),
            envelope=envelope,
        )

    # Step 2 — look up tracking record
    record: Optional[DelegatedExecutionTrackingRecord] = None
    if envelope.contract_id:
        record = _runtime.get_latest_for_contract(envelope.contract_id)
    if record is None and envelope.session_id:
        record = _runtime.get_latest_for_session(envelope.session_id)

    # Step 3 — miss
    if record is None:
        lookup_desc = (
            f"contract_id={envelope.contract_id!r}"
            if envelope.contract_id
            else f"session_id={envelope.session_id!r}"
        )
        return AndroidSignalReconcileOutcome(
            record=None,
            was_updated=False,
            reject_reason=(
                f"no tracking record found for {lookup_desc}; "
                "signal cannot be reconciled against an unknown execution"
            ),
            envelope=envelope,
        )

    # Step 4 — already terminal
    if record.phase.is_terminal():
        return AndroidSignalReconcileOutcome(
            record=record,
            was_updated=False,
            reject_reason=(
                f"tracking record is already in terminal phase {record.phase.value!r}; "
                "further signals are ignored per TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY"
            ),
            envelope=envelope,
        )

    # Step 5/6 — apply the appropriate update based on signal kind
    # For final_result and error: call apply_result() directly (which sets both
    # the phase AND the result field atomically, per PR-10 apply_result semantics).
    # For all other signals: call apply_acknowledgment_signal().
    if envelope.signal_kind in (AndroidSignalKind.final_result, AndroidSignalKind.error):
        is_success = envelope.signal_kind == AndroidSignalKind.final_result
        error_detail: str = ""
        if not is_success:
            error_detail = (
                str(envelope.payload.get("error_message") or "")
                or str(envelope.payload.get("error") or "")
                or str(envelope.payload.get("details") or "")
                or "android execution error"
            )
        result_payload: Dict[str, Any] = {
            k: v for k, v in envelope.payload.items()
            if k not in ("contract_id", "session_id", "device_id", "trace_id")
        }
        result_obj = DelegatedExecutionResult(
            success=is_success,
            result_payload=result_payload,
            error_detail=error_detail,
            completed_at=time.time(),
        )
        updated = apply_result(record, result_obj, runtime=_runtime)
    else:
        # Non-terminal signal: apply acknowledgment signal (ack/progress/partial_result/
        # timeout/cancelled)
        ack_signal: AcknowledgmentSignal = envelope.signal_kind.to_ack_signal()
        updated = apply_acknowledgment_signal(
            record,
            ack_signal,
            payload=dict(envelope.payload),
            runtime=_runtime,
        )

    return AndroidSignalReconcileOutcome(
        record=updated,
        was_updated=True,
        reject_reason="",
        envelope=envelope,
    )


def reconcile_inbound_message(
    message: Dict[str, Any],
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> AndroidSignalReconcileOutcome:
    """Convenience wrapper: extract envelope from *message* and reconcile.

    This is the single-call entry-point intended for use by gateway handlers.
    It combines :func:`extract_signal_envelope` and
    :func:`reconcile_android_execution_signal`.

    Parameters
    ----------
    message:
        Raw inbound AIP v3 message dict from the WebSocket gateway layer.
    runtime:
        Optional ring-buffer instance for test isolation.  Uses process
        singleton if None.

    Returns
    -------
    AndroidSignalReconcileOutcome
        Reconciliation result (``was_updated=False`` when no matching record is
        found or when the inbound message cannot be correlated).
    """
    envelope = extract_signal_envelope(message)
    return reconcile_android_execution_signal(envelope, runtime=runtime)
