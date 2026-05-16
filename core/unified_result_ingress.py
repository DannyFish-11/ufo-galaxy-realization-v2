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
import threading
import uuid
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.UnifiedResultIngress")

# Evidence verdicts that must block full closure in unified ingress.
EVIDENCE_CLOSURE_BLOCKING_VERDICTS = frozenset({"quarantine", "reject"})

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

UNIFIED_RESULT_INGRESS_POLICY: str = (
    "UNIFIED_RESULT_INGRESS_V1: core/unified_result_ingress.py is the single "
    "canonical result ingress.  ALL result source channels (canonical WS, "
    "compat WS, REST callback, replay, delegated/handoff) MUST normalise their "
    "result signal into a NormalizedResultEvent and pass it to "
    "ingest_result() before any state mutation occurs.  No competing result "
    "processing chain is permitted."
)


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

    # ── Raw message (for downstream helpers that need the full envelope) ─────
    raw_message: Dict[str, Any] = field(default_factory=dict)
    """The complete inbound message dict before any normalisation."""

    def __post_init__(self) -> None:
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
    1. idempotency check / record
    2. run_task_result_truth_chain (four-step truth chain)
    3. CanonicalTaskRuntime lifecycle update  (if not already done by step 2)
    4. Evidence quality classification (PR-4: execution evidence model + acceptance gate)
    5. Stamp Android truth SSOT context (participation tier / readiness basis)
    6. CanonicalCompletionIngress notify_with_android_context() / notify()
    7. store_task_result / memory backflow    (async, best-effort)
    8. structured logging
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

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

        # Step 0: unified continuity legality gate
        # Terminal result ingestion MUST submit to the same continuity
        # authority as reconnect, replay, and delegated recovery paths.
        # Per ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY.
        continuity_verdict = self._check_continuity_legality(event)
        outcome.continuity_legality_verdict = continuity_verdict
        if continuity_verdict in ("reject", "require_review"):
            outcome.continuity_rejected = True
            outcome.incomplete_reason = f"continuity_rejected:{continuity_verdict}"
            logger.warning(
                "unified_result_ingress: continuity gate rejected result " "task_id=%r verdict=%r source=%s",
                event.task_id,
                continuity_verdict,
                event.source_channel.value,
            )
            return outcome

        # Step 1: idempotency
        if self._check_idempotency(event):
            outcome.was_deduplicated = True
            outcome.incomplete_reason = "deduplicated"
            logger.debug(
                "unified_result_ingress: duplicate suppressed " "task_id=%r idempotency_key=%r source=%s",
                event.task_id,
                event.idempotency_key,
                event.source_channel.value,
            )
            return outcome

        self._record_idempotency(event)

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
        outcome.is_fully_closed = (
            not outcome.was_deduplicated
            and outcome.truth_chain_complete
            and outcome.completion_notified
            and not evidence_gate_blocked
        )
        if not outcome.is_fully_closed and not outcome.incomplete_reason:
            parts = []
            if not outcome.truth_chain_complete:
                parts.append("truth_chain_incomplete")
            if not outcome.completion_notified:
                parts.append("completion_not_notified")
            if evidence_gate_blocked:
                parts.append(f"evidence_gate:{evidence_verdict}")
            outcome.incomplete_reason = "; ".join(parts) if parts else "unknown"
        outcome.problem_execution_closure = self._build_problem_execution_closure(
            event=event,
            outcome=outcome,
        )
        outcome.task_completed = bool(outcome.problem_execution_closure.get("task_completed"))
        outcome.problem_solved = bool(outcome.problem_execution_closure.get("problem_solved"))
        outcome.problem_solved_via = str(outcome.problem_execution_closure.get("problem_solved_via") or "")

        return outcome

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

    def _check_continuity_legality(self, event: NormalizedResultEvent) -> str:
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
            report = evaluate_continuity_legality(ContinuityLegalityPath.TERMINAL_RESULT_INGESTION, ctx)
            return report.verdict.value
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: continuity legality gate unavailable " "(non-fatal, passing through): %s",
                _e,
            )
            return "allow"

    def _check_idempotency(self, event: NormalizedResultEvent) -> bool:
        """Return True iff the idempotency_key is already recorded."""
        if not event.idempotency_key:
            return False
        try:
            from core.durable_result_idempotency import check_result_idempotency

            return check_result_idempotency(event.idempotency_key)
        except Exception as _e:
            logger.debug("unified_result_ingress: idempotency check skipped (non-fatal): %s", _e)
            return False

    def _record_idempotency(self, event: NormalizedResultEvent) -> None:
        """Record the idempotency_key so subsequent duplicates are suppressed."""
        if not event.idempotency_key:
            return
        try:
            from core.durable_result_idempotency import record_result_idempotency

            record_result_idempotency(event.idempotency_key)
        except Exception as _e:
            logger.debug("unified_result_ingress: idempotency record skipped (non-fatal): %s", _e)

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

            if callable(notify_with_context):
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
                "unified_result_ingress: android truth SSOT read skipped "
                "(non-fatal) task_id=%r err=%s",
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
        return (
            isinstance(value, Collection)
            and not isinstance(value, (str, bytes, bytearray, dict))
            and len(value) > 0
        )

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
        logger.info(
            "unified_result_ingress: result processed "
            "task_id=%r status=%r source=%s "
            "truth_chain=%s completion=%s store=%s",
            event.task_id,
            event.normalized_status,
            event.source_channel.value,
            outcome.truth_chain_complete,
            outcome.completion_notified,
            outcome.store_task_result_ran,
        )

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
    "ResultSourceChannel",
    "NormalizedResultEvent",
    "UnifiedResultIngressOutcome",
    "UnifiedResultIngress",
    "get_unified_result_ingress",
    "ingest_result",
    "ingest_result_async",
    "normalize_status",
]
