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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.UnifiedResultIngress")

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
    4. CanonicalCompletionIngress.notify()    (unblock awaiters)
    5. store_task_result / memory backflow    (async, best-effort)
    6. structured logging
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
            outcome.incomplete_reason = (
                f"continuity_rejected:{continuity_verdict}"
            )
            logger.warning(
                "unified_result_ingress: continuity gate rejected result "
                "task_id=%r verdict=%r source=%s",
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
                "unified_result_ingress: duplicate suppressed "
                "task_id=%r idempotency_key=%r source=%s",
                event.task_id,
                event.idempotency_key,
                event.source_channel.value,
            )
            return outcome

        self._record_idempotency(event)

        logger.info(
            "unified_result_ingress: processing result "
            "task_id=%r status=%r kind=%r source=%s channel=%s",
            event.task_id,
            event.normalized_status,
            event.normalized_result_kind,
            event.source_channel.value,
            event.trace_id or "",
        )

        # Step 2: four-step truth chain
        outcome.truth_chain_complete = self._run_truth_chain(event)

        # Step 3: CanonicalTaskRuntime lifecycle (belt-and-suspenders if not done
        # by truth chain's authority_state_update step)
        self._sync_lifecycle(event)

        # Step 4: CanonicalCompletionIngress notify
        outcome.completion_notified = self._notify_completion(event)

        # Step 5: structured logging
        self._log_outcome(event, outcome)

        # Determine overall closure
        outcome.is_fully_closed = (
            not outcome.was_deduplicated
            and outcome.truth_chain_complete
            and outcome.completion_notified
        )
        if not outcome.is_fully_closed and not outcome.incomplete_reason:
            parts = []
            if not outcome.truth_chain_complete:
                parts.append("truth_chain_incomplete")
            if not outcome.completion_notified:
                parts.append("completion_not_notified")
            outcome.incomplete_reason = "; ".join(parts) if parts else "unknown"
        outcome.problem_execution_closure = self._build_problem_execution_closure(
            event=event,
            outcome=outcome,
        )

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
                    "unified_result_ingress: store_task_result failed (non-fatal) "
                    "task_id=%r error=%s",
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
            report = evaluate_continuity_legality(
                ContinuityLegalityPath.TERMINAL_RESULT_INGESTION, ctx
            )
            return report.verdict.value
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: continuity legality gate unavailable "
                "(non-fatal, passing through): %s",
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
            logger.debug(
                "unified_result_ingress: idempotency check skipped (non-fatal): %s", _e
            )
            return False

    def _record_idempotency(self, event: NormalizedResultEvent) -> None:
        """Record the idempotency_key so subsequent duplicates are suppressed."""
        if not event.idempotency_key:
            return
        try:
            from core.durable_result_idempotency import record_result_idempotency
            record_result_idempotency(event.idempotency_key)
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: idempotency record skipped (non-fatal): %s", _e
            )

    def _run_truth_chain(self, event: NormalizedResultEvent) -> bool:
        """Run the four-step canonical truth chain and return True iff complete."""
        if not event.task_id:
            logger.debug(
                "unified_result_ingress: truth chain skipped — no task_id "
                "source=%s kind=%r",
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
                    "unified_result_ingress: truth chain incomplete "
                    "task_id=%r source=%s reason=%r",
                    event.task_id,
                    event.source_channel.value,
                    ttc_outcome.incomplete_reason,
                )
            return ttc_outcome.is_truth_chain_complete
        except Exception as _e:
            logger.warning(
                "unified_result_ingress: truth chain exception (non-fatal) "
                "task_id=%r error=%s",
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
            logger.debug(
                "unified_result_ingress: lifecycle sync skipped (non-fatal): %s", _e
            )

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

            env = _Envelope()
            env.is_terminal = True
            env.handoff_id = event.payload.get("handoff_id") or ""
            env.task_id = event.task_id

            notified = ingress.notify(env)
            if not notified:
                logger.warning(
                    "unified_result_ingress: completion ingress returned non-notified "
                    "task_id=%r source=%s",
                    event.task_id,
                    event.source_channel.value,
                )
                return False
            logger.debug(
                "unified_result_ingress: completion ingress notified "
                "task_id=%r source=%s",
                event.task_id,
                event.source_channel.value,
            )
            return True
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: completion ingress skipped (non-fatal): %s", _e
            )
            return False

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
                    "unified_result_ingress: _pending_responses future resolved "
                    "task_id=%r",
                    event.task_id,
                )
                return True
            return False
        except Exception as _e:
            logger.debug(
                "unified_result_ingress: _pending_responses resolution skipped "
                "(non-fatal): %s",
                _e,
            )
            return False

    def _log_outcome(
        self, event: NormalizedResultEvent, outcome: UnifiedResultIngressOutcome
    ) -> None:
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
    return await get_unified_result_ingress().process_async(
        event, store_fn=store_fn, bridge=bridge
    )


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
