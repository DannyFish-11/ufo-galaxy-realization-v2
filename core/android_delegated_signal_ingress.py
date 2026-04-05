"""core/android_delegated_signal_ingress.py
===========================================
PR package 16 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Ingress Path for Android Delegated Execution Signals.

Background
----------
PR-13 established ``core.android_execution_signal_reconciler`` as the
host-side reconciliation binding for inbound Android execution signals.
That module supports a compatibility extraction path that infers
:class:`~core.android_execution_signal_reconciler.AndroidSignalKind` from
``(message_type, status)`` pairs carried by legacy message types such as
``task_result``, ``task_end``, and ``goal_execution_result``.

As Android PR-16 wires true outbound delegated execution signal transport,
the Android runtime begins emitting a dedicated ``delegated_execution_signal``
message type whose payload carries all identity and signal metadata as
first-class structured fields rather than relying on implicit status
inference.  These messages carry:

* ``signal_kind`` — the lifecycle signal kind (``ack`` / ``progress`` /
  ``result`` / ``timeout`` / ``cancelled``) as an explicit enum field.
* ``result_kind`` — for ``result``-kind signals, whether the outcome was
  ``success`` or ``failure``.
* ``signal_id`` — a UUID assigned by Android to this specific signal
  emission for idempotency / recovery purposes.
* ``emission_seq`` — a monotonically increasing emission sequence counter
  within the delegated execution lifetime for ordering / out-of-order
  detection.

This module provides the **canonical ingress path** that:

1. Recognises ``delegated_execution_signal`` messages as a first-class
   input (not a generic compat message).
2. Extracts all nine identity / signal fields from the message without
   implicit inference.
3. Normalises the inbound message to a
   :class:`DelegatedExecutionSignalEnvelope` that extends the base
   :class:`~core.android_execution_signal_reconciler.AndroidExecutionSignalEnvelope`
   concept with the new ``signal_id``, ``emission_seq``, and ``result_kind``
   fields.
4. Converts ``DelegatedSignalKind`` + ``ResultKind`` to the canonical
   :class:`~core.android_execution_signal_reconciler.AndroidSignalKind`
   understood by the PR-13 reconciler.
5. Delegates to :func:`~core.android_execution_signal_reconciler.reconcile_android_execution_signal`
   as the single canonical reconciliation entry-point.
6. Returns an :class:`~core.android_execution_signal_reconciler.AndroidSignalReconcileOutcome`
   so the calling gateway handler receives a typed, inspectable result.

Public API summary
------------------
Enums::

    DelegatedSignalKind  — ack / progress / result / timeout / cancelled
    ResultKind           — success / failure / unknown

Dataclass::

    DelegatedExecutionSignalEnvelope  — canonical carrier with all nine fields

Functions::

    extract_delegated_signal_envelope(message) -> DelegatedExecutionSignalEnvelope
    ingest_delegated_execution_signal(message, *, runtime=None) -> AndroidSignalReconcileOutcome

Ten policy sentinels documenting canonical ingress rules.

One PR sentinel (``ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL``).

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Explicit over implicit** — ``signal_kind`` and ``result_kind`` are read
  directly from structured payload fields; no inference from message_type or
  status strings.
- **Identity-preserving** — all nine identity fields flow verbatim from the
  inbound message through the envelope to the tracker.
- **Single reconcile path** — after extraction this module calls the
  established :func:`~core.android_execution_signal_reconciler.reconcile_android_execution_signal`
  function and returns its outcome unchanged.
- **Non-destructive on miss** — when no matching tracker record exists the
  reconciler returns ``was_updated=False``; this module propagates that
  outcome without creating phantom records.

PR package numbering
--------------------
Package 16 of the post-533 dual-repo runtime unification master plan.
MAIN-repo side only.  Android-repo side (PR-16) wires true outbound delegated
execution signal transport; this module consumes the signals produced by that
path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Imports from prior PR packages
# ---------------------------------------------------------------------------

from core.android_execution_signal_reconciler import (
    AndroidExecutionSignalEnvelope,
    AndroidSignalKind,
    AndroidSignalReconcileOutcome,
    reconcile_android_execution_signal,
)
from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY: str = (
    "core.android_delegated_signal_ingress::PR16::canonical-ingress-for-"
    "android-delegated-execution-signals"
)

# ---------------------------------------------------------------------------
# Policy sentinels — document canonical ingress rules
# ---------------------------------------------------------------------------

INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY: str = (
    "INGRESS_POLICY::INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL: "
    "The 'delegated_execution_signal' message type is the canonical ingress "
    "format for Android delegated execution lifecycle signals.  Gateway "
    "handlers MUST route messages of this type to "
    "ingest_delegated_execution_signal() rather than to the legacy "
    "reconcile_inbound_message() compatibility path."
)

INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY: str = (
    "INGRESS_POLICY::INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD: "
    "For 'delegated_execution_signal' messages the signal kind is read "
    "directly from the 'signal_kind' field in the message payload.  It MUST "
    "NOT be inferred from (message_type, status) pairs."
)

INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY: str = (
    "INGRESS_POLICY::INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS: "
    "When DelegatedSignalKind.result is present the 'result_kind' field "
    "distinguishes success (→ AndroidSignalKind.final_result) from failure "
    "(→ AndroidSignalKind.error).  Absent or unknown result_kind defaults to "
    "final_result (optimistic)."
)

INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY: str = (
    "INGRESS_POLICY::INGRESS_SIGNAL_ID_IS_PRESERVED: "
    "The 'signal_id' field from the inbound delegated signal message is "
    "extracted verbatim and carried on DelegatedExecutionSignalEnvelope.  "
    "The ingress path MUST NOT replace or synthesise signal_id values."
)

INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY: str = (
    "INGRESS_POLICY::INGRESS_EMISSION_SEQ_IS_PRESERVED: "
    "The 'emission_seq' integer from the inbound delegated signal message is "
    "extracted verbatim and carried on DelegatedExecutionSignalEnvelope.  "
    "A missing or non-integer emission_seq defaults to 0 without rejection."
)

INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY: str = (
    "INGRESS_POLICY::INGRESS_IDENTITY_FIELDS_ARE_VERBATIM: "
    "contract_id, session_id, device_id, trace_id, and task_id are extracted "
    "from the inbound message using the same priority rules as "
    "extract_signal_envelope() in the PR-13 reconciler: device_id and task_id "
    "from top-level first then payload; contract_id, session_id, trace_id "
    "from payload first then top-level."
)

INGRESS_REQUIRES_LOOKUP_KEY_POLICY: str = (
    "INGRESS_POLICY::INGRESS_REQUIRES_LOOKUP_KEY: "
    "A delegated execution signal ingestion attempt MUST carry at least one "
    "of contract_id or session_id to resolve the host-side tracking record.  "
    "Messages with both fields absent are passed to reconcile_android_execution_signal() "
    "which returns was_updated=False with a reject_reason."
)

INGRESS_DELEGATES_TO_RECONCILER_POLICY: str = (
    "INGRESS_POLICY::INGRESS_DELEGATES_TO_RECONCILER: "
    "After extraction and normalisation the canonical ingress path calls "
    "reconcile_android_execution_signal() from PR-13 as the single "
    "authoritative reconcile entry-point.  The ingress path MUST NOT "
    "directly manipulate the execution tracker."
)

INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY: str = (
    "INGRESS_POLICY::INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND: "
    "The host-side tracker phase transition produced by "
    "ingest_delegated_execution_signal() is guaranteed to be consistent with "
    "the DelegatedSignalKind in the envelope: "
    "ack→acknowledged, progress→in_progress, result/success→completed, "
    "result/failure→failed, timeout→timed_out, cancelled→cancelled."
)

INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY: str = (
    "INGRESS_POLICY::INGRESS_NON_DESTRUCTIVE_ON_MISS: "
    "When no matching execution tracking record is found for the lookup key "
    "the ingestion returns AndroidSignalReconcileOutcome(was_updated=False) "
    "without creating a phantom record or raising an exception."
)

_ALL_INGRESS_POLICIES = (
    INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY,
    INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY,
    INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY,
    INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY,
    INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY,
    INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
    INGRESS_REQUIRES_LOOKUP_KEY_POLICY,
    INGRESS_DELEGATES_TO_RECONCILER_POLICY,
    INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY,
    INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY,
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL: str = (
    "android_delegated_signal_ingress::package=16::pr=post533-pr16-main::"
    "canonical-ingress-for-android-delegated-execution-signals::"
    "authority=ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY"
)

# ---------------------------------------------------------------------------
# DelegatedSignalKind enum
# ---------------------------------------------------------------------------


class DelegatedSignalKind(str, Enum):
    """Canonical kind of an Android delegated execution lifecycle signal.

    This enum maps the ``signal_kind`` field emitted by the Android runtime
    in ``delegated_execution_signal`` messages.  It is **distinct** from
    :class:`~core.android_execution_signal_reconciler.AndroidSignalKind`
    (which includes the ``partial_result`` and ``error`` values used only
    after result-kind disambiguation).

    Values
    ------
    ack
        Initial receipt acknowledgment — Android accepted the delegated task.
    progress
        In-progress heartbeat or status update.
    result
        Execution has produced a final outcome (success or failure).
        Requires :class:`ResultKind` disambiguation to determine the
        canonical :class:`AndroidSignalKind`.
    timeout
        A timeout was detected.
    cancelled
        Execution was cancelled.
    """

    ack = "ack"
    progress = "progress"
    result = "result"
    timeout = "timeout"
    cancelled = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> "DelegatedSignalKind":
        """Return the matching kind or ``progress`` as safe default."""
        if not isinstance(value, str):
            return cls.progress
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.progress

    def is_terminal(self) -> bool:
        """Return True iff this kind will advance the tracker to a terminal phase."""
        return self in (
            DelegatedSignalKind.result,
            DelegatedSignalKind.timeout,
            DelegatedSignalKind.cancelled,
        )


# ---------------------------------------------------------------------------
# ResultKind enum
# ---------------------------------------------------------------------------


class ResultKind(str, Enum):
    """Outcome discriminator for ``DelegatedSignalKind.result`` signals.

    When an Android delegated execution signal carries
    ``signal_kind="result"``, the ``result_kind`` field in the payload
    disambiguates whether the execution succeeded or failed.

    Values
    ------
    success
        Execution completed successfully.
    failure
        Execution encountered an error or produced a failure outcome.
    unknown
        ``result_kind`` was absent or unrecognised; treated as ``success``
        by :func:`extract_delegated_signal_envelope` per the
        ``INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY``
        (optimistic default).
    """

    success = "success"
    failure = "failure"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ResultKind":
        """Return the matching kind or ``unknown`` as default."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# Mapping: (DelegatedSignalKind, ResultKind) → AndroidSignalKind
