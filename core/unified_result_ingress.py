"""core/unified_result_ingress.py
==================================
PR-UNIFY: Unified Result Ingress — single canonical entry point for ALL task
result signals arriving from any source channel.

Background
----------
Prior to this module, task results entered V2 through at least five distinct
paths, each with its own idempotency logic, status mapping, truth-chain
invocation, and completion-linkage behaviour:

1. canonical WS ``goal_execution_result`` (galaxy_gateway android_bridge)
2. compat WS ``task_result`` / ``goal_result``            (core/api_routes.py)
3. REST POST /api/v1/tasks/{task_id}/result               (core/routes/tasks.py)
4. Android offline-replay ``goal_execution_result``       (compat WS path)
5. delegated / handoff result callbacks                   (various)

Each path had its own divergence points: some ran the four-step truth chain,
some only updated ``task_queue``, and none guaranteed that the
``CanonicalCompletionIngress`` awaiter was unblocked.

This module closes all of these gaps by defining:

* :class:`NormalizedResultEvent` — the **canonical result schema** that all
  result sources must produce before the processing chain runs.  Any source
  channel that cannot produce this schema must be updated so that it can.

* :class:`UnifiedResultIngress` — the **single processing chain** that all
  normalized result events are driven through:
    1. idempotency check / record
    2. status mapping (Android taxonomy → V2 canonical)
    3. truth chain  (four-step: truth_ingress, reconcile, lifecycle, completion)
    4. CanonicalTaskRuntime lifecycle update
    5. CanonicalCompletionIngress notify / awaiter unblock
    6. store_task_result / memory backflow
    7. structured visibility logging

* :func:`ingest_result` — the module-level convenience wrapper that callers
  use in place of all previous per-path handlers.

Authority contract
------------------
``UNIFIED_RESULT_INGRESS_POLICY`` is an importable sentinel asserting that
*this module is the canonical result ingress* and that no other module may
implement a competing result processing chain.

Source channels
---------------
All known result source channels are enumerated in :class:`ResultSourceChannel`.
Callers pass the appropriate channel so that the ingress chain can log and
route correctly.

Public API
----------
::

    UNIFIED_RESULT_INGRESS_POLICY                   (sentinel)
    ResultSourceChannel                             (enum)
    NormalizedResultEvent                           (dataclass)
    UnifiedResultIngressOutcome                     (dataclass)
    UnifiedResultIngress                            (class)
    get_unified_result_ingress()                    (singleton factory)
    ingest_result(event) -> UnifiedResultIngressOutcome   (module convenience)
"""

from __future__ import annotations

import logging
import os
import re
import time
import threading
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional

from core.continuity_adjudication import (
    adjudicate_continuity_legality_gate,
    adjudicate_duplicate_vs_first_accepted,
    adjudicate_stale_vs_current,
    build_continuity_adjudication_evidence,
)

logger = logging.getLogger("Galaxy.UnifiedResultIngress")

# Evidence verdicts that must block full closure in unified ingress.
EVIDENCE_CLOSURE_BLOCKING_VERDICTS = frozenset({"quarantine", "reject"})

# Replay ordering decisions that block canonical closure.
REPLAY_ORDERING_BLOCKING_DECISIONS = frozenset(
    {
        "reject_out_of_order",
        "reject_stale",
    }
)

ANDROID_RESULT_DEDUPE_MESSAGE_TYPES = frozenset(
    {
        "task_result",
        "goal_result",
        "goal_execution_result",
    }
)

ANDROID_RECONCILIATION_DEDUPE_MESSAGE_TYPES = frozenset(
    {
        "reconciliation_signal",
        "handoff_result",
        "handoff_failure",
        "handoff_envelope_v2_result",
        "device_state_snapshot",
        "device_execution_event",
    }
)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_RESULT_INGRESS_POLICY: str = (
    "UNIFIED_RESULT_INGRESS_V1: core/unified_result_ingress.py is the single "
    "canonical result ingress.  ALL result source channels (canonical WS, "
    "compat WS, REST callback, replay, delegated/handoff) MUST normalise their "
    "result signal into a NormalizedResultEvent and pass it to "
    "ingest_result() before any state mutation occurs.  No competing result "
    "processing chain is permitted."
)

UNIFIED_RESULT_INGRESS_REPLAY_ORDERING_POLICY: str = (
    "UNIFIED_RESULT_INGRESS_REPLAY_ORDERING_V1: For ResultSourceChannel.REPLAY "
    "events, replay ordering adjudication MUST run (Step 0.75) before idempotency "
    "recording and canonical closure adjudication.  Ordering evaluation uses the "
    "contract defined in core.offline_replay_ordering_contract "
    "(evaluate_replay_sequence / STALE_SEQ_WINDOW / OfflineReplayItemDecision).  "
    "Decisions reject_out_of_order and reject_stale MUST block canonical closure.  "
    "Decision ambiguous_authority (missing replay_item_id + replay_seq) MUST NOT "
    "silently promote to full canonical closure.  "
    "Missing ordering metadata produces visible evidence rather than silent acceptance.  "
    "Non-REPLAY channels are not subject to replay ordering adjudication."
)

ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY: str = (
    "ANDROID_CLOSURE_GRADE_ELIGIBILITY_V1: "
    "Only Android runtime payloads that (1) pass the strict uplink schema/contract "
    "gate (action='accept'), (2) carry all closure-critical identity fields "
    "(task_id, device_id), and (3) carry a canonical terminal normalized_status "
    "are eligible for closure-grade canonical credit.  Payloads that enter via the "
    "compat/degrade path (AndroidIngressPayloadGrade.COMPAT_DEGRADED) or that are "
    "hard-rejected (AndroidIngressPayloadGrade.NOT_CLOSURE_GRADE) MUST have "
    "closure_grade_eligible=False in both NormalizedResultEvent and "
    "UnifiedResultIngressOutcome.  Such payloads MUST NOT be promoted to "
    "is_fully_closed=True.  The degrade path exists for operational compatibility "
    "only and does not confer canonical closure truthfulness."
)

CLOSURE_CRITICAL_ANDROID_IDENTITY_FIELDS: FrozenSet[str] = frozenset(
    {
        "task_id",
        "device_id",
    }
)
"""Minimum identity fields that must be non-empty for an Android runtime result
to be considered closure-grade eligible.  Absence of any field in this set
implies the payload cannot be attributed to a specific canonical task+device
pair and therefore must not be credited as canonical closure."""


class AndroidIngressPayloadGrade(str, Enum):
    """Closure-grade classification for Android-originated ingress payloads.

    Explicitly distinguishes the quality tier of an inbound Android result
    payload so that downstream processing and closure adjudication can make
    truthful decisions based on real payload quality rather than permissive
    compat acceptance alone.

    This enum is the canonical vocabulary for the ``android_payload_grade``
    field on :class:`NormalizedResultEvent` and
    :class:`UnifiedResultIngressOutcome`.
    """

    CANONICAL = "canonical"
    """Payload passed the strict schema gate (action='accept') and carries all
    closure-critical identity fields.  Eligible for full canonical closure."""

    COMPAT_DEGRADED = "compat_degraded"
    """Payload was accepted via the compat/degrade path (e.g. missing schema
    metadata, legacy format, or degraded dedupe contract).  Ineligible for
    closure-grade canonical credit; MUST NOT be treated as full canonical
    closure (is_fully_closed must remain False)."""

    WEAK_IDENTITY = "weak_identity"
    """Schema gate passed but one or more closure-critical identity fields are
    absent (e.g. missing task_id or device_id).  Ineligible for closure-grade
    canonical credit."""

    NOT_CLOSURE_GRADE = "not_closure_grade"
    """Payload was explicitly classified as not eligible for closure-grade
    handling (e.g. hard gate reject, absent terminal status)."""

    UNCLASSIFIED = "unclassified"
    """No closure-grade classification has been applied.  Used when the Android
    ingress gate assessment was unavailable or not performed.  Payloads in this
    state are treated as closure-grade eligible by default (backward compat)."""


# ---------------------------------------------------------------------------
# ResultSourceChannel
# ---------------------------------------------------------------------------


class ResultSourceChannel(str, Enum):
    """All known result source channels."""

    CANONICAL_WS = "canonical_ws"
    """Canonical WebSocket path through android_bridge / goal_execution handler."""

    COMPAT_WS = "compat_ws"
    """Compat WebSocket path through core/api_routes.py device_websocket."""

    REST_CALLBACK = "rest_callback"
    """REST POST /api/v1/tasks/{task_id}/result endpoint."""

    REPLAY = "replay"
    """Android OfflineTaskQueue offline-replay drain."""

    DELEGATED = "delegated"
    """Delegated execution / handoff result callback."""

    LOCAL = "local"
    """本地执行链路结果 — 来自 core/local_execution_chain.py 的本地执行结果。
    Local execution chain result from core/local_execution_chain.py record_local_execution()."""

    UNKNOWN = "unknown"
    """Unclassified source — must NOT be used for production paths."""


# ---------------------------------------------------------------------------
# NormalizedResultEvent
# ---------------------------------------------------------------------------


