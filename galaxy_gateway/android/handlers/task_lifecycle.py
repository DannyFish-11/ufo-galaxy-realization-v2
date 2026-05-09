"""
galaxy_gateway/android/handlers/task_lifecycle.py

Handles task result, task end, task progress, command result, and error messages.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, Optional

from galaxy_gateway.protocol.aip_v3 import TaskStatus
from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Observable error counters — machine-checkable by tests and monitoring.
# These counters make previously-silent failure paths detectable without
# requiring log-scraping.  A non-zero value signals that the result
# ingestion truth chain has partially failed and warrants investigation.
#
# Note: these are module-level integers rather than a class so that they can
# be imported and read directly by tests and monitoring exporters with a
# single import.  Use get_result_ingestion_error_counts() for a snapshot dict.
# ---------------------------------------------------------------------------

#: Counts how many times the PR-13 execution-signal reconciler raised an
#: unexpected exception.  Incremented even when the exception is non-fatal.
RESULT_RECONCILE_ERRORS: int = 0

#: Counts how many times the PR-4V2 participant-truth ingress raised an
#: unexpected exception.
RESULT_TRUTH_INGRESS_ERRORS: int = 0

#: Counts how many times the DeviceRouter completion notification raised
#: an unexpected exception.
RESULT_DEVICE_ROUTER_ERRORS: int = 0

#: Counts how many times the OpenClawd memory backflow raised an unexpected
#: exception.
RESULT_MEMORY_BACKFLOW_ERRORS: int = 0


def get_result_ingestion_error_counts() -> dict:
    """Return a snapshot dict of all result-ingestion error counters.

    Intended for use by tests, health-check endpoints, and metrics exporters.
    The returned dict has stable string keys so callers are not coupled to the
    module-level variable names.

    Example::

        counts = get_result_ingestion_error_counts()
        if any(counts.values()):
            log_alert("truth chain errors detected", counts)
    """
    return {
        "reconcile_errors": RESULT_RECONCILE_ERRORS,
        "truth_ingress_errors": RESULT_TRUTH_INGRESS_ERRORS,
        "device_router_errors": RESULT_DEVICE_ROUTER_ERRORS,
        "memory_backflow_errors": RESULT_MEMORY_BACKFLOW_ERRORS,
        "total_errors": (
            RESULT_RECONCILE_ERRORS
            + RESULT_TRUTH_INGRESS_ERRORS
            + RESULT_DEVICE_ROUTER_ERRORS
            + RESULT_MEMORY_BACKFLOW_ERRORS
        ),
    }

# OpenClawd memory backflow — top-level import so tests can patch() it.
try:
    from core.openclawd_memory_backflow import store_task_result
except ImportError:
    store_task_result = None  # type: ignore[assignment]

# PR-13: canonical host-side reconciliation binding — top-level import so
# tests can patch() it and so the import failure is handled gracefully.
try:
    from core.android_execution_signal_reconciler import reconcile_inbound_message as _reconcile_inbound_message
except ImportError:
    _reconcile_inbound_message = None  # type: ignore[assignment]

# PR-4V2: Android participant/session/runtime truth ingress — top-level import
# so tests can patch() it and import failures are handled gracefully.
try:
    from core.android_participant_truth_ingress import ingest_android_participant_truth_message as _ingest_participant_truth
except ImportError:
    _ingest_participant_truth = None  # type: ignore[assignment]

# PR-TTC: Canonical must-run truth chain for task_result processing.
# Top-level import so tests can patch() the chain function.
try:
    from core.task_result_canonical_truth_chain import run_task_result_truth_chain as _run_task_result_truth_chain
except ImportError:
    _run_task_result_truth_chain = None  # type: ignore[assignment]

# PR-V1-RESULT: V1 unified continuity legality authority — top-level import so
# tests can patch() the evaluate function and import failures are handled
# gracefully (fail-open so existing deployments are never broken by a missing
# authority module).
try:
    from core.unified_continuity_legality_authority import (
        ContinuityLegalityContext as _ContinuityLegalityContext,
        ContinuityLegalityPath as _ContinuityLegalityPath,
        evaluate_continuity_legality as _evaluate_continuity_legality,
    )
except ImportError:
    _ContinuityLegalityContext = None  # type: ignore[assignment,misc]
    _ContinuityLegalityPath = None  # type: ignore[assignment]
    _evaluate_continuity_legality = None  # type: ignore[assignment]

# PR-V1-RESULT: Policy sentinel — participant result ingress must submit to the
# V1 unified continuity legality authority before truth-chain execution.
RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY = (
    "Participant result ingress MUST evaluate V1 unified continuity legality "
    "(TERMINAL_RESULT_INGESTION path) before entering participant truth ingress, "
    "execution signal reconciliation, canonical lifecycle update, or canonical "
    "completion ingress.  Stale, revoked, detached, or otherwise "
    "continuity-invalid runtime/session identities MUST be rejected before "
    "truth-chain execution."
)

# ---------------------------------------------------------------------------
# Compat lifecycle path signal guard
# ---------------------------------------------------------------------------
# Prevents the same lifecycle signal (identified by idempotency_key or
# message_id) from being processed more than once when the compat layer
# normalises v1/v2 messages before dispatch.  This is a process-local,
# in-memory bounded ordered dict — it acts as a 512-slot LRU seen-set.
# OrderedDict gives O(1) lookup and O(1) ordered eviction; entries older
# than the 512-slot window are automatically discarded.

_SIGNAL_GUARD_CAPACITY: int = 512
_processed_signals: OrderedDict = OrderedDict()

_NON_TERMINAL_STATUS_VALUES = frozenset(
    {
        "created",
        "queued",
        "admitted",
        "planned",
        "routed",
        "dispatch",
        "dispatched",
        "pending",
        "running",
        "result",
        "partial_result",
        "continue",
    }
)
_CANCELLED_STATUS_VALUES = frozenset({"cancelled", "canceled"})
_TERMINAL_COMPLETED_STATUS_VALUES = frozenset(
    {"completed", "failed", "degraded", "success", "error"}
)


def _signal_guard_accept(message: Dict[str, Any]) -> bool:
    """Return True and record the signal if it has not been seen before.

    Returns False (reject / skip) if the idempotency_key or message_id of
    *message* was already processed within the current guard window.  This
    prevents the compat normalisation layer from causing the same lifecycle
    event to be reconciled or acted upon twice.

    The guard key prefers ``idempotency_key`` (injected by the compat layer)
    over ``message_id`` (supplied by the sender).  When neither is present the
    signal is always accepted so that the guard is never a blocking error path.
    """
    key = message.get("idempotency_key") or message.get("message_id")
    if not key:
        # No stable identity — cannot guard; allow through.
        return True
    key = str(key)
    if key in _processed_signals:
        logger.debug(
            "task_lifecycle signal guard: duplicate signal suppressed key=%r type=%s",
            key, message.get("type"),
        )
        return False
    # Record as seen; evict the oldest entry first when at capacity so the
    # dict never temporarily exceeds _SIGNAL_GUARD_CAPACITY.
    if len(_processed_signals) >= _SIGNAL_GUARD_CAPACITY:
        _processed_signals.popitem(last=False)
    _processed_signals[key] = True
    return True


def _extract_status_value(raw_status: Any) -> str:
    """Normalise any runtime lifecycle/status object to a lower-case string."""
    if hasattr(raw_status, "value"):
        raw_status = raw_status.value
    return str(raw_status or "").strip().lower()


def _map_runtime_status_to_task_status(raw_status: Any) -> Optional[str]:
    """Map runtime/canonical lifecycle values to AIP task status values."""
    status = _extract_status_value(raw_status)
    if not status:
        return None
    if status in _CANCELLED_STATUS_VALUES:
        return TaskStatus.CANCELLED.value
    if status in {"failed", "degraded", "error"}:
        return TaskStatus.FAILED.value
    if status in {"completed", "success"}:
        return TaskStatus.COMPLETED.value
    if status in {"running", "result", "partial_result", "continue"}:
        return TaskStatus.RUNNING.value
    if status in _NON_TERMINAL_STATUS_VALUES:
        return TaskStatus.PENDING.value
    return None


def _read_canonical_runtime_status(task_id: Optional[str]) -> Optional[str]:
    """Return authoritative task status from canonical runtimes when available."""
    if not task_id:
        return None

    try:
        from core.task_graph_runtime import get_task_graph_runtime

        node = get_task_graph_runtime().get_node_by_task_id(task_id)
        if node is not None:
            mapped = _map_runtime_status_to_task_status(getattr(node, "state", None))
            if mapped:
                return mapped
    except Exception as exc:
        logger.warning("task_lifecycle: TaskGraphRuntime status lookup skipped: %s", exc)

    try:
        from core.canonical_task import get_canonical_task_runtime

        task = get_canonical_task_runtime().get_by_task_id(task_id)
        if task is not None:
            mapped = _map_runtime_status_to_task_status(getattr(task, "lifecycle", None))
            if mapped:
                return mapped
    except Exception as exc:
        logger.debug("task_lifecycle: CanonicalTaskRuntime status lookup skipped: %s", exc)

    try:
        from core.routes._shared import task_queue

        if task_id in task_queue:
            mapped = _map_runtime_status_to_task_status(task_queue[task_id].get("status"))
            if mapped:
                return mapped
    except Exception as exc:
        logger.debug("task_lifecycle: task_queue status lookup skipped: %s", exc)

    return None


def _apply_canonical_task_cancellation(task_id: Optional[str]) -> tuple[bool, Optional[str]]:
    """Cancel a task across canonical runtime surfaces when it is known."""
    if not task_id:
        return False, "task_not_found"

    known = False
    cancellable = False
    already_cancelled = False
    already_completed = False

    try:
        from core.routes._shared import task_queue

        task_entry = task_queue.get(task_id)
        if task_entry is not None:
            known = True
            status = _extract_status_value(task_entry.get("status"))
            if status in _CANCELLED_STATUS_VALUES:
                already_cancelled = True
            elif status in _TERMINAL_COMPLETED_STATUS_VALUES:
                already_completed = True
            else:
                cancellable = True
                task_entry["status"] = TaskStatus.CANCELLED.value
                task_entry["cancelled_at"] = time.time()
    except Exception as exc:
        logger.warning("task_lifecycle: task_queue cancellation skipped: %s", exc)

    try:
        from core.canonical_task import TaskLifecycle, get_canonical_task_runtime

        runtime = get_canonical_task_runtime()
        task = runtime.get_by_task_id(task_id)
        if task is not None:
            known = True
            status = _extract_status_value(getattr(task, "lifecycle", None))
            if status in _CANCELLED_STATUS_VALUES:
                already_cancelled = True
            elif status in _TERMINAL_COMPLETED_STATUS_VALUES:
                already_completed = True
            else:
                cancellable = True
                runtime.update_lifecycle(task_id, TaskLifecycle.CANCELLED)
    except Exception as exc:
        logger.debug("task_lifecycle: CanonicalTaskRuntime cancellation skipped: %s", exc)

    try:
        from core.task_graph_runtime import (
            GraphNodeState,
            WorkflowContributorKind,
            get_task_graph_runtime,
        )

        runtime = get_task_graph_runtime()
        node = runtime.get_node_by_task_id(task_id)
        if node is not None:
            known = True
            status = _extract_status_value(getattr(node, "state", None))
            if status in _CANCELLED_STATUS_VALUES:
                already_cancelled = True
            elif status in _TERMINAL_COMPLETED_STATUS_VALUES:
                already_completed = True
            else:
                cancellable = True
                runtime.transition(
                    task_id,
                    GraphNodeState.CANCELLED,
                    reason="android_task_cancel",
                    contributor=WorkflowContributorKind.UNKNOWN,
                )
    except Exception as exc:
        logger.debug("task_lifecycle: TaskGraphRuntime cancellation skipped: %s", exc)

    if cancellable:
        try:
            from core.openclawd import get_openclawd

            get_openclawd().cancel_task(task_id)
        except Exception as exc:
            logger.debug("task_lifecycle: OpenClawd cancel propagation skipped: %s", exc)
        return True, None

    if already_cancelled:
        return True, "task_already_cancelled"
    if known and already_completed:
        return False, "task_already_completed"
    if known:
        return True, None
    return False, "task_not_found"


def _try_reconcile(message: Dict[str, Any]) -> None:
    """Best-effort reconcile *message* against the host-side execution tracker.

    Calls :func:`~core.android_execution_signal_reconciler.reconcile_inbound_message`
    when the reconciler is available and the message carries at least one of
    ``contract_id`` / ``session_id`` (otherwise a no-op).  Failures are logged
    at DEBUG level and never propagated so existing handler behaviour is
    unchanged when the reconciler is unavailable or the message is not
    associated with a tracked delegated execution.

    A compat-path signal guard is applied first: if the same idempotency_key
    or message_id was already processed in this process session the reconcile
    call is skipped entirely, preventing duplicate processing when v1/v2 compat
    normalisation causes the same lifecycle event to be dispatched more than
    once.
    """
    # Compat lifecycle path signal guard — skip duplicates.
    if not _signal_guard_accept(message):
        return

    if _reconcile_inbound_message is None:
        return
    payload = message.get("payload") or {}
    has_key = (
        bool(message.get("contract_id") or payload.get("contract_id"))
        or bool(
            message.get("session_id")
            or payload.get("session_id")
            or message.get("runtime_session_id")
            or payload.get("runtime_session_id")
        )
    )
    if not has_key:
        return
    try:
        outcome = _reconcile_inbound_message(message)
        if outcome.was_updated:
            logger.debug(
                "PR-13 reconcile: signal=%s contract_id=%r session_id=%r → phase=%s",
                outcome.envelope.signal_kind.value if outcome.envelope else "?",
                outcome.envelope.contract_id if outcome.envelope else "",
                outcome.envelope.session_id if outcome.envelope else "",
                outcome.record.phase.value if outcome.record else "?",
            )
        elif outcome.reject_reason:
            logger.debug(
                "PR-13 reconcile skipped: %s",
                outcome.reject_reason,
            )
    except Exception as exc:
        global RESULT_RECONCILE_ERRORS  # noqa: PLW0603
        RESULT_RECONCILE_ERRORS += 1
        logger.warning(
            "PR-13 reconcile failed (non-fatal, errors=%d): type=%s task_id=%r exc=%s",
            RESULT_RECONCILE_ERRORS,
            message.get("type", "?"),
            message.get("task_id"),
            exc,
        )

def _try_ingest_participant_truth(message: Dict[str, Any], truth_kind: str) -> None:
    """Best-effort ingest *message* as Android participant truth into V2 canonical state.

    Calls :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
    when the ingress module is available.  The *message* dict is enriched with
    the caller-supplied *truth_kind* value (which maps to
    :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`)
    before passing to the ingress function.

    Failures are logged at WARNING level and the observable error counter is
    incremented so that monitoring can detect truth-ingress regressions without
    log-scraping.
    """
    if _ingest_participant_truth is None:
        return
    try:
        enriched = dict(message)
        # Inject truth_kind so the ingress envelope extractor classifies it
        # correctly even if the raw Android message does not carry the field.
        enriched.setdefault("truth_kind", truth_kind)
        outcome = _ingest_participant_truth(enriched)
        if outcome.was_reconciled:
            logger.debug(
                "PR-4V2 participant truth ingested: truth_kind=%s contract_id=%r "
                "session_id=%r was_reconciled=True canonical_update=%r phase=%r",
                truth_kind,
                outcome.envelope.contract_id if outcome.envelope else "",
                outcome.envelope.session_id if outcome.envelope else "",
                outcome.canonical_update,
                outcome.tracking_record_phase,
            )
        elif outcome.reject_reason:
            logger.debug(
                "PR-4V2 participant truth skipped: truth_kind=%s reason=%r",
                truth_kind,
                outcome.reject_reason,
            )
    except Exception as exc:
        global RESULT_TRUTH_INGRESS_ERRORS  # noqa: PLW0603
        RESULT_TRUTH_INGRESS_ERRORS += 1
        logger.warning(
            "PR-4V2 participant truth ingest failed (non-fatal, errors=%d): "
            "truth_kind=%s task_id=%r exc=%s",
            RESULT_TRUTH_INGRESS_ERRORS,
            truth_kind,
            message.get("task_id"),
            exc,
        )


def _check_result_ingress_continuity_legality(
    message: Dict[str, Any],
) -> tuple:
    """Run the V1 canonical continuity legality pre-check for participant result ingress.

    Evaluates the inbound result message against the unified continuity
    legality authority (``TERMINAL_RESULT_INGESTION`` path) BEFORE any
    truth-chain step is allowed to run.

    Returns
    -------
    (verdict_str, is_rejected) :
        *verdict_str* is one of ``"allow"``, ``"reject"``,
        ``"require_review"``.
        *is_rejected* is ``True`` when the result must be blocked (i.e. the
        calling path MUST NOT enter the truth chain).

    Graceful degradation
    --------------------
    When the authority module is unavailable the function returns
    ``("allow", False)`` so existing deployments are never broken by a
    missing authority.  Exceptions inside the authority call are also caught
    and treated as ``"allow"`` with a DEBUG-level log entry.
    """
    if _evaluate_continuity_legality is None:
        # Authority module not installed — fail-open for backward compat.
        return "allow", False
    try:
        payload = message.get("payload") or {}
        ctx = _ContinuityLegalityContext(
            device_id=str(message.get("device_id") or ""),
            runtime_session_id=str(
                message.get("runtime_session_id")
                or payload.get("runtime_session_id")
                or ""
            ),
            runtime_attachment_session_id=str(
                message.get("runtime_attachment_session_id")
                or payload.get("runtime_attachment_session_id")
                or ""
            ),
            durable_session_id=str(
                message.get("durable_session_id")
                or payload.get("durable_session_id")
                or ""
            ),
            contract_id=str(
                message.get("contract_id")
                or payload.get("contract_id")
                or ""
            ),
            flow_id=str(
                message.get("flow_id")
                or payload.get("flow_id")
                or ""
            ),
        )
        report = _evaluate_continuity_legality(
            _ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
            ctx,
        )
        return report.verdict.value, report.is_rejected
    except Exception as _ce:
        logger.debug(
            "task_lifecycle: V1 continuity legality gate error "
            "(non-fatal, allowing): %s",
            _ce,
        )
        return "allow", False


async def handle_task_result(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理任务结果，完成 Future 并触发 OpenClawd 记忆回流

    Durable idempotency guard
    -------------------------
    Before processing, the task_id is checked against the cross-restart durable
    result-ID store.  If the result was already processed in a previous V2
    process lifetime (e.g. Android reconnects after a V2 restart and replays
    the same task_result), the message is suppressed here so that the Future
    is not double-resolved and memory backflow is not duplicated.
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    result_status = message.get("status", "unknown")
    route_mode = message.get("route_mode", "cross_device")

    logger.info(
        "Task result received: task_id=%s device_id=%s status=%s",
        task_id, device_id, result_status,
    )

    # PR-V1-RESULT: Canonical V1 continuity legality pre-check.
    # Evaluate the inbound result against the unified continuity legality
    # authority BEFORE any truth-chain step (truth ingress, reconciliation,
    # lifecycle update, completion ingress) is allowed to run.  This closes
    # the result-ingress continuity gap so that stale, revoked, detached, or
    # otherwise continuity-invalid runtime/session identities cannot pollute
    # canonical truth.  Per RESULT_INGRESS_CONTINUITY_LEGALITY_POLICY.
    _continuity_verdict, _continuity_rejected = (
        _check_result_ingress_continuity_legality(message)
    )
    if _continuity_rejected:
        logger.warning(
            "handle_task_result: V1 continuity legality REJECTED result "
            "ingress (verdict=%s) for task_id=%r device_id=%r — blocking "
            "before truth chain",
            _continuity_verdict,
            task_id,
            device_id,
        )
        return
    logger.debug(
        "handle_task_result: V1 continuity legality verdict=%s task_id=%r",
        _continuity_verdict,
        task_id,
    )

    # ── Durable idempotency: suppress cross-restart duplicate results ──
    if task_id:
        try:
            from core.durable_result_idempotency import (
                check_result_idempotency,
                record_result_idempotency,
            )
            if check_result_idempotency(task_id):
                logger.info(
                    "task_lifecycle: duplicate task result suppressed (durable store): "
                    "task_id=%s device_id=%s",
                    task_id,
                    device_id,
                )
                return
            record_result_idempotency(task_id)
        except Exception as _idem_exc:  # noqa: BLE001 — durable store must never block dispatch
            logger.debug(
                "task_lifecycle: durable idempotency check skipped (non-fatal): %s",
                _idem_exc,
            )

    # PR-TTC: Run the canonical must-run truth chain.  This replaces the
    # previous separate _try_reconcile + _try_ingest_participant_truth calls
    # with a single entry point that:
    #   (1) truth_ingress   — ingest Android participant truth into V2 state
    #   (2) reconcile       — reconcile against host-side execution tracker
    #   (3) authority_update — advance CanonicalTaskRuntime lifecycle
    #   (4) completion_linkage — notify CanonicalCompletionIngress
    # The TruthChainOutcome records whether the chain was fully closed so
    # acceptance / audit layers can distinguish "result arrived" from
    # "truth chain complete".
    if _run_task_result_truth_chain is not None:
        _truth_chain_outcome = _run_task_result_truth_chain(
            message,
            task_id=task_id,
            result_status=result_status,
        )
        if not _truth_chain_outcome.is_truth_chain_complete:
            logger.warning(
                "handle_task_result: truth chain incomplete for task_id=%r: %s",
                task_id,
                _truth_chain_outcome.incomplete_reason,
            )
        else:
            logger.debug(
                "handle_task_result: truth chain complete for task_id=%r",
                task_id,
            )
    else:
        # Fallback: canonical truth chain module unavailable — run legacy
        # best-effort helpers so existing behaviour is preserved.
        logger.warning(
            "handle_task_result: canonical truth chain module unavailable "
            "(task_result_canonical_truth_chain); falling back to legacy "
            "best-effort helpers for task_id=%r",
            task_id,
        )
        _try_reconcile(message)
        _try_ingest_participant_truth(message, "result")

    # 完成等待的 Future
    if task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.set_result(message)

    # 更新设备状态
    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = None

    # PR-1 P0 Completion Closure: notify DeviceRouter so that any
    # dispatch_to_websocket awaiter blocked on task_events[task_id].wait()
    # is woken immediately by a real completion event rather than a timeout.
    if task_id:
        try:
            from galaxy_gateway.device_router import device_router as _device_router

            _dr_result = {
                **message,
                "success": result_status not in ("failed", "error", "cancelled"),
                "via": "task_lifecycle.handle_task_result",
            }
            await _device_router.handle_task_result(task_id, _dr_result)
            logger.debug(
                "PR-1 P0: task_result → device_router.handle_task_result task_id=%r",
                task_id,
            )
        except Exception as _dr_exc:
            global RESULT_DEVICE_ROUTER_ERRORS  # noqa: PLW0603
            RESULT_DEVICE_ROUTER_ERRORS += 1
            logger.warning(
                "PR-1 P0: device_router.handle_task_result failed (non-fatal, errors=%d): "
                "task_id=%r exc=%s",
                RESULT_DEVICE_ROUTER_ERRORS,
                task_id,
                _dr_exc,
            )

    # OpenClawd 记忆回流
    if task_id and device_id and store_task_result is not None:
        try:
            await store_task_result(
                task_id=task_id,
                device_id=device_id,
                route_mode=route_mode,
                result=message,
            )
            logger.debug(
                "Memory backflow stored: task_id=%s device_id=%s route_mode=%s",
                task_id, device_id, route_mode,
            )
        except Exception as bf_err:
            global RESULT_MEMORY_BACKFLOW_ERRORS  # noqa: PLW0603
            RESULT_MEMORY_BACKFLOW_ERRORS += 1
            logger.warning(
                "Memory backflow failed (non-fatal, errors=%d): task_id=%s error=%s",
                RESULT_MEMORY_BACKFLOW_ERRORS,
                task_id,
                bf_err,
            )


async def handle_task_end(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务结束通知"""
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    final_status = message.get("status", TaskStatus.COMPLETED.value)

    logger.info(
        "Task lifecycle ended: task_id=%s device_id=%s final_status=%s",
        task_id, device_id, final_status,
    )

    # PR-13: reconcile inbound signal against host-side execution tracker
    _try_reconcile(message)
    # PR-4V2: ingest Android task_phase truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "task_phase")

    # 清理残余 pending future
    if task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.set_result(message)

    async with bridge._lock:
        if device_id and device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = None

    # PR-1 P0 Completion Closure: notify DeviceRouter so that any
    # dispatch_to_websocket awaiter blocked on task_events[task_id].wait()
    # is woken immediately by a real completion event rather than a timeout.
    if task_id:
        try:
            from galaxy_gateway.device_router import device_router as _device_router

            _dr_result = {
                **message,
                "success": final_status not in ("failed", "error", "cancelled"),
                "via": "task_lifecycle.handle_task_end",
            }
            await _device_router.handle_task_result(task_id, _dr_result)
            logger.debug(
                "PR-1 P0: task_end → device_router.handle_task_result task_id=%r",
                task_id,
            )
        except Exception as _dr_exc:
            logger.debug(
                "PR-1 P0: device_router.handle_task_result (task_end) skipped "
                "(non-fatal): task_id=%r exc=%s",
                task_id,
                _dr_exc,
            )

    return {
        "version": "3.0",
        "type": "task_end_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "task_id": task_id,
        "timestamp": int(time.time() * 1000),
        "status": "acknowledged",
    }


async def handle_task_progress(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理任务进度"""
    task_id = message.get("task_id")
    progress = message.get("progress", 0)
    logger.debug("Task progress: %s - %s%%", task_id, progress)

    # PR-13: reconcile inbound signal against host-side execution tracker
    _try_reconcile(message)
    # PR-4V2: ingest Android progress as status truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "status")


async def handle_command_result(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理命令结果"""
    message_id = message.get("message_id")

    if message_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(message_id)
        if not future.done():
            future.set_result(message)

    # PR-13: reconcile inbound command_result signal against the host-side
    # execution tracker.  command_result is an ACK/result-style Android
    # execution signal; messages that carry contract_id or session_id identity
    # fields must advance the canonical tracking record.  _try_reconcile's
    # internal has_key guard is a no-op for messages without those fields, so
    # this call is safe for all command_result messages regardless of whether
    # they relate to a tracked delegated execution.
    _try_reconcile(message)


async def handle_error(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理错误消息，使用结构化日志输出"""
    device_id = message.get("device_id")
    error_code = message.get("error_code")
    error_message = message.get("error_message")
    details = message.get("details")
    task_id = message.get("task_id")

    logger.error(
        "Error from device: device_id=%s error_code=%s error_message=%s task_id=%s details=%s",
        device_id, error_code, error_message, task_id, details,
    )

    # PR-13: reconcile inbound error signal against host-side execution tracker
    _try_reconcile(message)
    # PR-4V2: ingest Android failure truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "failure")


async def handle_task_cancel(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务取消请求，传播到 canonical runtime 并返回 task_cancel_ack。

    链路：Android → task_cancel → canonical task cancellation propagation
    (TaskGraphRuntime / CanonicalTaskRuntime / OpenClawd cancel registry / task_queue)
    → 清理 bridge 本地 Future → 返回 task_cancel_ack
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    correlation_id = message.get("message_id")

    logger.info(
        "Task cancel requested: task_id=%s device_id=%s",
        task_id, device_id,
    )

    try:
        cancelled, reason = _apply_canonical_task_cancellation(task_id)
    except Exception as exc:
        logger.warning(
            "Task cancel: canonical cancellation propagation failed: task_id=%s device_id=%s exc=%s",
            task_id,
            device_id,
            exc,
        )
        cancelled, reason = False, "task_cancel_propagation_failed"

    if task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.cancel()
            cancelled = True
            logger.info(
                "Task cancelled successfully: task_id=%s device_id=%s",
                task_id, device_id,
            )
        elif not cancelled:
            reason = "task_already_completed"
            logger.info(
                "Task cancel: future already done: task_id=%s device_id=%s",
                task_id, device_id,
            )
    elif not cancelled and reason == "task_not_found":
        logger.info(
            "Task cancel: task not found in canonical runtime or pending_responses: "
            "task_id=%s device_id=%s",
            task_id, device_id,
        )

    # 清理设备端 current_task_id
    async with bridge._lock:
        if device_id and device_id in bridge._devices:
            if bridge._devices[device_id].current_task_id == task_id:
                bridge._devices[device_id].current_task_id = None

    # PR-4V2: ingest Android cancel truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "cancel")

    return MessageBuilder.task_cancel_ack(
        device_id=device_id or "",
        task_id=task_id,
        cancelled=cancelled,
        reason=reason,
        correlation_id=correlation_id,
    )


async def handle_task_status(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务状态查询，优先返回 canonical runtime truth。

    链路：Android → task_status → TaskGraphRuntime / CanonicalTaskRuntime / task_queue
    → bridge 本地兜底 → 返回 task_status_response
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    correlation_id = message.get("message_id")

    logger.info(
        "Task status query: task_id=%s device_id=%s",
        task_id, device_id,
    )

    status = _read_canonical_runtime_status(task_id)

    # Canonical runtime unavailable时，回退到 bridge 本地状态。
    if status is None and task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses[task_id]
        if future.cancelled():
            status = TaskStatus.CANCELLED.value
        elif future.done():
            status = TaskStatus.COMPLETED.value
        else:
            status = TaskStatus.RUNNING.value
    elif status is None:
        # 检查设备当前任务
        async with bridge._lock:
            device = bridge._devices.get(device_id or "")
        if device and device.current_task_id == task_id and task_id:
            status = TaskStatus.RUNNING.value
        else:
            status = TaskStatus.COMPLETED.value

    logger.info(
        "Task status resolved: task_id=%s device_id=%s status=%s",
        task_id, device_id, status,
    )

    # PR-4V2: ingest Android status truth into V2 canonical orchestration.
    # Enrich the message with the resolved status so the ingress extractor
    # can read it as task_phase_value via payload.status.
    _status_enriched = dict(message)
    _status_enriched["payload"] = {**(message.get("payload") or {}), "status": status}
    _try_ingest_participant_truth(_status_enriched, "status")

    return MessageBuilder.task_status_response(
        device_id=device_id or "",
        task_id=task_id,
        status=status,
        correlation_id=correlation_id,
    )