# ---------------------------------------------------------------------------

# Payload content keys harvested from the payload sub-dict into the envelope
# snapshot during extraction.
_DELEGATED_PAYLOAD_CONTENT_KEYS: tuple = (
    "result", "details", "error", "error_message", "latency_ms",
    "step_count", "partial_result",
)


def _resolve_android_signal_kind(
    signal_kind: DelegatedSignalKind,
    result_kind: ResultKind,
) -> AndroidSignalKind:
    """Map ``(DelegatedSignalKind, ResultKind)`` to :class:`AndroidSignalKind`.

    This is the canonical conversion table per
    ``INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY``.
    """
    if signal_kind == DelegatedSignalKind.ack:
        return AndroidSignalKind.ack
    if signal_kind == DelegatedSignalKind.progress:
        return AndroidSignalKind.progress
    if signal_kind == DelegatedSignalKind.result:
        if result_kind == ResultKind.failure:
            return AndroidSignalKind.error
        # success or unknown → optimistic final_result
        return AndroidSignalKind.final_result
    if signal_kind == DelegatedSignalKind.timeout:
        return AndroidSignalKind.timeout
    if signal_kind == DelegatedSignalKind.cancelled:
        return AndroidSignalKind.cancelled
    # Safety default — should not be reached given enum exhaustion
    return AndroidSignalKind.progress  # pragma: no cover