@dataclass
class NormalizedResultEvent:
    """Canonical result schema.  All result sources MUST produce this before
    the processing chain runs.

    Required fields
    ---------------
    ``task_id``, ``device_id``, ``raw_message_type``,
    ``normalized_result_kind``, ``normalized_status``, ``source_channel``.

    Optional / context fields
    -------------------------
    ``payload``, ``runtime_session_id``, ``runtime_attachment_session_id``,
    ``durable_session_id``, ``idempotency_key``, ``trace_id``,
    ``raw_message``.
    """

    # ── Core identity ────────────────────────────────────────────────────────
    task_id: str = ""
    """Canonical task identifier.  Empty for non-task result types."""

    device_id: str = ""
    """The device that produced this result."""

    participant_id: str = ""
    """Participant identity for task-level completion lineage.
    Defaults to ``device_id`` when a more specific participant identifier is absent."""

    raw_message_type: str = ""
    """The original ``type`` field from the inbound message before aliasing."""

    normalized_result_kind: str = ""
    """Normalised result kind — one of ``goal_execution_result``,
    ``task_result``, ``goal_result``, ``command_result``, etc."""

    normalized_status: str = ""
    """V2 canonical status — one of ``completed``, ``failed``, ``cancelled``,
    ``degraded``."""

    source_channel: ResultSourceChannel = ResultSourceChannel.UNKNOWN
    """Which ingress channel delivered this result."""

    # ── Payload ──────────────────────────────────────────────────────────────
    payload: Dict[str, Any] = field(default_factory=dict)
    """The full inbound payload dict (the original ``message`` or sub-payload)."""

    # ── Session / continuity context ─────────────────────────────────────────
    runtime_session_id: str = ""
    """Active runtime session identifier (if provided)."""

    runtime_attachment_session_id: str = ""
    """Runtime attachment session identifier (if provided)."""

    durable_session_id: str = ""
    """Durable / persistent session identifier (if provided)."""

    # ── Idempotency ──────────────────────────────────────────────────────────
    idempotency_key: str = ""
    """Durable idempotency key used to de-duplicate replay.  Defaults to
    ``<normalized_result_kind>:<task_id>`` when not explicitly set."""

    # ── Trace / observability ────────────────────────────────────────────────
    trace_id: str = ""
    """Trace/correlation identifier (if provided by the source)."""

    completion_emission_id: str = ""
    """Stable identity for the emitted terminal completion signal.
    Defaults to the first available completion-ish identifier from payload /
    raw_message (for example ``completion_emission_id``, ``handoff_id``,
    ``result_id``, ``message_id``) and falls back to ``<kind>:<status>``."""

    # ── Raw message (for downstream helpers that need the full envelope) ─────
    raw_message: Dict[str, Any] = field(default_factory=dict)
    """The complete inbound message dict before any normalisation."""

    # ── Session / continuity epoch ───────────────────────────────────────────
    session_epoch: Optional[int] = None
    """The ``continuity_epoch`` integer from the session that produced this result.
    When set, ``UnifiedResultIngress`` compares it against the canonical stored epoch
    for the device and classifies the result as stale when there is a mismatch.
    Absence (``None``) means epoch comparison is skipped (legacy/unknown path)."""

    is_stale: bool = False
    """Explicit stale flag.  Upstream callers (e.g. replay drain, reconnect handler)
    may pre-mark a result as stale before passing it to ``ingest_result()``.
    When ``True`` the result is immediately classified as stale by the ingress
    epoch gate and blocked from canonical closure adjudication."""

    stale_reason: str = ""
    """Human-readable reason string populated by the caller when ``is_stale=True``.
    Propagated verbatim into the stale evidence dict for diagnostics."""

    # ── Replay ordering metadata (required for REPLAY channel adjudication) ──
    replay_seq: Optional[int] = None
    """Sequence number from the Android offline replay queue.
    Required for replay ordering adjudication (Step 0.75).  When absent on a
    REPLAY channel event, the item cannot be positively confirmed in-order and
    the ordering decision is ``ambiguous_authority``.
    Android callers MUST populate this from ``OfflineTaskQueue`` item seq."""

    replay_session_id: str = ""
    """Session scope identifier for replay ordering.  Defines the boundary
    within which sequence numbers are compared for ordering enforcement.
    Defaults to ``runtime_session_id`` when not explicitly set by the caller.
    Android callers SHOULD populate this from the session that produced the
    queued item so that cross-session replays remain identifiable."""

    replay_item_id: str = ""
    """Unique item identifier from the Android offline replay queue.
    Required for per-item duplicate detection within a replay sequence.
    When absent, the ordering contract cannot apply duplicate-avoidance and
    classifies the item as ``ambiguous_authority``.
    Android callers MUST populate this from ``OfflineTaskQueue`` item id."""

    # ── Closure-grade eligibility ─────────────────────────────────────────────
    closure_grade_eligible: bool = True
    """Whether this payload is eligible for closure-grade canonical credit.

    Defaults to ``True`` for backward compatibility with callers that do not
    perform an explicit Android ingress gate assessment.

    Android gateway handlers (e.g. ``handle_goal_execution_result``) MUST set
    this to ``False`` when the uplink schema gate decision is ``action='degrade'``
    or ``action='reject'``, or when the payload is missing closure-critical
    identity fields per ``CLOSURE_CRITICAL_ANDROID_IDENTITY_FIELDS``.

    When ``False``, :class:`UnifiedResultIngress` will not set
    ``is_fully_closed=True`` even if all other processing steps succeed.
    Per ``ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY``."""

    android_payload_grade: str = ""
    """Closure-grade classification string from :class:`AndroidIngressPayloadGrade`.

    Set by Android gateway handlers to record how the uplink schema gate
    classified this payload.  Empty string means no explicit grade assessment
    was performed (treated as :attr:`AndroidIngressPayloadGrade.UNCLASSIFIED`
    for logging, but does not affect ``closure_grade_eligible``)."""

    @staticmethod
    def _first_available_text(*values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _derive_participant_id(self) -> str:
        return self._first_available_text(
            (self.payload or {}).get("participant_id"),
            (self.payload or {}).get("participant_identity"),
            (self.raw_message or {}).get("participant_id"),
            (self.raw_message or {}).get("participant_identity"),
            self.device_id,
        )

    def _derive_completion_emission_id(self) -> str:
        for key in (
            "completion_emission_id",
            "emission_id",
            "completion_id",
            "handoff_id",
            "result_id",
            "message_id",
        ):
            value = self._first_available_text(
                (self.payload or {}).get(key),
                (self.raw_message or {}).get(key),
            )
            if value:
                return value
        return self._first_available_text(
            self.trace_id,
            f"{self.normalized_result_kind}:{self.normalized_status}",
        )

    def __post_init__(self) -> None:
        if not self.participant_id:
            self.participant_id = self._derive_participant_id()
        if not self.completion_emission_id:
            self.completion_emission_id = self._derive_completion_emission_id()
        # Auto-generate idempotency_key when not explicitly set.
        if not self.idempotency_key and self.task_id:
            self.idempotency_key = f"{self.normalized_result_kind}:{self.task_id}"


# ---------------------------------------------------------------------------
# UnifiedResultIngressOutcome
# ---------------------------------------------------------------------------


@dataclass
class UnifiedResultIngressOutcome:
    """Result of one :func:`ingest_result` call.

    Attributes
    ----------
    was_deduplicated
        True iff the event was suppressed by the idempotency guard.
    truth_chain_complete
        True iff all four truth-chain steps ran without fatal error.
    completion_notified
        True iff ``CanonicalCompletionIngress.notify()`` ran successfully.
    store_task_result_ran
        True iff ``store_task_result`` was invoked (regardless of success).
    pending_response_resolved
        True iff at least one ``_pending_responses`` future was resolved.
    is_fully_closed
        True iff the result was fully processed through the entire chain without
        being deduplicated and all critical steps ran.
    incomplete_reason
        Human-readable explanation when ``is_fully_closed`` is False.
    task_id
        The ``task_id`` from the processed event.
    normalized_status
        The ``normalized_status`` from the processed event.
    """

    was_deduplicated: bool = False
    truth_chain_complete: bool = False
    completion_notified: bool = False
    store_task_result_ran: bool = False
    pending_response_resolved: bool = False
    is_fully_closed: bool = False
    incomplete_reason: str = ""
    task_id: str = ""
    normalized_status: str = ""
    continuity_rejected: bool = False
    """True iff the unified continuity legality authority rejected this result."""
    continuity_legality_verdict: str = ""
    """The :class:`~core.unified_continuity_legality_authority.ContinuityLegalityVerdict`
    value string produced by the continuity gate (empty when not evaluated)."""
    continuity_legality_mode: str = ""
    """Continuity legality strictness mode applied to this result ingress call."""
    problem_execution_closure: Dict[str, Any] = field(default_factory=dict)
    """Additive closure split: task closure vs delegated-step closure vs user-problem closure."""
    task_completed: bool = False
    """True iff canonical closure semantics classify the task as completed."""
    problem_solved: bool = False
    """True iff canonical closure semantics classify the user problem as solved."""
    problem_solved_via: str = ""
    """Problem-solving path classification (``local``/``cross_device``/``pending``)."""
    # PR-4: Execution evidence and canonical truth fields
    execution_evidence_state: str = ""
    """The :class:`~core.execution_evidence_model.ExecutionEvidenceState` value string
    for this result (e.g. ``completed_strong``, ``android_delegated``, ``failed``)."""
    evidence_trust_level: str = ""
    """The :class:`~core.execution_evidence_model.EvidenceTrustLevel` value string
    (``trusted`` / ``provisional`` / ``quarantine`` / ``rejected``)."""
    evidence_acceptance_verdict: str = ""
    """The :class:`~core.result_truth_acceptance_gate.ResultAcceptanceVerdict` value string
    (``accept`` / ``accept_provisional`` / ``quarantine`` / ``reject``)."""
    execution_evidence_record: Optional[Dict[str, Any]] = field(default=None)
    """Serialised :class:`~core.execution_evidence_model.ExecutionEvidenceRecord`
    dict for operator/audit consumers (None when evidence classification was skipped)."""
    effective_android_proof_class: str = ""
    """Explicit or inferred Android proof class that actually drove evidence classification."""
    android_evidence_resolution: str = ""
    """How Android evidence classification was resolved (explicit / inferred / missing)."""
    android_inferred_evidence_strength: str = ""
    """Inferred Android evidence strength when no explicit proof class is available."""
    android_evidence_runtime_context: Dict[str, Any] = field(default_factory=dict)
    """Merged Android runtime truth fields used to infer evidence strength."""
    # SSOT: Android truth context stamped at closure time
    android_truth_context: Dict[str, Any] = field(default_factory=dict)
    """V2AndroidTruthBlock dict for the originating device, stamped at closure time.
    Provides a stable Android truth snapshot co-sourced with this result closure.
    Empty when no device_id is available or the SSOT module is unavailable."""

    # Stale epoch classification
    stale_epoch_rejected: bool = False
    """True iff the result was blocked by the epoch stale gate before reaching
    closure adjudication.  Mutually exclusive with ``is_fully_closed=True``."""
    stale_classification: str = ""
    """One of ``"explicit_stale"``, ``"epoch_mismatch"``, ``"replay_epoch_mismatch"``
    or ``""`` when not stale."""
    stale_epoch_evidence: Dict[str, Any] = field(default_factory=dict)
    """Diagnostic evidence dict produced by the epoch stale gate.  Contains at
    minimum: ``task_id``, ``device_id``, ``session_epoch``, ``source_channel``,
    ``stale_trigger``, ``stale_classification``, ``stale_check_at``."""
    # Replay ordering adjudication (Step 0.75 — REPLAY channel only)
    replay_ordering_adjudicated: bool = False
    """True iff replay ordering adjudication ran for this event (REPLAY channel only).
    False for all non-REPLAY channel events and when the contract module is unavailable."""
    replay_ordering_decision: str = ""
    """Per-item ordering decision from the replay ordering contract.
    One of ``accept``, ``reject_out_of_order``, ``reject_stale``,
    ``reject_duplicate``, ``ambiguous_authority``.  Empty for non-REPLAY events."""
    replay_ordering_verdict: str = ""
    """Contract-level verdict from replay ordering adjudication.
    One of ``authoritative_contract_defined``, ``contract_partially_evidenced``,
    ``downgraded``, ``contract_not_yet_evidenced``.  Empty for non-REPLAY events."""
    replay_ordering_evidence: Dict[str, Any] = field(default_factory=dict)
    """Structured evidence from replay ordering adjudication.  Contains at minimum:
    ``adjudication_status``, ``ordering_decision``, ``ordering_verdict``,
    ``replay_item_id``, ``replay_seq``, ``session_key``.  Empty for non-REPLAY events."""
    completion_disposition: str = ""
    """Canonical completion disposition: ``first_accepted``,
    ``duplicate_ignored``, or ``stale_rejected``."""
    completion_lineage: Dict[str, Any] = field(default_factory=dict)
    """Task-level completion lineage evidence for this ingress event."""
    joint_idempotency_evidence: Dict[str, Any] = field(default_factory=dict)
    """Structured evidence describing the joint result-id and task-lineage
    idempotency decision for this ingress event."""
    dedupe_contract_action: str = ""
    """Cross-repo Android dedupe contract outcome (``accept``/``degrade``/``reject``)."""
    dedupe_contract_reason: str = ""
    """Reason explaining why canonical duplicate guarantees were degraded or rejected."""
    dedupe_contract_evidence: Dict[str, Any] = field(default_factory=dict)
    """Structured evidence attached to cross-repo dedupe contract evaluation."""
    continuity_adjudication_classification: str = ""
    """Unified continuity adjudication classification for this ingress decision."""
    continuity_adjudication_evidence: Dict[str, Any] = field(default_factory=dict)
    """Structured continuity adjudication evidence for diagnostics and tests."""
    closure_evidence_ledger: Dict[str, Any] = field(default_factory=dict)
    """Per-task closure adjudication evidence ledger snapshot."""
    final_truth_provenance: Dict[str, Any] = field(default_factory=dict)
    """Final-truth provenance derived from closure evidence ledger."""
    # Closure-grade eligibility (Stage 1 Android ingress hardening)
    closure_grade_eligible: bool = True
    """Whether the Android payload that produced this outcome was eligible for
    closure-grade canonical credit.

    Propagated directly from :attr:`NormalizedResultEvent.closure_grade_eligible`.
    When ``False``, ``is_fully_closed`` will also be ``False`` regardless of
    whether the truth chain and completion notification steps succeeded.

    Per ``ANDROID_CLOSURE_GRADE_ELIGIBILITY_POLICY``."""
    closure_grade_ineligible_reason: str = ""
    """Human-readable reason explaining why ``closure_grade_eligible`` is False.
    Empty when ``closure_grade_eligible`` is True or when no reason was recorded."""
    android_payload_grade: str = ""
    """Closure-grade classification string from :class:`AndroidIngressPayloadGrade`.
    Propagated from :attr:`NormalizedResultEvent.android_payload_grade`.
    Empty string means no explicit grade assessment was performed."""


# ---------------------------------------------------------------------------
# UnifiedResultIngress
# ---------------------------------------------------------------------------


class UnifiedResultIngress:
    """Single canonical result processing chain.

    Thread-safe.  The :meth:`process` method is *synchronous* — async
    enrichment (``store_task_result``) is called via ``asyncio`` where
    available and falls back gracefully when no event loop is running.

    Processing chain steps (in order)
    ----------------------------------
    0.   Unified continuity legality gate
    0.5. Session epoch stale gate
    0.75 Replay ordering adjudication (REPLAY channel only)
    1.   Idempotency check / record
    2.   run_task_result_truth_chain (four-step truth chain)
    3.   CanonicalTaskRuntime lifecycle update  (if not already done by step 2)
    4.   Evidence quality classification (PR-4: execution evidence model + acceptance gate)
    5.   Stamp Android truth SSOT context (participation tier / readiness basis)
    6.   CanonicalCompletionIngress notify_with_android_context() / notify()
    7.   store_task_result / memory backflow    (async, best-effort)
    8.   Structured logging
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_closure_outcome: Dict[str, Any] = {}
        self._last_joint_idempotency_evidence: Dict[str, Any] = {}
        self._closure_evidence_ledger_by_task: Dict[str, Dict[str, Any]] = {}
        # Replay session state: keyed by "{device_id}:{session_id}".
        # Tracks max_seq and seen item_ids per replay session for ordering enforcement.
        self._replay_session_state: Dict[str, Dict[str, Any]] = {}
        self._replay_session_lock = threading.Lock()

    def reset_replay_session_state(self) -> None:
        """Clear all tracked replay session state (test isolation helper)."""
        with self._replay_session_lock:
            self._replay_session_state.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, event: NormalizedResultEvent) -> UnifiedResultIngressOutcome:
        """Drive *event* through the unified result processing chain.

        This method is **synchronous**.  Callers on an async path may await
        :meth:`process_async` instead.

        Returns a :class:`UnifiedResultIngressOutcome` describing which steps
        ran.
        """
        outcome = UnifiedResultIngressOutcome(
            task_id=event.task_id,
            normalized_status=event.normalized_status,
        )
        # Propagate closure-grade fields from the event immediately so that
        # all early-return paths (continuity reject, stale, replay ordering
        # reject, dedupe) also carry the correct closure-grade classification.
        outcome.closure_grade_eligible = event.closure_grade_eligible
        outcome.android_payload_grade = event.android_payload_grade
        if not event.closure_grade_eligible:
            grade = event.android_payload_grade or AndroidIngressPayloadGrade.UNCLASSIFIED.value
            outcome.closure_grade_ineligible_reason = (
                f"Payload not eligible for canonical closure due to grade: {grade}"
            )
        completion_lineage = self._build_completion_lineage(event)
        outcome.completion_lineage = dict(completion_lineage)

        # Step 0: unified continuity legality gate
        # Terminal result ingestion MUST submit to the same continuity
        # authority as reconnect, replay, and delegated recovery paths.
        # Per ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY.
        continuity_mode = self._resolve_continuity_mode(event)
        continuity_verdict = self._check_continuity_legality(
            event,
            mode=continuity_mode,
        )
        outcome.continuity_legality_verdict = continuity_verdict
        outcome.continuity_legality_mode = continuity_mode
        if self._should_block_on_continuity_verdict(
            continuity_verdict,
            mode=continuity_mode,
        ):
            continuity_policy = adjudicate_continuity_legality_gate(
                should_block=True,
                verdict=continuity_verdict,
            )
            outcome.continuity_rejected = True
            outcome.continuity_adjudication_classification = continuity_policy.classification
            outcome.continuity_adjudication_evidence = build_continuity_adjudication_evidence(
                classification=outcome.continuity_adjudication_classification,
                triggering_reason=continuity_policy.triggering_reason,
                epoch_session_basis={
                    "session_epoch": event.session_epoch,
                    "runtime_session_id": event.runtime_session_id,
                    "runtime_attachment_session_id": event.runtime_attachment_session_id,
                    "source_channel": event.source_channel.value,
                },
                related_identity={
                    "task_id": event.task_id,
                    "device_id": event.device_id,
                    "result_id": event.idempotency_key,
                    "completion_emission_id": event.completion_emission_id,
                },
                decision_point="unified_result_ingress.continuity_legality_gate",
            )
            outcome.incomplete_reason = f"continuity_rejected:{continuity_verdict}"
            logger.warning(
                "unified_result_ingress: continuity gate rejected result " "task_id=%r verdict=%r source=%s",
                event.task_id,
                continuity_verdict,
                event.source_channel.value,
            )
            self._record_last_closure_outcome(event, outcome)
            return outcome

        # Step 0.5: session epoch stale gate
        # Prevents old-session / reconnect-late / replay-derived results from
        # entering canonical closure adjudication.  Runs BEFORE idempotency so
        # that stale results are not recorded in the durable idempotency store.
        _stale, _stale_cls, _stale_evidence = self._check_stale_epoch(event)
        if _stale:
            stale_policy = adjudicate_stale_vs_current(
                is_stale=True,
                stale_classification=_stale_cls,
                stale_reason=str(_stale_evidence.get("stale_reason") or ""),
            )
            outcome.stale_epoch_rejected = True
            outcome.stale_classification = _stale_cls
            outcome.stale_epoch_evidence = _stale_evidence
            outcome.completion_disposition = stale_policy.completion_disposition
            outcome.continuity_adjudication_classification = stale_policy.classification
            outcome.continuity_adjudication_evidence = build_continuity_adjudication_evidence(
                classification=outcome.continuity_adjudication_classification,
                triggering_reason=stale_policy.triggering_reason,
                epoch_session_basis={
                    "session_epoch": event.session_epoch,
                    "stored_epoch": _stale_evidence.get("stored_epoch"),
                    "presented_epoch": _stale_evidence.get("presented_epoch"),
                    "runtime_session_id": event.runtime_session_id,
                    "runtime_attachment_session_id": event.runtime_attachment_session_id,
                },
                related_identity={
                    "task_id": event.task_id,
                    "device_id": event.device_id,
                    "result_id": event.idempotency_key,
                    "completion_emission_id": event.completion_emission_id,
                },
                decision_point="unified_result_ingress.stale_epoch_gate",
            )
            outcome.joint_idempotency_evidence = self._fallback_joint_idempotency_evidence(
                event,
                completion_lineage=completion_lineage,
                decision="stale_rejected",
                stale_classification=_stale_cls,
            )
            outcome.incomplete_reason = f"stale_epoch_rejected:{_stale_cls}"
            logger.warning(
                "unified_result_ingress: stale epoch gate blocked result "
                "task_id=%r classification=%r device_id=%r source=%s evidence=%r",
                event.task_id,
                _stale_cls,
                event.device_id,
                event.source_channel.value,
                _stale_evidence,
            )
            self._record_last_closure_outcome(event, outcome)
            return outcome

        # Step 0.75: Replay ordering adjudication (REPLAY channel only)
        # Evaluates replay ordering semantics against the V2-side offline replay
        # ordering contract BEFORE idempotency recording and canonical closure.
        # Items that fail ordering adjudication (out-of-order, stale) are blocked.
        # Items missing required ordering metadata (replay_item_id + replay_seq)
        # are classified ambiguous_authority and do NOT silently pass as canonical.
        if event.source_channel == ResultSourceChannel.REPLAY:
            (
                _replay_blocked,
                _replay_decision,
                _replay_verdict,
                _replay_evidence,
            ) = self._adjudicate_replay_ordering(event)
            outcome.replay_ordering_adjudicated = True
            outcome.replay_ordering_decision = _replay_decision
            outcome.replay_ordering_verdict = _replay_verdict
            outcome.replay_ordering_evidence = _replay_evidence
            if _replay_blocked:
                outcome.incomplete_reason = f"replay_ordering_rejected:{_replay_decision}"
                logger.warning(
                    "unified_result_ingress: replay ordering gate blocked result "
                    "task_id=%r decision=%r verdict=%r device_id=%r",
                    event.task_id,
                    _replay_decision,
                    _replay_verdict,
                    event.device_id,
                )
                self._record_last_closure_outcome(event, outcome)
                return outcome
            if _replay_decision == "ambiguous_authority":
                outcome.dedupe_contract_action = "degrade"
                outcome.dedupe_contract_reason = "replay_ordering_ambiguous_authority"
                outcome.dedupe_contract_evidence = {
                    "contract_class": "replay",
                    "replay_ordering": dict(_replay_evidence or {}),
                }

        (
            _dedupe_contract_action,
            _dedupe_contract_reason,
            _dedupe_contract_evidence,
        ) = self._evaluate_cross_repo_dedupe_contract(event)
        if _dedupe_contract_action == "reject":
            outcome.dedupe_contract_action = "reject"
            outcome.dedupe_contract_reason = _dedupe_contract_reason
            outcome.dedupe_contract_evidence = dict(_dedupe_contract_evidence or {})
            outcome.incomplete_reason = f"dedupe_contract_rejected:{_dedupe_contract_reason}"
            logger.warning(
                "unified_result_ingress: cross-repo dedupe contract rejected " "task_id=%r source=%s reason=%s",
                event.task_id,
                event.source_channel.value,
                _dedupe_contract_reason,
            )
            self._record_last_closure_outcome(event, outcome)
            return outcome
        if _dedupe_contract_action == "degrade":
            outcome.dedupe_contract_action = "degrade"
            if not outcome.dedupe_contract_reason:
                outcome.dedupe_contract_reason = _dedupe_contract_reason
            combined_evidence = dict(outcome.dedupe_contract_evidence or {})
            combined_evidence.update(dict(_dedupe_contract_evidence or {}))
            outcome.dedupe_contract_evidence = combined_evidence

        # Step 1: idempotency
        if self._check_idempotency(event):
            duplicate_policy = adjudicate_duplicate_vs_first_accepted(
                is_duplicate=True,
            )
            outcome.was_deduplicated = True
            outcome.completion_disposition = duplicate_policy.completion_disposition
            outcome.continuity_adjudication_classification = duplicate_policy.classification
            outcome.continuity_adjudication_evidence = build_continuity_adjudication_evidence(
                classification=outcome.continuity_adjudication_classification,
                triggering_reason=duplicate_policy.triggering_reason,
                epoch_session_basis={
                    "session_epoch": event.session_epoch,
                    "runtime_session_id": event.runtime_session_id,
                    "runtime_attachment_session_id": event.runtime_attachment_session_id,
                },
                related_identity={
                    "task_id": event.task_id,
                    "device_id": event.device_id,
                    "result_id": event.idempotency_key,
                    "completion_emission_id": event.completion_emission_id,
                    "completion_lineage_key": completion_lineage.get("completion_lineage_key"),
                },
                decision_point="unified_result_ingress.idempotency_gate",
            )
            outcome.joint_idempotency_evidence = (
                self._consume_joint_idempotency_evidence()
                or self._fallback_joint_idempotency_evidence(
                    event,
                    completion_lineage=completion_lineage,
                    decision="duplicate_ignored",
                )
            )
            outcome.incomplete_reason = "deduplicated"
            logger.debug(
                "unified_result_ingress: duplicate suppressed " "task_id=%r idempotency_key=%r source=%s",
                event.task_id,
                event.idempotency_key,
                event.source_channel.value,
            )
            self._record_last_closure_outcome(event, outcome)
            return outcome

        self._record_idempotency(event)
        accept_policy = adjudicate_duplicate_vs_first_accepted(
            is_duplicate=False,
        )
        outcome.completion_disposition = accept_policy.completion_disposition
        outcome.continuity_adjudication_classification = accept_policy.classification
        outcome.continuity_adjudication_evidence = build_continuity_adjudication_evidence(
            classification=outcome.continuity_adjudication_classification,
            triggering_reason=accept_policy.triggering_reason,
            epoch_session_basis={
                "session_epoch": event.session_epoch,
                "runtime_session_id": event.runtime_session_id,
                "runtime_attachment_session_id": event.runtime_attachment_session_id,
            },
            related_identity={
                "task_id": event.task_id,
                "device_id": event.device_id,
                "result_id": event.idempotency_key,
                "completion_emission_id": event.completion_emission_id,
                "completion_lineage_key": completion_lineage.get("completion_lineage_key"),
            },
            decision_point="unified_result_ingress.accept_current_result",
        )
        outcome.joint_idempotency_evidence = (
            self._consume_joint_idempotency_evidence()
            or self._fallback_joint_idempotency_evidence(
                event,
                completion_lineage=completion_lineage,
                decision="first_accepted",
            )
        )

        logger.info(
            "unified_result_ingress: processing result " "task_id=%r status=%r kind=%r source=%s channel=%s",
            event.task_id,
            event.normalized_status,
            event.normalized_result_kind,
            event.source_channel.value,
            event.trace_id or "",
        )

        # Step 1.5: wire-level closure fallback normalization.
        # Android may report structured closure semantics via
        # `problem_solving_closure_class`; completion ingress and closure builders
        # consume `problem_solved` / `problem_closed`.
        self._apply_problem_solving_closure_fallback(event)

        # Step 2: four-step truth chain
        outcome.truth_chain_complete = self._run_truth_chain(event)

        # Step 3: CanonicalTaskRuntime lifecycle (belt-and-suspenders if not done
        # by truth chain's authority_state_update step)
        self._sync_lifecycle(event)

        # Step 4: PR-4 execution evidence classification + acceptance gate
        try:
            self._classify_and_apply_evidence_gate(event, outcome)
        except Exception as _ev_err:
            logger.warning(
                "unified_result_ingress: evidence gate step raised (non-fatal) " "task_id=%r err=%s",
                event.task_id,
                _ev_err,
            )

        # Step 5: Stamp Android truth SSOT context at closure time so completion
        # ingress and downstream projections consume the same participation truth.
        self._stamp_android_truth_context(event, outcome)

        # Step 6: CanonicalCompletionIngress notify / notify_with_android_context
        outcome.completion_notified = self._notify_completion(event)

        # Step 7: structured logging
        self._log_outcome(event, outcome)

        # Determine overall closure
        evidence_verdict = outcome.evidence_acceptance_verdict or ""
        evidence_gate_blocked = evidence_verdict in EVIDENCE_CLOSURE_BLOCKING_VERDICTS
        dedupe_contract_blocked = outcome.dedupe_contract_action == "degrade"
        closure_grade_blocked = not outcome.closure_grade_eligible
        outcome.is_fully_closed = (
            not outcome.was_deduplicated
            and outcome.truth_chain_complete
            and outcome.completion_notified
            and not evidence_gate_blocked
            and not dedupe_contract_blocked
            and not closure_grade_blocked
        )
        if not outcome.is_fully_closed and not outcome.incomplete_reason:
            parts = []
            if not outcome.truth_chain_complete:
                parts.append("truth_chain_incomplete")
            if not outcome.completion_notified:
                parts.append("completion_not_notified")
            if evidence_gate_blocked:
                parts.append(f"evidence_gate:{evidence_verdict}")
            if dedupe_contract_blocked:
                parts.append(f"dedupe_contract:{outcome.dedupe_contract_reason or outcome.dedupe_contract_action}")
            if closure_grade_blocked:
                parts.append(
                    f"closure_grade_ineligible:{outcome.closure_grade_ineligible_reason or outcome.android_payload_grade or 'unclassified'}"
                )
            outcome.incomplete_reason = "; ".join(parts) if parts else "unknown"
        outcome.problem_execution_closure = self._build_problem_execution_closure(
            event=event,
            outcome=outcome,
        )
        outcome.task_completed = bool(outcome.problem_execution_closure.get("task_completed"))
        outcome.problem_solved = bool(outcome.problem_execution_closure.get("problem_solved"))
        outcome.problem_solved_via = str(outcome.problem_execution_closure.get("problem_solved_via") or "")
        self._record_last_closure_outcome(event, outcome)

        return outcome

    def _record_last_closure_outcome(
        self,
        event: NormalizedResultEvent,
        outcome: UnifiedResultIngressOutcome,
    ) -> None:
        ledger_entry = self._upsert_closure_evidence_ledger(event, outcome)
        provenance = self._build_final_truth_provenance(ledger_entry)
        outcome.closure_evidence_ledger = dict(ledger_entry)
        outcome.final_truth_provenance = dict(provenance)
        canonical_truth_completed = bool(
            outcome.is_fully_closed
            and outcome.truth_chain_complete
            and str(outcome.evidence_acceptance_verdict or "").strip().lower() in {"accept", "accepted"}
        )
        summary = {
            "available": True,
            "task_id": event.task_id,
            "device_id": event.device_id,
            "normalized_status": outcome.normalized_status,
            "is_fully_closed": bool(outcome.is_fully_closed),
            "truth_chain_complete": bool(outcome.truth_chain_complete),
            "canonical_truth_completed": canonical_truth_completed,
            "mature_closure_achieved": bool(canonical_truth_completed and not bool(outcome.incomplete_reason)),
            "completion_notified": bool(outcome.completion_notified),
            "problem_solved": bool(outcome.problem_solved),
            "problem_solved_via": str(outcome.problem_solved_via or ""),
            "incomplete_reason": str(outcome.incomplete_reason or ""),
            "source_channel": event.source_channel.value,
            "closure_authority": "canonical_result_ingress",
            "completion_disposition": str(outcome.completion_disposition or ""),
            "completion_lineage": dict(outcome.completion_lineage or {}),
            "joint_idempotency_evidence": dict(outcome.joint_idempotency_evidence or {}),
            "continuity_adjudication_classification": str(outcome.continuity_adjudication_classification or ""),
            "continuity_adjudication_evidence": dict(outcome.continuity_adjudication_evidence or {}),
            "stale_classification": str(outcome.stale_classification or ""),
            "closure_evidence_ledger": dict(ledger_entry),
            "final_truth_provenance": dict(provenance),
            "replay_ordering_adjudicated": bool(outcome.replay_ordering_adjudicated),
            "replay_ordering_decision": str(outcome.replay_ordering_decision or ""),
            "replay_ordering_verdict": str(outcome.replay_ordering_verdict or ""),
            "replay_ordering_evidence": dict(outcome.replay_ordering_evidence or {}),
            "dedupe_contract_action": str(outcome.dedupe_contract_action or ""),
            "dedupe_contract_reason": str(outcome.dedupe_contract_reason or ""),
            "dedupe_contract_evidence": dict(outcome.dedupe_contract_evidence or {}),
            # Stage 1: closure-grade eligibility
            "closure_grade_eligible": bool(outcome.closure_grade_eligible),
            "closure_grade_ineligible_reason": str(outcome.closure_grade_ineligible_reason or ""),
            "android_payload_grade": str(outcome.android_payload_grade or ""),
            "updated_at": time.time(),
        }
        with self._lock:
            self._last_closure_outcome = summary

    def get_last_closure_outcome(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._last_closure_outcome)

    def _upsert_closure_evidence_ledger(
        self,
        event: NormalizedResultEvent,
        outcome: UnifiedResultIngressOutcome,
    ) -> Dict[str, Any]:
        task_id = str(event.task_id or "")
        if not task_id:
            return {}

        now = time.time()
        identity = {
            "task_id": task_id,
            "device_id": str(event.device_id or ""),
            "participant_id": str(event.participant_id or event.device_id or ""),
            "session_epoch": event.session_epoch,
            "runtime_session_id": str(event.runtime_session_id or ""),
            "runtime_attachment_session_id": str(event.runtime_attachment_session_id or ""),
            "result_id": str(event.idempotency_key or ""),
            "completion_emission_id": str(event.completion_emission_id or ""),
            "source_channel": event.source_channel.value,
        }
        reason = (
            str((outcome.continuity_adjudication_evidence or {}).get("triggering_reason") or "")
            or str(outcome.incomplete_reason or "")
            or str(outcome.stale_classification or "")
            or str(outcome.completion_disposition or "unknown")
        )
        event_evidence = {
            "disposition": str(outcome.completion_disposition or ""),
            "classification": str(outcome.continuity_adjudication_classification or ""),
            "reason": reason,
            "identity": identity,
            "adjudication_evidence": dict(outcome.continuity_adjudication_evidence or {}),
            "stale_evidence": dict(outcome.stale_epoch_evidence or {}),
            "joint_idempotency_evidence": dict(outcome.joint_idempotency_evidence or {}),
            "dedupe_contract_action": str(outcome.dedupe_contract_action or ""),
            "dedupe_contract_reason": str(outcome.dedupe_contract_reason or ""),
            "dedupe_contract_evidence": dict(outcome.dedupe_contract_evidence or {}),
            "recorded_at": now,
        }

        with self._lock:
            ledger = dict(self._closure_evidence_ledger_by_task.get(task_id) or {})
            if not ledger:
                ledger = {
                    "task_id": task_id,
                    "first_accepted_completion": {},
                    "competing_events": [],
                    "competing_summary": {
                        "duplicate_ignored": 0,
                        "stale_rejected": 0,
                        "superseded_by_newer_epoch_session": 0,
                    },
                    "updated_at": now,
                }

            accepted = dict(ledger.get("first_accepted_completion") or {})
            disposition = str(outcome.completion_disposition or "")
            if disposition == "first_accepted":
                if not accepted:
                    ledger["first_accepted_completion"] = dict(event_evidence)
                else:
                    accepted_identity = dict((accepted.get("identity") or {}))
                    accepted_epoch = accepted_identity.get("session_epoch")
                    presented_epoch = identity.get("session_epoch")
                    superseded = (
                        isinstance(accepted_epoch, int)
                        and isinstance(presented_epoch, int)
                        and presented_epoch > accepted_epoch
                    ) or (
                        bool(accepted_identity.get("runtime_session_id"))
                        and bool(identity.get("runtime_session_id"))
                        and accepted_identity.get("runtime_session_id") != identity.get("runtime_session_id")
                    )
                    if superseded:
                        superseded_event = dict(event_evidence)
                        superseded_event["disposition"] = "superseded_by_newer_epoch_session"
                        superseded_event["reason"] = "accepted_event_superseded_by_newer_epoch_or_session"
                        competing = list(ledger.get("competing_events") or [])
                        competing.append(superseded_event)
                        ledger["competing_events"] = competing[-20:]
                        summary = dict(ledger.get("competing_summary") or {})
                        summary["superseded_by_newer_epoch_session"] = (
                            int(summary.get("superseded_by_newer_epoch_session", 0)) + 1
                        )
                        ledger["competing_summary"] = summary
                        ledger["first_accepted_completion"] = dict(event_evidence)
            else:
                competing = list(ledger.get("competing_events") or [])
                competing.append(event_evidence)
                ledger["competing_events"] = competing[-20:]
                summary = dict(ledger.get("competing_summary") or {})
                if disposition == "duplicate_ignored":
                    summary["duplicate_ignored"] = int(summary.get("duplicate_ignored", 0)) + 1
                if disposition == "stale_rejected":
                    summary["stale_rejected"] = int(summary.get("stale_rejected", 0)) + 1
                    stale_cls = str(outcome.stale_classification or "")
                    stale_ev = dict(outcome.stale_epoch_evidence or {})
                    if stale_cls in {"epoch_mismatch", "replay_epoch_mismatch"}:
                        stored_epoch = stale_ev.get("stored_epoch")
                        presented_epoch = stale_ev.get("presented_epoch")
                        if isinstance(stored_epoch, int) and isinstance(presented_epoch, int):
                            if stored_epoch > presented_epoch:
                                summary["superseded_by_newer_epoch_session"] = (
                                    int(summary.get("superseded_by_newer_epoch_session", 0)) + 1
                                )
                ledger["competing_summary"] = summary

            ledger["updated_at"] = now
            self._closure_evidence_ledger_by_task[task_id] = dict(ledger)
            return dict(ledger)

    @staticmethod
    def _build_final_truth_provenance(ledger_entry: Dict[str, Any]) -> Dict[str, Any]:
        if not ledger_entry:
            return {}
        accepted = dict(ledger_entry.get("first_accepted_completion") or {})
        accepted_identity = dict(accepted.get("identity") or {})
        accepted_reason = str(accepted.get("reason") or "")
        competing_summary = dict(ledger_entry.get("competing_summary") or {})
        return {
            "accepted_event_identity": accepted_identity,
            "accepted_reason_basis": accepted_reason,
            "competing_rejected_or_ignored_summary": competing_summary,
            "evidence_ledger_task_id": str(ledger_entry.get("task_id") or ""),
            "evidence_ledger_updated_at": ledger_entry.get("updated_at"),
        }

    async def process_async(
        self,
        event: NormalizedResultEvent,
        *,
        store_fn: Any = None,
        bridge: Any = None,
    ) -> UnifiedResultIngressOutcome:
        """Async version of :meth:`process` that also runs ``store_task_result``.

        Parameters
        ----------
        event:
            The normalized result event to process.
        store_fn:
            Optional coroutine function matching the signature of
            ``core.openclawd_memory_backflow.store_task_result``.  When
            provided, memory backflow runs before returning.
        bridge:
            Optional :class:`~galaxy_gateway.android_bridge.AndroidBridge`
            instance.  When provided, any ``_pending_responses`` future keyed
            by ``event.task_id`` will be resolved.
        """
        outcome = self.process(event)

        if outcome.was_deduplicated:
            return outcome

        # Step 5a: resolve _pending_responses (bridge futures)
        if bridge is not None and event.task_id:
            resolved = self._resolve_bridge_pending(bridge, event)
            outcome.pending_response_resolved = resolved

        # Step 5b: async memory backflow
        if store_fn is not None and event.task_id:
            try:
                await store_fn(
                    task_id=event.task_id,
                    device_id=event.device_id,
                    route_mode=event.payload.get("route_mode", ""),
                    result={
                        "status": event.normalized_status,
                        "result": event.payload.get("result") or event.payload.get("details", ""),
                        "trace_id": event.trace_id,
                        "task_type": event.normalized_result_kind,
                    },
                    session_id=event.payload.get("session_id") or event.runtime_session_id or None,
                )
                outcome.store_task_result_ran = True
            except Exception as _store_err:
                logger.warning(
                    "unified_result_ingress: store_task_result failed (non-fatal) " "task_id=%r error=%s",
                    event.task_id,
                    _store_err,
                )

        return outcome

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_continuity_mode(self, event: NormalizedResultEvent) -> str:
        payload = event.payload or {}
        for key in (
            "continuity_legality_mode",
            "canonical_continuity_mode",
            "canonical_governance_mode",
        ):
            raw = str(payload.get(key) or "").strip().lower()
            if raw in {"strict", "compat", "relaxed"}:
                return raw
        env_mode = str(os.environ.get("GALAXY_RESULT_INGRESS_CONTINUITY_MODE", "compat")).strip().lower()
        if env_mode in {"strict", "compat", "relaxed"}:
            return env_mode
        return "compat"

    @staticmethod
    def _should_block_on_continuity_verdict(verdict: str, *, mode: str) -> bool:
        norm_mode = str(mode).strip().lower()
        if verdict == "reject":
            return True
        if verdict == "require_review":
            return norm_mode == "strict"
        return False

    def _check_continuity_legality(
        self,
        event: NormalizedResultEvent,
        *,
        mode: str,
    ) -> str:
        """Run the unified continuity legality gate for terminal result ingestion.

        Returns the verdict string: ``"allow"``, ``"reject"``, or
        ``"require_review"``.  Defaults to ``"allow"`` when the authority
        module is unavailable (graceful degradation consistent with the
        additive-only policy for this change).
        """
        try:
            from core.unified_continuity_legality_authority import (
                ContinuityLegalityContext,
                ContinuityLegalityPath,
                evaluate_continuity_legality,
            )

            ctx = ContinuityLegalityContext(
                device_id=event.device_id or "",
                runtime_session_id=event.runtime_session_id or "",
                runtime_attachment_session_id=event.runtime_attachment_session_id or "",
                durable_session_id=event.durable_session_id or "",
            )
            report = evaluate_continuity_legality(
                ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
                ctx,
                mode=mode,
            )
            return report.verdict.value
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: continuity legality gate unavailable " "(mode=%s): %s",
                mode,
                _e,
            )
            if str(mode).strip().lower() == "strict":
                return "require_review"
            if str(mode).strip().lower() == "relaxed":
                return "allow"
            return "require_review"

    def _check_stale_epoch(
        self,
        event: NormalizedResultEvent,
    ) -> tuple:
        """Classify *event* for session/continuity epoch staleness.

        Returns a ``(is_stale, classification, evidence)`` triple.

        Classification strings
        ----------------------
        ``"explicit_stale"``
            The event's ``is_stale`` flag was pre-set by the upstream caller.
        ``"epoch_mismatch"``
            ``event.session_epoch`` differs from the canonical stored epoch in
            the session registry for ``event.device_id``.
        ``"replay_epoch_mismatch"``
            Source channel is :attr:`ResultSourceChannel.REPLAY` and
            ``event.session_epoch`` differs from the registry epoch.

        When no stale condition is detected returns ``(False, "", {})``.
        """
        evidence: Dict[str, Any] = {
            "task_id": event.task_id,
            "device_id": event.device_id,
            "participant_id": event.participant_id or event.device_id,
            "session_epoch": event.session_epoch,
            "completion_emission_id": event.completion_emission_id,
            "source_channel": event.source_channel.value,
            "stale_check_at": time.time(),
        }

        # ── Case 1: explicit is_stale flag set by upstream caller ───────────
        if event.is_stale:
            reason = event.stale_reason or "explicit_is_stale"
            evidence["stale_trigger"] = "explicit_flag"
            evidence["stale_classification"] = "explicit_stale"
            evidence["stale_reason"] = reason
            return True, "explicit_stale", evidence

        # ── Case 2: epoch comparison via registry ────────────────────────────
        if event.session_epoch is not None and event.device_id:
            try:
                from core.attached_runtime_session_registry import (
                    lookup_session_by_device,
                )

                registry_entry = lookup_session_by_device(event.device_id)
                if registry_entry is not None:
                    stored_epoch = getattr(registry_entry, "continuity_epoch", None)
                    evidence["stored_epoch"] = stored_epoch
                    evidence["presented_epoch"] = event.session_epoch
                    if stored_epoch is not None and stored_epoch != event.session_epoch:
                        is_replay = event.source_channel == ResultSourceChannel.REPLAY
                        classification = "replay_epoch_mismatch" if is_replay else "epoch_mismatch"
                        evidence["stale_trigger"] = "epoch_comparison"
                        evidence["stale_classification"] = classification
                        return True, classification, evidence
            except Exception as _lookup_err:
                logger.debug(
                    "unified_result_ingress: stale epoch registry lookup skipped " "(non-fatal) task_id=%r err=%s",
                    event.task_id,
                    _lookup_err,
                )

        return False, "", {}

    def _adjudicate_replay_ordering(
        self,
        event: "NormalizedResultEvent",
    ) -> "tuple":
        """Adjudicate replay ordering for a REPLAY channel event.

        Evaluates the event against the V2-side offline replay ordering contract
        (``core.offline_replay_ordering_contract``) using per-session state
        tracking.  Must be called only for ``ResultSourceChannel.REPLAY`` events.

        Parameters
        ----------
        event
            The REPLAY channel event being adjudicated.

        Returns
        -------
        tuple of (is_blocked, decision_str, verdict_str, evidence_dict)
            ``is_blocked`` is True when the ordering decision is
            ``reject_out_of_order`` or ``reject_stale``.  ``ambiguous_authority``
            and ``reject_duplicate`` do NOT block (the standard idempotency gate
            handles duplicates; ambiguous is non-canonical but not hard-blocked).
            ``evidence_dict`` always contains structured ordering evidence.
        """
        adjudication_at = time.time()
        replay_item_id = str(event.replay_item_id or "").strip()
        replay_seq = event.replay_seq  # None = missing
        replay_session_id = str(event.replay_session_id or event.runtime_session_id or "").strip()
        session_key = f"{event.device_id or ''}:{replay_session_id}"

        try:
            from core.offline_replay_ordering_contract import (
                OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY,
                OfflineReplayItemDecision,
                OfflineReplayContractVerdict,
                STALE_SEQ_WINDOW,
            )
        except Exception as _import_err:
            logger.debug(
                "unified_result_ingress: replay ordering contract unavailable " "(non-fatal) task_id=%r err=%s",
                event.task_id,
                _import_err,
            )
            # Make "contract unavailable" explicit rather than silently passing.
            evidence: Dict[str, Any] = {
                "adjudication_status": "contract_unavailable",
                "task_id": event.task_id,
                "device_id": event.device_id,
                "replay_item_id": replay_item_id,
                "replay_seq": replay_seq,
                "session_key": session_key,
                "ordering_decision": "ambiguous_authority",
                "ordering_verdict": "contract_not_yet_evidenced",
                "adjudication_at": adjudication_at,
            }
            return False, "ambiguous_authority", "contract_not_yet_evidenced", evidence

        has_seq = replay_seq is not None
        has_item_id = bool(replay_item_id)

        # Case 1: Missing both ordering fields → ambiguous authority
        if not has_seq and not has_item_id:
            evidence = {
                "adjudication_status": "missing_ordering_metadata",
                "task_id": event.task_id,
                "device_id": event.device_id,
                "replay_item_id": replay_item_id,
                "replay_seq": replay_seq,
                "session_key": session_key,
                "ordering_decision": OfflineReplayItemDecision.ambiguous_authority.value,
                "ordering_verdict": OfflineReplayContractVerdict.downgraded.value,
                "missing_fields": ["replay_item_id", "replay_seq"],
                "contract_authority": OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY,
                "adjudication_at": adjudication_at,
            }
            logger.debug(
                "unified_result_ingress: replay ordering — missing metadata " "task_id=%r device_id=%r session_key=%r",
                event.task_id,
                event.device_id,
                session_key,
            )
            return (
                False,
                OfflineReplayItemDecision.ambiguous_authority.value,
                OfflineReplayContractVerdict.downgraded.value,
                evidence,
            )

        # Case 2: Evaluate against per-session state
        seq = int(replay_seq) if has_seq else 0

        with self._replay_session_lock:
            state = self._replay_session_state.get(session_key)
            if state is None:
                state = {"max_seq": -1, "seen_ids": set(), "item_count": 0}
                self._replay_session_state[session_key] = state

            max_seq_before = state["max_seq"]
            seen_ids: set = state["seen_ids"]

            # Mirror the ordering logic of _evaluate_items_into_report in the
            # offline replay ordering contract.  Stale check: item is more than
            # STALE_SEQ_WINDOW *behind* the current session maximum
            # (max_seq_before - seq > STALE_SEQ_WINDOW).  When seq is *ahead*
            # of max (seq > max_seq_before), this expression is negative and the
            # condition is False — the item is correctly not stale.
            is_dup = has_item_id and (replay_item_id in seen_ids)
            is_stale = (not is_dup) and has_seq and (max_seq_before - seq > STALE_SEQ_WINDOW)
            is_oor = (not is_dup) and (not is_stale) and has_seq and (seq < max_seq_before)

            if is_dup:
                decision = OfflineReplayItemDecision.reject_duplicate
                verdict = OfflineReplayContractVerdict.contract_partially_evidenced
            elif is_stale:
                decision = OfflineReplayItemDecision.reject_stale
                verdict = OfflineReplayContractVerdict.contract_partially_evidenced
            elif is_oor:
                decision = OfflineReplayItemDecision.reject_out_of_order
                verdict = OfflineReplayContractVerdict.contract_partially_evidenced
            elif not has_item_id:
                # Has seq but no item_id → ambiguous (cannot dedup)
                decision = OfflineReplayItemDecision.ambiguous_authority
                verdict = OfflineReplayContractVerdict.downgraded
            else:
                decision = OfflineReplayItemDecision.accept
                verdict = OfflineReplayContractVerdict.authoritative_contract_defined
                seen_ids.add(replay_item_id)

            # Advance session max_seq for accepted and ambiguous items (not for
            # rejected items whose ordering position is already behind max).
            if not is_dup and not is_stale and not is_oor and has_seq and seq > state["max_seq"]:
                state["max_seq"] = seq

            state["item_count"] += 1

        evidence = {
            "adjudication_status": "evaluated",
            "task_id": event.task_id,
            "device_id": event.device_id,
            "replay_item_id": replay_item_id,
            "replay_seq": replay_seq,
            "session_key": session_key,
            "replay_session_id": replay_session_id,
            "ordering_decision": decision.value,
            "ordering_verdict": verdict.value,
            "session_max_seq_before": max_seq_before,
            "is_duplicate": is_dup,
            "is_stale": is_stale,
            "is_out_of_order": is_oor,
            "contract_authority": OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY,
            "adjudication_at": adjudication_at,
        }

        is_blocked = decision.value in REPLAY_ORDERING_BLOCKING_DECISIONS

        logger.debug(
            "unified_result_ingress: replay ordering adjudicated "
            "task_id=%r decision=%r verdict=%r blocked=%s seq=%r max_before=%r",
            event.task_id,
            decision.value,
            verdict.value,
            is_blocked,
            replay_seq,
            max_seq_before,
        )
        return is_blocked, decision.value, verdict.value, evidence

    def _check_idempotency(self, event: NormalizedResultEvent) -> bool:
        """Return True iff the idempotency_key is already recorded."""
        completion_lineage = self._build_completion_lineage(event)
        evidence = self._fallback_joint_idempotency_evidence(
            event,
            completion_lineage=completion_lineage,
            decision="pending_first_record",
        )
        try:
            from core.durable_result_idempotency import check_result_idempotency

            checked_keys = []
            result_duplicate = False
            if event.idempotency_key:
                checked_keys.append(event.idempotency_key)
                result_duplicate = check_result_idempotency(event.idempotency_key)
            lineage_key = str(completion_lineage.get("completion_lineage_key") or "").strip()
            lineage_duplicate = False
            if lineage_key:
                # Intentional: when a legacy path omits result_id / idempotency_key,
                # task-level completion lineage still provides canonical duplicate
                # suppression and evidence for terminal replays/re-sends.
                checked_keys.append(lineage_key)
                lineage_duplicate = check_result_idempotency(lineage_key)
            evidence["joint_idempotency_keys_checked"] = checked_keys
            evidence["result_idempotency_duplicate"] = bool(result_duplicate)
            evidence["completion_lineage_duplicate"] = bool(lineage_duplicate)
            duplicate_reason = ""
            if result_duplicate and lineage_duplicate:
                duplicate_reason = "result_idempotency+completion_lineage"
            elif result_duplicate:
                duplicate_reason = "result_idempotency"
            elif lineage_duplicate:
                duplicate_reason = "completion_lineage"
            if duplicate_reason:
                evidence["duplicate_reason"] = duplicate_reason
                evidence["joint_idempotency_decision"] = "duplicate_ignored"
            self._set_last_joint_idempotency_evidence(evidence)
            return bool(result_duplicate or lineage_duplicate)
        except Exception as _e:
            logger.debug("unified_result_ingress: idempotency check skipped (non-fatal): %s", _e)
            evidence["joint_idempotency_decision"] = "idempotency_check_skipped"
            evidence["joint_idempotency_error"] = str(_e)
            self._set_last_joint_idempotency_evidence(evidence)
            return False

    def _record_idempotency(self, event: NormalizedResultEvent) -> None:
        """Record the idempotency_key so subsequent duplicates are suppressed."""
        completion_lineage = self._build_completion_lineage(event)
        evidence = (
            dict(self._last_joint_idempotency_evidence)
            if self._last_joint_idempotency_evidence
            else self._fallback_joint_idempotency_evidence(
                event,
                completion_lineage=completion_lineage,
                decision="first_accepted",
            )
        )
        try:
            from core.durable_result_idempotency import record_result_idempotency

            recorded_keys = []
            if event.idempotency_key:
                record_result_idempotency(event.idempotency_key)
                recorded_keys.append(event.idempotency_key)
            lineage_key = str(completion_lineage.get("completion_lineage_key") or "").strip()
            if lineage_key:
                # Intentional: lineage evidence remains durable even when a legacy
                # path did not provide a separate result idempotency key.
                record_result_idempotency(lineage_key)
                # Keep the summary list unique because callers may explicitly set
                # idempotency_key to the same composite lineage token.
                if lineage_key not in recorded_keys:
                    recorded_keys.append(lineage_key)
            evidence["joint_idempotency_recorded_keys"] = recorded_keys
            evidence["joint_idempotency_decision"] = "first_accepted"
            self._set_last_joint_idempotency_evidence(evidence)
        except Exception as _e:
            logger.debug("unified_result_ingress: idempotency record skipped (non-fatal): %s", _e)
            evidence["joint_idempotency_decision"] = "idempotency_record_skipped"
            evidence["joint_idempotency_error"] = str(_e)
            self._set_last_joint_idempotency_evidence(evidence)

    def _run_truth_chain(self, event: NormalizedResultEvent) -> bool:
        """Run the four-step canonical truth chain and return True iff complete."""
        if not event.task_id:
            logger.debug(
                "unified_result_ingress: truth chain skipped — no task_id " "source=%s kind=%r",
                event.source_channel.value,
                event.normalized_result_kind,
            )
            return False
        try:
            from core.task_result_canonical_truth_chain import run_task_result_truth_chain

            ttc_outcome = run_task_result_truth_chain(
                event.raw_message or event.payload,
                task_id=event.task_id,
                result_status=event.normalized_status,
            )
            if not ttc_outcome.is_truth_chain_complete:
                logger.warning(
                    "unified_result_ingress: truth chain incomplete " "task_id=%r source=%s reason=%r",
                    event.task_id,
                    event.source_channel.value,
                    ttc_outcome.incomplete_reason,
                )
            return ttc_outcome.is_truth_chain_complete
        except Exception as _e:
            logger.warning(
                "unified_result_ingress: truth chain exception (non-fatal) " "task_id=%r error=%s",
                event.task_id,
                _e,
            )
            return False

    def _sync_lifecycle(self, event: NormalizedResultEvent) -> None:
        """Belt-and-suspenders CanonicalTaskRuntime lifecycle sync."""
        if not event.task_id:
            return
        try:
            from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

            _runtime = get_canonical_task_runtime()
            s = event.normalized_status.lower()
            if s == "failed":
                _target = TaskLifecycle.FAILED
            elif s == "cancelled":
                _target = TaskLifecycle.CANCELLED
            elif s == "degraded":
                _target = TaskLifecycle.DEGRADED
            else:
                _target = TaskLifecycle.COMPLETED
            _runtime.update_lifecycle(event.task_id, _target)
        except Exception as _e:
            logger.debug("unified_result_ingress: lifecycle sync skipped (non-fatal): %s", _e)

    def _notify_completion(self, event: NormalizedResultEvent) -> bool:
        """Notify CanonicalCompletionIngress so awaiters are unblocked."""
        if not event.task_id:
            return False
        try:
            from core.canonical_completion_ingress import get_canonical_completion_ingress

            ingress = get_canonical_completion_ingress()

            class _Envelope:
                is_terminal: bool = True
                handoff_id: str = ""
                task_id: str = ""
                problem_closed: bool = False
                final_answer_ready: bool = False
                final_user_response: str = ""
                problem_solved: bool = False

            env = _Envelope()
            env.is_terminal = True
            env.handoff_id = event.payload.get("handoff_id") or ""
            env.task_id = event.task_id
            env.problem_closed = bool(event.payload.get("problem_closed"))
            env.final_answer_ready = bool(event.payload.get("final_answer_ready"))
            env.final_user_response = str(event.payload.get("final_user_response") or "")
            env.problem_solved = bool(event.payload.get("problem_solved"))
            acceptance_verdict = self._normalize_optional_context_value(
                event.payload.get("_acceptance_verdict_for_completion_ingress")
            )
            android_participation_tier = self._normalize_optional_context_value(
                event.payload.get("_android_participation_tier_for_completion_ingress")
            )
            android_device_id = self._normalize_optional_context_value(
                event.payload.get("_android_device_id_for_completion_ingress")
            )

            # These best-effort hints (acceptance_verdict,
            # android_participation_tier, android_device_id) are populated by
            # _stamp_android_truth_context(). If SSOT stamping is unavailable,
            # they remain None and completion ingress still degrades gracefully.
            notify_with_context = getattr(ingress, "notify_with_android_context", None)
            has_context_notify = self._has_context_notification_method(ingress)

            if has_context_notify:
                notified = bool(
                    notify_with_context(
                        env,
                        android_participation_tier=android_participation_tier,
                        android_device_id=android_device_id,
                        acceptance_verdict=acceptance_verdict,
                    )
                )
            else:
                notified = ingress.notify(env)
            if not notified:
                logger.warning(
                    "unified_result_ingress: completion ingress returned non-notified " "task_id=%r source=%s",
                    event.task_id,
                    event.source_channel.value,
                )
                return False
            logger.debug(
                "unified_result_ingress: completion ingress notified " "task_id=%r source=%s",
                event.task_id,
                event.source_channel.value,
            )
            return True
        except Exception as _e:
            logger.debug("unified_result_ingress: completion ingress skipped (non-fatal): %s", _e)
            return False

    @staticmethod
    def _has_context_notification_method(ingress: Any) -> bool:
        # MagicMock-style test doubles can synthesize arbitrary callable
        # attributes via __getattr__(). Require a class-level or explicitly
        # attached instance attribute so mock-only completion ingress objects
        # still exercise the plain notify() fallback path.
        return callable(getattr(type(ingress), "notify_with_android_context", None)) or (
            "notify_with_android_context" in getattr(ingress, "__dict__", {})
        )

    def _apply_problem_solving_closure_fallback(self, event: NormalizedResultEvent) -> None:
        """Backfill closure booleans from Android wire closure class.

        This is a boundary fallback and intentionally monotonic:
        it only upgrades missing/false booleans to ``True`` when the Android
        structured closure class indicates solved/closed.
        """
        payload = event.payload if isinstance(event.payload, dict) else {}
        if not payload:
            return

        closure_class_raw = payload.get("problem_solving_closure_class")
        closure_class = self._normalize_optional_context_value(closure_class_raw)
        if not closure_class:
            return

        derived = self._derive_problem_closure_booleans_from_class(closure_class)
        if not derived:
            return

        derived_problem_solved = bool(derived.get("problem_solved"))
        derived_problem_closed = bool(derived.get("problem_closed"))

        if derived_problem_solved and not bool(payload.get("problem_solved")):
            payload["problem_solved"] = True
        if derived_problem_closed and not bool(payload.get("problem_closed")):
            payload["problem_closed"] = True

    def _derive_problem_closure_booleans_from_class(
        self,
        closure_class: str,
    ) -> Optional[Dict[str, bool]]:
        """Translate Android ``problem_solving_closure_class`` into booleans."""
        normalized = str(closure_class).strip().lower()
        if not normalized:
            return None

        tokens = {tok for tok in re.split(r"[^a-z0-9]+", normalized) if tok}
        if not tokens:
            return None

        unsolved = "unsolved" in tokens or ("not" in tokens and "solved" in tokens)
        solved = "solved" in tokens and not unsolved
        closed = (
            solved
            or "closed" in tokens
            or "closure" in tokens
            or "completed" in tokens
            or "done" in tokens
            or "terminal" in tokens
        )

        if not solved and not closed:
            return None
        return {
            "problem_solved": solved,
            "problem_closed": closed,
        }

    def _resolve_bridge_pending(self, bridge: Any, event: NormalizedResultEvent) -> bool:
        """Resolve any _pending_responses future keyed by task_id in bridge."""
        try:
            pending = getattr(bridge, "_pending_responses", None)
            if pending is None:
                return False
            future = pending.pop(event.task_id, None)
            if future is None:
                return False
            if not future.done():
                result_payload = {
                    "status": event.normalized_status,
                    "task_id": event.task_id,
                    "result": event.payload.get("result", ""),
                    "source": event.source_channel.value,
                }
                future.set_result(result_payload)
                logger.debug(
                    "unified_result_ingress: _pending_responses future resolved " "task_id=%r",
                    event.task_id,
                )
                return True
            return False
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: _pending_responses resolution skipped " "(non-fatal): %s",
                _e,
            )
            return False

    def _stamp_android_truth_context(
        self,
        event: NormalizedResultEvent,
        outcome: UnifiedResultIngressOutcome,
    ) -> None:
        """Stamp Android truth context and propagate completion payload hints.

        Priority:
        1) Android result-time payload truth (authoritative for delayed results)
        2) Processing-time SSOT snapshot truth (fallback only when payload absent)
        """
        if not event.device_id:
            return
        try:
            truth_dict = self._resolve_android_truth_context_with_fallback(event)
            outcome.android_truth_context = truth_dict
            if isinstance(event.payload, dict):
                tier = self._normalize_optional_context_value(truth_dict.get("participation_tier"))
                if tier:
                    event.payload["_android_participation_tier_for_completion_ingress"] = tier
                # event.device_id is already non-empty at this point, but we
                # still normalize to trim whitespace and keep completion
                # context formatting consistent across all fields.
                device_id_value = self._normalize_optional_context_value(event.device_id)
                if device_id_value:
                    event.payload["_android_device_id_for_completion_ingress"] = device_id_value
                verdict = self._normalize_optional_context_value(outcome.evidence_acceptance_verdict)
                if verdict:
                    event.payload["_acceptance_verdict_for_completion_ingress"] = verdict
        except Exception as _ssot_err:
            logger.debug(
                "unified_result_ingress: android truth SSOT stamp skipped " "(non-fatal) task_id=%r err=%s",
                event.task_id,
                _ssot_err,
            )

    def _resolve_android_truth_context_with_fallback(
        self,
        event: NormalizedResultEvent,
    ) -> Dict[str, Any]:
        """Resolve Android truth with payload-first fallback hierarchy."""
        ssot_truth: Dict[str, Any] = {}
        try:
            from core.v2_android_truth_ssot import build_v2_android_truth_block

            ssot_truth = build_v2_android_truth_block(event.device_id).to_dict()
        except Exception as _ssot_err:
            logger.debug(
                "unified_result_ingress: android truth SSOT read skipped " "(non-fatal) task_id=%r err=%s",
                event.task_id,
                _ssot_err,
            )

        merged_truth: Dict[str, Any] = dict(ssot_truth)
        payload = event.payload if isinstance(event.payload, dict) else {}
        truth_source_by_field: Dict[str, str] = {}
        ssot_sources = ssot_truth.get("sources")
        ssot_fallback_allowed = self._is_valid_ssot_sources_collection(ssot_sources)
        truth_fields = (
            "participation_tier",
            "dispatch_eligible",
            "runtime_constrained",
            "local_mode_active",
            "local_loop_ready",
        )

        for truth_field in truth_fields:
            payload_value = payload.get(truth_field)
            if self._has_meaningful_truth_value(payload_value):
                merged_truth[truth_field] = payload_value
                truth_source_by_field[truth_field] = "result_payload"
                continue

            if ssot_fallback_allowed:
                ssot_value = ssot_truth.get(truth_field)
                if self._has_meaningful_truth_value(ssot_value):
                    merged_truth[truth_field] = ssot_value
                    truth_source_by_field[truth_field] = "ssot_snapshot"

        if truth_source_by_field:
            merged_truth["android_truth_source_by_field"] = truth_source_by_field
        return merged_truth

    @staticmethod
    def _has_meaningful_truth_value(value: Any) -> bool:
        """Return True when truth value should be considered present.

        ``False`` is meaningful for runtime flags and must not be treated as missing.
        """
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    @staticmethod
    def _is_valid_ssot_sources_collection(value: Any) -> bool:
        """Return True when SSOT sources indicate a usable snapshot basis."""
        return isinstance(value, Collection) and not isinstance(value, (str, bytes, bytearray, dict)) and len(value) > 0

    @staticmethod
    def _normalize_optional_context_value(value: Any) -> Optional[str]:
        """Normalize completion-ingress context values to Optional[str].

        Returns ``None`` for missing values, blank strings, and booleans.
        Booleans are intentionally filtered out to avoid ambiguous implicit
        stringification (``"True"``/``"False"``) in completion context fields.
        """
        if value is None or isinstance(value, bool):
            # Keep booleans out of completion context to avoid downstream
            # treating textual "True"/"False" as semantic verdict/tier values.
            return None
        text = str(value).strip()
        return text or None

    def _classify_and_apply_evidence_gate(
        self,
        event: NormalizedResultEvent,
        outcome: UnifiedResultIngressOutcome,
    ) -> None:
        """PR-4: Build an execution evidence record and apply the acceptance gate.

        This step classifies the execution evidence state for this result and
        derives an :class:`~core.result_truth_acceptance_gate.ResultAcceptanceVerdict`
        that affects downstream propagation (user closure, operator surface,
        board projection).

        Stamps ``outcome`` with ``execution_evidence_state``,
        ``evidence_trust_level``, ``evidence_acceptance_verdict``, and
        ``execution_evidence_record`` fields.  If verdict is ``quarantine`` or
        ``reject``, clears ``is_fully_closed`` so the result does not propagate
        to user-facing problem closure.

        Failures are caught and logged at WARNING level; the processing chain
        continues regardless (additive, non-blocking).
        """
        try:
            from core.execution_evidence_model import build_execution_evidence_record
            from core.result_truth_acceptance_gate import apply_acceptance_gate

            # Extract Android proof class from payload if present
            android_proof_class = (
                event.payload.get("proof_class", "") or event.payload.get("android_proof_class", "") or ""
            )
            android_runtime_truth_context: Dict[str, Any] = {}
            acceptance_evidence_hint: Dict[str, Any] = {}
            if event.device_id:
                try:
                    from core.v2_android_truth_ssot import build_v2_android_truth_block

                    truth_dict = build_v2_android_truth_block(event.device_id).to_dict()
                    if truth_dict.get("sources"):
                        participation_tier = str(truth_dict.get("participation_tier") or "").strip()
                        if participation_tier in {
                            "dispatch_eligible",
                            "distributed_participant",
                        }:
                            android_runtime_truth_context["participation_tier"] = participation_tier
                        if truth_dict.get("dispatch_eligible") is True:
                            android_runtime_truth_context["dispatch_eligible"] = True
                        if truth_dict.get("runtime_constrained") is True:
                            android_runtime_truth_context["runtime_constrained"] = True
                        if truth_dict.get("local_mode_active") is True:
                            android_runtime_truth_context["local_mode_active"] = True
                        if truth_dict.get("local_loop_ready") is True:
                            android_runtime_truth_context["local_loop_ready"] = True
                except Exception as _truth_err:
                    logger.debug(
                        "unified_result_ingress: android evidence truth context skipped "
                        "(non-fatal) task_id=%r err=%s",
                        event.task_id,
                        _truth_err,
                    )
                try:
                    from core.android_acceptance_evidence_store import (
                        get_latest_device_acceptance_evidence_dict,
                    )

                    acceptance_evidence_hint = get_latest_device_acceptance_evidence_dict(event.device_id)
                except Exception as _acceptance_err:
                    logger.debug(
                        "unified_result_ingress: android acceptance evidence lookup skipped "
                        "(non-fatal) task_id=%r err=%s",
                        event.task_id,
                        _acceptance_err,
                    )
            mapped_acceptance_proof_class = str(
                acceptance_evidence_hint.get("mapped_android_proof_class") or ""
            ).strip()
            if not android_proof_class and mapped_acceptance_proof_class:
                # 当 result payload 未携带 proof_class 时，使用最近一次
                # DEVICE_ACCEPTANCE_REPORT 映射出的 proof_class 作为权威兜底，
                # 让 acceptance evidence 真正进入 V2 evidence gate。
                android_proof_class = mapped_acceptance_proof_class
                android_runtime_truth_context["proof_class_source"] = "device_acceptance_report"
            if acceptance_evidence_hint:
                android_runtime_truth_context["acceptance_tag"] = acceptance_evidence_hint.get("acceptance_tag") or ""
                android_runtime_truth_context["acceptance_snapshot_id"] = (
                    acceptance_evidence_hint.get("snapshot_id") or ""
                )
                android_runtime_truth_context["acceptance_missing_dimensions"] = list(
                    acceptance_evidence_hint.get("missing_dimensions") or []
                )
                android_runtime_truth_context["acceptance_dimension_states"] = dict(
                    acceptance_evidence_hint.get("dimension_states") or {}
                )
                android_runtime_truth_context["acceptance_mapping_reason"] = (
                    acceptance_evidence_hint.get("mapping_reason") or ""
                )
                android_runtime_truth_context["acceptance_evidence_authority"] = (
                    acceptance_evidence_hint.get("evidence_authority") or ""
                )
                android_runtime_truth_context["acceptance_evidence_completeness"] = (
                    acceptance_evidence_hint.get("evidence_completeness") or ""
                )
                android_runtime_truth_context["acceptance_closure_significance"] = (
                    acceptance_evidence_hint.get("closure_significance") or ""
                )
                android_runtime_truth_context["acceptance_canonical_confirmation_required"] = bool(
                    acceptance_evidence_hint.get("canonical_confirmation_required")
                )

            evidence_record = build_execution_evidence_record(
                task_id=event.task_id,
                device_id=event.device_id,
                normalized_status=event.normalized_status,
                source_channel=event.source_channel.value,
                truth_chain_complete=outcome.truth_chain_complete,
                android_proof_class=android_proof_class,
                android_runtime_truth_context=android_runtime_truth_context,
                is_duplicate=outcome.was_deduplicated,
                payload=event.payload,
            )

            # Stamp evidence record onto outcome for operator/audit consumers
            outcome.execution_evidence_record = evidence_record.to_dict()
            outcome.effective_android_proof_class = (
                outcome.execution_evidence_record.get("effective_android_proof_class", "") or ""
            )
            outcome.android_evidence_resolution = (
                outcome.execution_evidence_record.get("android_evidence_resolution", "") or ""
            )
            outcome.android_inferred_evidence_strength = (
                outcome.execution_evidence_record.get("android_inferred_evidence_strength", "") or ""
            )
            outcome.android_evidence_runtime_context = dict(
                outcome.execution_evidence_record.get("android_evidence_runtime_context", {}) or {}
            )

            # Apply acceptance gate — may clear is_fully_closed for quarantine/reject
            acceptance = apply_acceptance_gate(evidence_record, outcome)

            # Record to the operator observability ring buffer (non-blocking)
            try:
                from core.operator_execution_observability_surface import (
                    record_operator_evidence_entry,
                )

                record_operator_evidence_entry(
                    task_id=event.task_id,
                    device_id=event.device_id,
                    evidence_state=acceptance.evidence_state,
                    trust_level=acceptance.evidence_trust_level,
                    acceptance_verdict=acceptance.verdict.value,
                    truth_chain_complete=outcome.truth_chain_complete,
                    operator_warning=acceptance.operator_warning,
                    android_proof_class=android_proof_class,
                    effective_android_proof_class=outcome.effective_android_proof_class,
                    android_evidence_resolution=outcome.android_evidence_resolution,
                    android_inferred_evidence_strength=outcome.android_inferred_evidence_strength,
                    android_evidence_runtime_context=outcome.android_evidence_runtime_context,
                    source_channel=event.source_channel.value,
                    diagnosis=list(acceptance.diagnosis),
                )
            except Exception as _obs_err:
                logger.debug(
                    "unified_result_ingress: operator observability record skipped " "(non-fatal) task_id=%r err=%s",
                    event.task_id,
                    _obs_err,
                )

        except Exception as _e:
            logger.warning(
                "unified_result_ingress: evidence gate skipped (non-fatal) " "task_id=%r source=%s err=%s",
                event.task_id,
                event.source_channel.value,
                _e,
            )

    def _log_outcome(self, event: NormalizedResultEvent, outcome: UnifiedResultIngressOutcome) -> None:
        if outcome.replay_ordering_adjudicated:
            logger.info(
                "unified_result_ingress: result processed "
                "task_id=%r status=%r source=%s disposition=%s "
                "truth_chain=%s completion=%s store=%s "
                "replay_ordering_decision=%s replay_ordering_verdict=%s",
                event.task_id,
                event.normalized_status,
                event.source_channel.value,
                outcome.completion_disposition,
                outcome.truth_chain_complete,
                outcome.completion_notified,
                outcome.store_task_result_ran,
                outcome.replay_ordering_decision,
                outcome.replay_ordering_verdict,
            )
        else:
            logger.info(
                "unified_result_ingress: result processed "
                "task_id=%r status=%r source=%s disposition=%s "
                "truth_chain=%s completion=%s store=%s",
                event.task_id,
                event.normalized_status,
                event.source_channel.value,
                outcome.completion_disposition,
                outcome.truth_chain_complete,
                outcome.completion_notified,
                outcome.store_task_result_ran,
            )

    def _looks_like_android_wire_message(self, event: NormalizedResultEvent) -> bool:
        payload = event.payload or {}
        raw_message = event.raw_message or {}
        return bool(
            raw_message.get("_cross_repo_schema_version_gate")
            or raw_message.get("version")
            or payload.get("version")
            or raw_message.get("schema_version")
            or payload.get("schema_version")
            or raw_message.get("android_completion_closure_uplink_schema_version")
            or payload.get("android_completion_closure_uplink_schema_version")
        )

    def _evaluate_cross_repo_dedupe_contract(
        self,
        event: NormalizedResultEvent,
    ) -> tuple[str, str, Dict[str, Any]]:
        if event.source_channel not in {
            ResultSourceChannel.CANONICAL_WS,
            ResultSourceChannel.COMPAT_WS,
            ResultSourceChannel.REPLAY,
        }:
            return "", "", {}

        if not self._looks_like_android_wire_message(event):
            return "", "", {}

        wire_message = event.raw_message or event.payload or {}
        schema_gate_evidence = wire_message.get("_cross_repo_schema_version_gate")
        if isinstance(schema_gate_evidence, dict):
            gate_action = str(schema_gate_evidence.get("action") or "").strip().lower()
            if gate_action in {"reject", "degrade"}:
                return (
                    gate_action,
                    str(schema_gate_evidence.get("reason") or f"schema_gate_{gate_action}"),
                    {"schema_gate": dict(schema_gate_evidence)},
                )

        try:
            from contracts.cross_repo_schema_version_gate import (
                evaluate_android_uplink_dedupe_contract,
            )

            decision = evaluate_android_uplink_dedupe_contract(
                message_type=event.raw_message_type or event.normalized_result_kind,
                message=wire_message,
            )
        except Exception as exc:
            logger.debug(
                "unified_result_ingress: cross-repo dedupe contract import/eval failed, using inline fallback: %s",
                exc,
            )
            action, reason, evidence = self._evaluate_cross_repo_dedupe_contract_fallback(
                message_type=event.raw_message_type or event.normalized_result_kind,
                wire_message=wire_message,
                error=str(exc),
            )
            return action, reason, evidence

        if decision is None:
            action, reason, evidence = self._evaluate_cross_repo_dedupe_contract_fallback(
                message_type=event.raw_message_type or event.normalized_result_kind,
                wire_message=wire_message,
                error="contract_returned_none",
            )
            return action, reason, evidence
        if decision.action == "accept":
            return "", "", {"android_dedupe_contract": decision.to_dict()}
        return decision.action, decision.reason, {"android_dedupe_contract": decision.to_dict()}

    @staticmethod
    def _extract_wire_message_field(wire_message: Dict[str, Any], *field_names: str) -> str:
        """Extract a field value from a wire message.

        Search order is top-level ``wire_message`` → nested ``payload`` →
        nested ``payload.schema_gate``.  The first non-empty value among
        ``field_names`` wins.
        """
        payload = wire_message.get("payload")
        payload_mapping = payload if isinstance(payload, dict) else {}
        schema_gate = payload_mapping.get("schema_gate")
        schema_gate_mapping = schema_gate if isinstance(schema_gate, dict) else {}
        for field_name in field_names:
            for candidate in (
                wire_message.get(field_name),
                payload_mapping.get(field_name),
                schema_gate_mapping.get(field_name),
            ):
                if candidate is not None:
                    normalized_candidate = str(candidate).strip()
                    if normalized_candidate:
                        return normalized_candidate
        return ""

    def _evaluate_cross_repo_dedupe_contract_fallback(
        self,
        *,
        message_type: str,
        wire_message: Dict[str, Any],
        error: str,
    ) -> tuple[str, str, Dict[str, Any]]:
        """Fallback Android dedupe contract evaluator.

        Parameters
        ----------
        message_type:
            Normalized wire message type to evaluate.
        wire_message:
            Raw or normalized message payload.
        error:
            Stringified import/evaluation error from the canonical contract path.

        Returns
        -------
        tuple[str, str, Dict[str, Any]]
            ``(action, reason, evidence)`` where action is ``"degrade"`` or
            empty string, reason is the machine-readable gate reason, and
            evidence contains fallback provenance and contract diagnostics.
        """
        normalized_type = str(message_type or "").strip().lower()
        fallback_evidence = {
            "fallback": {
                "used": True,
                "reason": "inline_unified_result_ingress_fallback",
                "contract_error": str(error or ""),
            }
        }
        if normalized_type in ANDROID_RESULT_DEDUPE_MESSAGE_TYPES:
            task_id = self._extract_wire_message_field(wire_message, "task_id", "goal_id")
            idempotency_key = self._extract_wire_message_field(wire_message, "idempotency_key")
            completion_emission_id = self._extract_wire_message_field(
                wire_message,
                "completion_emission_id",
                "emission_id",
                "completion_id",
                "result_id",
            )
            missing_fields = []
            if not task_id:
                missing_fields.append("task_id")
            if not idempotency_key:
                missing_fields.append("idempotency_key")
            if not completion_emission_id:
                missing_fields.append("completion_emission_id")
            reason = "canonical_dedupe_contract_satisfied" if not missing_fields else "missing_canonical_result_dedupe_fields"
            action = "" if not missing_fields else "degrade"
            fallback_evidence["android_dedupe_contract"] = {
                "action": "accept" if not missing_fields else "degrade",
                "message_type": normalized_type,
                "contract_class": "result",
                "reason": reason,
                "evidence": {
                    "task_id_present": bool(task_id),
                    "idempotency_key_present": bool(idempotency_key),
                    "completion_emission_id_present": bool(completion_emission_id),
                    "missing_fields": missing_fields,
                },
            }
            return action, reason if action else "", fallback_evidence

        if normalized_type in ANDROID_RECONCILIATION_DEDUPE_MESSAGE_TYPES:
            subject_identity = self._extract_wire_message_field(
                wire_message,
                "contract_id",
                "session_id",
                "runtime_session_id",
            )
            reconciliation_identity = self._extract_wire_message_field(
                wire_message,
                "reconciliation_id",
                "signal_id",
                "handoff_id",
                "event_id",
                "result_id",
                "completion_emission_id",
            )
            missing_fields = []
            if not subject_identity:
                missing_fields.append("contract_id|session_id")
            if not reconciliation_identity:
                missing_fields.append("reconciliation_id|signal_id|handoff_id")
            reason = (
                "canonical_dedupe_contract_satisfied"
                if not missing_fields
                else "missing_canonical_reconciliation_dedupe_fields"
            )
            action = "" if not missing_fields else "degrade"
            fallback_evidence["android_dedupe_contract"] = {
                "action": "accept" if not missing_fields else "degrade",
                "message_type": normalized_type,
                "contract_class": "reconciliation",
                "reason": reason,
                "evidence": {
                    "subject_identity_present": bool(subject_identity),
                    "reconciliation_identity_present": bool(reconciliation_identity),
                    "missing_fields": missing_fields,
                },
            }
            return action, reason if action else "", fallback_evidence

        return "", "", {}

    def _build_completion_lineage(
        self,
        event: NormalizedResultEvent,
    ) -> Dict[str, Any]:
        participant_id = str(event.participant_id or event.device_id or "").strip()
        completion_emission_id = str(event.completion_emission_id or "").strip()
        epoch_token = str(event.session_epoch) if event.session_epoch is not None else "unknown_epoch"
        lineage_key = (
            f"completion_lineage:{event.normalized_result_kind}:{event.task_id}:"
            f"{participant_id}:{epoch_token}:{completion_emission_id}"
        )
        return {
            "task_id": event.task_id,
            "device_id": event.device_id,
            "participant_id": participant_id,
            "session_epoch": event.session_epoch,
            "completion_emission_id": completion_emission_id,
            "source_channel": event.source_channel.value,
            "normalized_result_kind": event.normalized_result_kind,
            "normalized_status": event.normalized_status,
            "result_idempotency_key": event.idempotency_key,
            "completion_lineage_key": lineage_key,
        }

    def _fallback_joint_idempotency_evidence(
        self,
        event: NormalizedResultEvent,
        *,
        completion_lineage: Dict[str, Any],
        decision: str,
        stale_classification: str = "",
    ) -> Dict[str, Any]:
        evidence = dict(completion_lineage)
        evidence["joint_idempotency_decision"] = decision
        if stale_classification:
            evidence["stale_classification"] = stale_classification
        return evidence

    def _set_last_joint_idempotency_evidence(self, evidence: Dict[str, Any]) -> None:
        with self._lock:
            self._last_joint_idempotency_evidence = dict(evidence)

    def _consume_joint_idempotency_evidence(self) -> Dict[str, Any]:
        with self._lock:
            evidence = dict(self._last_joint_idempotency_evidence)
            self._last_joint_idempotency_evidence = {}
            return evidence

    def _build_problem_execution_closure(
        self,
        *,
        event: NormalizedResultEvent,
        outcome: UnifiedResultIngressOutcome,
    ) -> Dict[str, Any]:
        try:
            from core.nl_execution_spine import build_problem_execution_closure

            return build_problem_execution_closure(
                source_channel=event.source_channel.value,
                normalized_status=event.normalized_status,
                truth_chain_complete=outcome.truth_chain_complete,
                completion_notified=outcome.completion_notified,
                payload=event.payload,
                evidence_acceptance_verdict=outcome.evidence_acceptance_verdict,
            )
        except Exception as _err:
            logger.warning(
                "unified_result_ingress: problem_execution_closure build skipped "
                "(non-fatal) task_id=%r source=%s err_type=%s err=%s",
                event.task_id,
                event.source_channel.value,
                type(_err).__name__,
                _err,
                exc_info=True,
            )
            return {}


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_singleton: Optional[UnifiedResultIngress] = None
_singleton_lock = threading.Lock()


def get_unified_result_ingress() -> UnifiedResultIngress:
    """Return the process-wide :class:`UnifiedResultIngress` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = UnifiedResultIngress()
    return _singleton


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def ingest_result(event: NormalizedResultEvent) -> UnifiedResultIngressOutcome:
    """Synchronous convenience wrapper: ``get_unified_result_ingress().process(event)``."""
    return get_unified_result_ingress().process(event)