# ---------------------------------------------------------------------------
# DelegatedExecutionSignalEnvelope dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegatedExecutionSignalEnvelope:
    """Canonical carrier for a single inbound Android delegated execution signal.

    This dataclass extends the ``AndroidExecutionSignalEnvelope`` concept with
    three new fields introduced by Android PR-16's structured
    ``delegated_execution_signal`` message format:

    * ``signal_id`` — UUID assigned by Android to uniquely identify this
      signal emission (supports idempotency / duplicate detection).
    * ``emission_seq`` — monotonically increasing emission sequence counter
      within the delegated execution lifetime (supports ordering / out-of-order
      detection).
    * ``result_kind`` — :class:`ResultKind` that disambiguates ``result``-kind
      signals between success and failure.

    Together with the five identity fields (``contract_id``, ``session_id``,
    ``device_id``, ``trace_id``, ``task_id``), ``signal_kind`` as a
    :class:`DelegatedSignalKind`, and the derived
    ``resolved_android_signal_kind`` this dataclass is the stable, typed
    carrier between the canonical ingress path and the PR-13 reconciler.

    Attributes
    ----------
    signal_kind
        The :class:`DelegatedSignalKind` read directly from the message
        ``signal_kind`` field.
    result_kind
        :class:`ResultKind` from the message ``result_kind`` field.  Only
        meaningful when ``signal_kind == DelegatedSignalKind.result``.
    contract_id
        Handoff contract identifier.
    session_id
        Attached runtime session / runtime session identifier.
    device_id
        Source Android device identifier.
    trace_id
        Distributed trace identifier.
    task_id
        Task identifier.
    signal_id
        UUID assigned by Android to this specific signal emission.
    emission_seq
        Emission sequence counter (0-based, monotonically increasing).
    payload
        Opaque payload snapshot forwarded to the PR-13 reconciler.
    envelope_id
        Auto-generated UUID for this envelope instance (audit / correlation).
    received_at
        Unix timestamp when this envelope was created on the host.
    resolved_android_signal_kind
        The :class:`AndroidSignalKind` derived from ``signal_kind`` +
        ``result_kind`` by :func:`_resolve_android_signal_kind`.  Populated
        automatically at construction time via ``__post_init__``.
    """

    signal_kind: DelegatedSignalKind = DelegatedSignalKind.progress
    result_kind: ResultKind = ResultKind.unknown
    contract_id: str = ""
    session_id: str = ""
    device_id: str = ""
    trace_id: str = ""
    task_id: str = ""
    signal_id: str = ""
    emission_seq: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    received_at: float = field(default_factory=time.time)
    # Derived field — set by __post_init__
    resolved_android_signal_kind: AndroidSignalKind = field(
        default=AndroidSignalKind.progress,
        compare=False,
    )

    def __post_init__(self) -> None:
        # Frozen dataclass — use object.__setattr__ to set the derived field.
        object.__setattr__(
            self,
            "resolved_android_signal_kind",
            _resolve_android_signal_kind(self.signal_kind, self.result_kind),
        )

    def has_lookup_key(self) -> bool:
        """Return True iff at least one of contract_id or session_id is non-empty."""
        return bool(self.contract_id) or bool(self.session_id)

    def to_android_execution_signal_envelope(self) -> AndroidExecutionSignalEnvelope:
        """Convert to :class:`AndroidExecutionSignalEnvelope` for reconciliation.

        This bridges the PR-16 canonical ingress envelope to the PR-13
        reconciler's envelope type, propagating all shared fields plus
        surfacing ``signal_id`` and ``emission_seq`` in the ``payload``
        snapshot so the tracker record can carry them for audit purposes.
        """
        payload_with_meta: Dict[str, Any] = dict(self.payload)
        if self.signal_id:
            payload_with_meta["signal_id"] = self.signal_id
        if self.emission_seq:
            payload_with_meta["emission_seq"] = self.emission_seq
        if self.result_kind != ResultKind.unknown:
            payload_with_meta["result_kind"] = self.result_kind.value
        return AndroidExecutionSignalEnvelope(
            signal_kind=self.resolved_android_signal_kind,
            contract_id=self.contract_id,
            session_id=self.session_id,
            device_id=self.device_id,
            trace_id=self.trace_id,
            task_id=self.task_id,
            payload=payload_with_meta,
            signal_id=self.signal_id,
            emission_seq=self.emission_seq,
            result_kind=self.result_kind.value,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "signal_kind": self.signal_kind.value,
            "result_kind": self.result_kind.value,
            "contract_id": self.contract_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "signal_id": self.signal_id,
            "emission_seq": self.emission_seq,
            "payload": dict(self.payload),
            "envelope_id": self.envelope_id,
            "received_at": self.received_at,
            "resolved_android_signal_kind": self.resolved_android_signal_kind.value,
        }


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def extract_delegated_signal_envelope(
    message: Dict[str, Any],
) -> DelegatedExecutionSignalEnvelope:
    """Extract a canonical :class:`DelegatedExecutionSignalEnvelope` from a
    raw inbound ``delegated_execution_signal`` message dict.

    Extraction strategy
    -------------------
    * ``device_id``, ``task_id`` — top-level keys first, then ``payload``
      sub-dict as fallback (consistent with PR-13 ``extract_signal_envelope``).
    * ``contract_id``, ``session_id``, ``trace_id`` — ``payload`` sub-dict
      first, then top-level keys as fallback (delegated routing fields).
    * ``signal_kind`` — ``payload.signal_kind`` first, then top-level
      ``signal_kind``; parsed as :class:`DelegatedSignalKind`.
    * ``result_kind`` — ``payload.result_kind`` first, then top-level
      ``result_kind``; parsed as :class:`ResultKind`.
    * ``signal_id`` — ``payload.signal_id`` first, then top-level
      ``signal_id``; defaults to empty string.
    * ``emission_seq`` — ``payload.emission_seq`` first, then top-level
      ``emission_seq``; coerced to int, defaults to 0.

    Parameters
    ----------
    message:
        Raw inbound message dict from the WebSocket gateway layer.

    Returns
    -------
    DelegatedExecutionSignalEnvelope
        Populated envelope ready for :func:`ingest_delegated_execution_signal`.
    """
    payload: Dict[str, Any] = message.get("payload") or {}

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

    # ---- signal_kind — payload first ----
    raw_signal_kind: str = (
        str(payload.get("signal_kind") or "")
        or str(message.get("signal_kind") or "")
    )
    signal_kind = DelegatedSignalKind.from_string(raw_signal_kind)

    # ---- result_kind — payload first ----
    raw_result_kind: str = (
        str(payload.get("result_kind") or "")
        or str(message.get("result_kind") or "")
    )
    result_kind = ResultKind.from_string(raw_result_kind)

    # ---- signal_id — payload first ----
    signal_id: str = (
        str(payload.get("signal_id") or "")
        or str(message.get("signal_id") or "")
    )

    # ---- emission_seq — payload first, coerced to int ----
    raw_emission_seq = (
        payload.get("emission_seq")
        if payload.get("emission_seq") is not None
        else message.get("emission_seq")
    )
    try:
        emission_seq: int = int(raw_emission_seq) if raw_emission_seq is not None else 0
    except (TypeError, ValueError):
        emission_seq = 0

    # ---- payload snapshot ----
    payload_snapshot: Dict[str, Any] = {}
    for key in _DELEGATED_PAYLOAD_CONTENT_KEYS:
        if payload.get(key) is not None:
            payload_snapshot[key] = payload[key]
    if task_id:
        payload_snapshot["task_id"] = task_id
    if device_id:
        payload_snapshot["device_id"] = device_id
    if trace_id:
        payload_snapshot["trace_id"] = trace_id
    if contract_id:
        payload_snapshot["contract_id"] = contract_id

    return DelegatedExecutionSignalEnvelope(
        signal_kind=signal_kind,
        result_kind=result_kind,
        contract_id=contract_id,
        session_id=session_id,
        device_id=device_id,
        trace_id=trace_id,
        task_id=task_id,
        signal_id=signal_id,
        emission_seq=emission_seq,
        payload=payload_snapshot,
    )


def ingest_delegated_execution_signal(
    message: Dict[str, Any],
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> AndroidSignalReconcileOutcome:
    """Canonical ingress entry-point for Android delegated execution signals.

    This is the **single authoritative function** that gateway handlers MUST
    call when a ``delegated_execution_signal`` message arrives.  It:

    1. Extracts a :class:`DelegatedExecutionSignalEnvelope` via
       :func:`extract_delegated_signal_envelope`.
    2. Converts the delegated envelope to an
       :class:`~core.android_execution_signal_reconciler.AndroidExecutionSignalEnvelope`
       understood by the PR-13 reconciler.
    3. Calls :func:`~core.android_execution_signal_reconciler.reconcile_android_execution_signal`
       as the canonical reconcile entry-point.
    4. Returns the :class:`~core.android_execution_signal_reconciler.AndroidSignalReconcileOutcome`
       unchanged.

    Parameters
    ----------
    message:
        Raw inbound ``delegated_execution_signal`` message dict from the
        WebSocket gateway layer.
    runtime:
        Optional ring-buffer instance for test isolation.  Uses process
        singleton if None.

    Returns
    -------
    AndroidSignalReconcileOutcome
        Reconciliation result (``was_updated=False`` when no matching record
        is found or when the inbound message cannot be correlated).

    Raises
    ------
    Does not raise.  All errors during extraction or reconciliation are
    handled gracefully: extraction yields safe defaults for missing fields;
    reconciliation returns ``was_updated=False`` with a ``reject_reason``
    rather than raising.
    """
    delegated_envelope = extract_delegated_signal_envelope(message)
    android_envelope = delegated_envelope.to_android_execution_signal_envelope()
    return reconcile_android_execution_signal(android_envelope, runtime=runtime)