async def ingest_result_async(
    event: NormalizedResultEvent,
    *,
    store_fn: Any = None,
    bridge: Any = None,
) -> UnifiedResultIngressOutcome:
    """Async convenience wrapper with optional memory backflow and bridge resolution."""
    return await get_unified_result_ingress().process_async(event, store_fn=store_fn, bridge=bridge)


def get_last_result_closure_outcome() -> Dict[str, Any]:
    """Return the latest canonical closure summary observed by unified result ingress."""
    return get_unified_result_ingress().get_last_closure_outcome()


def normalize_status(raw_status: Optional[str]) -> str:
    """Map Android/device result status to canonical V2 task status.

    Centralised here so all result paths use the same mapping.

    Mapping:
        failed / error   → "failed"
        cancelled        → "cancelled"
        degraded         → "degraded"
        anything else    → "completed"
    """
    if not raw_status:
        return "completed"
    s = str(raw_status).lower().strip()
    if s in ("failed", "error"):
        return "failed"
    if s == "cancelled":
        return "cancelled"
    if s == "degraded":
        return "degraded"
    return "completed"


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "UNIFIED_RESULT_INGRESS_POLICY",
    "UNIFIED_RESULT_INGRESS_REPLAY_ORDERING_POLICY",
    "REPLAY_ORDERING_BLOCKING_DECISIONS",
    "ResultSourceChannel",
    "NormalizedResultEvent",
    "UnifiedResultIngressOutcome",
    "UnifiedResultIngress",
    "get_unified_result_ingress",
    "ingest_result",
    "ingest_result_async",
    "get_last_result_closure_outcome",
    "normalize_status",
]
