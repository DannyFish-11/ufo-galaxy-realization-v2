"""core/task_result_canonical_truth_chain.py
=============================================
PR-TTC: task_result Canonical Truth Chain — makes the four critical
truth-convergence steps a default strong main path instead of optional/
fallback wiring.

Background
----------
Previous PR packages (PR-13, PR-4V2, PR-1) wired individual truth-ingress,
reconcile, and completion-linkage steps into ``handle_task_result`` as
separate *best-effort* helpers.  Each helper silently no-ops when its backing
module is unavailable.  This means:

* A ``task_result`` can arrive and be considered "done" even if zero of the
  four critical truth-convergence steps ran.
* Acceptance / audit layers have no machine-checkable signal distinguishing
  "result arrived AND truth chain complete" from "result arrived but truth
  chain incomplete".

This module closes that gap by:

1. Defining :class:`TruthChainOutcome` — a dataclass that records whether
   each of the four canonical must-run steps ran and what each step returned.
   ``is_truth_chain_complete`` is ``True`` only when **all four** critical
   steps succeeded.

2. Providing :func:`run_task_result_truth_chain` — the single entry point
   that executes the four critical steps in order and returns a
   :class:`TruthChainOutcome`.  Optional enrichment steps (memory backflow,
   device-router notification) are **not** included here; they belong to the
   caller's extension layer and their absence must not influence
   ``is_truth_chain_complete``.

Critical (must-run) steps
-------------------------
The four steps that constitute a closed truth loop for a ``task_result``:

1. **truth_ingress** — Ingest the Android participant truth into V2 canonical
   orchestration state via
   :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`.
2. **reconcile** — Reconcile the inbound signal against the host-side
   execution tracker via
   :func:`~core.android_execution_signal_reconciler.reconcile_inbound_message`.
3. **authority_state_update** — Advance the :class:`~core.canonical_task.CanonicalTask`
   lifecycle to the terminal state matching the result status via
   :func:`~core.canonical_task.CanonicalTaskRuntime.update_lifecycle`.
4. **canonical_completion_linkage** — Notify the
   :class:`~core.canonical_completion_ingress.CanonicalCompletionIngress`
   singleton so any registered awaiter is unblocked.

Optional enrichment steps (NOT part of this module)
----------------------------------------------------
* OpenClawd memory backflow (``store_task_result``)
* DeviceRouter task-event notification
* NATS / event-bus publication

These remain in the handler and must not affect ``is_truth_chain_complete``.

Authority contract
------------------
``TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY`` is an importable string sentinel
that asserts this module's role as the canonical must-run truth chain for
``task_result`` processing.  Other modules may import this sentinel to assert
compliance.

Public API
----------
::

    TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY   (sentinel)
    TruthChainOutcome                          (dataclass)
    run_task_result_truth_chain(message, ...)  (function)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY: str = (
    "POLICY::TASK_RESULT_TRUTH_CHAIN_MUST_RUN: "
    "When a task_result arrives the following four steps MUST run and their "
    "outcome MUST be captured: (1) truth_ingress via "
    "android_participant_truth_ingress, (2) reconcile via "
    "android_execution_signal_reconciler, (3) authority_state_update via "
    "CanonicalTaskRuntime.update_lifecycle, (4) canonical_completion_linkage "
    "via CanonicalCompletionIngress.notify.  A result that arrives without "
    "completing this chain MUST be recorded as truth_chain_incomplete, NOT as "
    "a successfully closed task."
)

TRUTH_CHAIN_OPTIONAL_ENRICHMENT_POLICY: str = (
    "POLICY::TRUTH_CHAIN_OPTIONAL_ENRICHMENT: "
    "Optional enrichment steps (OpenClawd memory backflow, DeviceRouter "
    "notification, NATS publication) are NOT part of the canonical truth "
    "chain.  Their absence MUST NOT cause is_truth_chain_complete to be True "
    "or False.  They are extension-layer concerns and must be handled by the "
    "caller outside run_task_result_truth_chain."
)


# ---------------------------------------------------------------------------
# Step outcome types
# ---------------------------------------------------------------------------

class StepStatus(str):
    """Step run-status string constants."""
    COMPLETED = "completed"
    """Step ran and produced a positive outcome."""
    SKIPPED_MODULE_UNAVAILABLE = "skipped_module_unavailable"
    """Step could not run because its backing module is not importable."""
    SKIPPED_NO_TASK_ID = "skipped_no_task_id"
    """Step skipped because the message carries no task_id."""
    SKIPPED_NO_KEY = "skipped_no_key"
    """Step skipped because the message carries no usable correlation key."""
    FAILED_EXCEPTION = "failed_exception"
    """Step raised an unexpected exception."""
    NOT_RECONCILED = "not_reconciled"
    """Step ran but the backing runtime reported no matching record."""
    COMPLETED_NO_MATCH = "completed_no_match"
    """Step ran, no matching record found, but that is non-fatal for this step."""


# ---------------------------------------------------------------------------
# TruthChainOutcome
# ---------------------------------------------------------------------------

@dataclass
class TruthChainOutcome:
    """Records the outcome of the four canonical must-run truth-chain steps.

    Attributes
    ----------
    task_id:
        The task identifier this outcome applies to.
    result_status:
        The status string from the inbound ``task_result`` message.

    truth_ingress_status:
        :class:`StepStatus` constant for step 1 (truth ingress).
    reconcile_status:
        :class:`StepStatus` constant for step 2 (reconcile).
    authority_update_status:
        :class:`StepStatus` constant for step 3 (authority state update).
    completion_linkage_status:
        :class:`StepStatus` constant for step 4 (canonical completion linkage).

    truth_ingress_was_reconciled:
        ``True`` if step 1 reported ``was_reconciled=True``.
    reconcile_was_updated:
        ``True`` if step 2 reported ``was_updated=True``.
    authority_task_found:
        ``True`` if step 3 found a matching :class:`~core.canonical_task.CanonicalTask`
        and advanced its lifecycle.
    completion_linkage_resolved:
        ``True`` if step 4 resolved a registered awaiting Future.

    is_truth_chain_complete:
        ``True`` only when ALL four steps ran without a fatal failure.
        A step that found no matching record (``NOT_RECONCILED`` /
        ``COMPLETED_NO_MATCH``) is still considered "ran" — the record may
        not exist for all task_result messages (e.g. tasks not tracked by
        the delegated-execution tracker).

    incomplete_reason:
        Human-readable explanation when ``is_truth_chain_complete`` is
        ``False``.
    """

    task_id: str = ""
    result_status: str = ""

    # Per-step status
    truth_ingress_status: str = StepStatus.SKIPPED_MODULE_UNAVAILABLE
    reconcile_status: str = StepStatus.SKIPPED_MODULE_UNAVAILABLE
    authority_update_status: str = StepStatus.SKIPPED_MODULE_UNAVAILABLE
    completion_linkage_status: str = StepStatus.SKIPPED_MODULE_UNAVAILABLE

    # Per-step boolean outcomes
    truth_ingress_was_reconciled: bool = False
    reconcile_was_updated: bool = False
    authority_task_found: bool = False
    completion_linkage_resolved: bool = False

    # Top-level completeness verdict
    is_truth_chain_complete: bool = False
    incomplete_reason: str = ""

    # Optional: raw step exceptions (for diagnostics, not re-raised)
    _truth_ingress_exc: Optional[BaseException] = field(default=None, repr=False)
    _reconcile_exc: Optional[BaseException] = field(default=None, repr=False)
    _authority_update_exc: Optional[BaseException] = field(default=None, repr=False)
    _completion_linkage_exc: Optional[BaseException] = field(default=None, repr=False)

    def _fatal_status(self, status: str) -> bool:
        """Return True for statuses that block truth chain completion."""
        return status in (
            StepStatus.SKIPPED_MODULE_UNAVAILABLE,
            StepStatus.FAILED_EXCEPTION,
        )

    def _compute_completeness(self) -> None:
        """Populate ``is_truth_chain_complete`` and ``incomplete_reason``."""
        failures = []
        if self._fatal_status(self.truth_ingress_status):
            failures.append(f"truth_ingress={self.truth_ingress_status}")
        if self._fatal_status(self.reconcile_status):
            failures.append(f"reconcile={self.reconcile_status}")
        if self._fatal_status(self.authority_update_status):
            failures.append(f"authority_update={self.authority_update_status}")
        if self._fatal_status(self.completion_linkage_status):
            failures.append(f"completion_linkage={self.completion_linkage_status}")
        if failures:
            self.is_truth_chain_complete = False
            self.incomplete_reason = "; ".join(failures)
        else:
            self.is_truth_chain_complete = True
            self.incomplete_reason = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable summary dict (no private fields)."""
        return {
            "task_id": self.task_id,
            "result_status": self.result_status,
            "truth_ingress_status": self.truth_ingress_status,
            "reconcile_status": self.reconcile_status,
            "authority_update_status": self.authority_update_status,
            "completion_linkage_status": self.completion_linkage_status,
            "truth_ingress_was_reconciled": self.truth_ingress_was_reconciled,
            "reconcile_was_updated": self.reconcile_was_updated,
            "authority_task_found": self.authority_task_found,
            "completion_linkage_resolved": self.completion_linkage_resolved,
            "is_truth_chain_complete": self.is_truth_chain_complete,
            "incomplete_reason": self.incomplete_reason,
        }


# ---------------------------------------------------------------------------
# Module-level imports (top-level so tests can patch them)
# ---------------------------------------------------------------------------

try:
    from core.android_participant_truth_ingress import (
        ingest_android_participant_truth_message as _ingest_participant_truth,
    )
except ImportError:
    _ingest_participant_truth = None  # type: ignore[assignment]

try:
    from core.android_execution_signal_reconciler import (
        reconcile_inbound_message as _reconcile_inbound_message,
    )
except ImportError:
    _reconcile_inbound_message = None  # type: ignore[assignment]

try:
    from core.canonical_task import (
        TaskLifecycle,
        get_canonical_task_runtime as _get_canonical_task_runtime,
    )
except ImportError:
    TaskLifecycle = None  # type: ignore[assignment]
    _get_canonical_task_runtime = None  # type: ignore[assignment]

try:
    from core.canonical_completion_ingress import (
        get_canonical_completion_ingress as _get_canonical_completion_ingress,
    )
except ImportError:
    _get_canonical_completion_ingress = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _run_truth_ingress(
    message: Dict[str, Any],
    outcome: TruthChainOutcome,
) -> None:
    """Step 1: ingest Android participant truth into V2 canonical state."""
    if _ingest_participant_truth is None:
        outcome.truth_ingress_status = StepStatus.SKIPPED_MODULE_UNAVAILABLE
        return
    try:
        enriched = dict(message)
        enriched.setdefault("truth_kind", "result")
        result = _ingest_participant_truth(enriched)
        outcome.truth_ingress_was_reconciled = bool(
            getattr(result, "was_reconciled", False)
        )
        outcome.truth_ingress_status = StepStatus.COMPLETED
    except Exception as exc:
        outcome.truth_ingress_status = StepStatus.FAILED_EXCEPTION
        outcome._truth_ingress_exc = exc
        logger.warning(
            "truth_chain step 1 (truth_ingress) failed: task_id=%r exc=%s",
            outcome.task_id,
            exc,
        )


def _run_reconcile(
    message: Dict[str, Any],
    outcome: TruthChainOutcome,
) -> None:
    """Step 2: reconcile inbound signal against host-side execution tracker."""
    if _reconcile_inbound_message is None:
        outcome.reconcile_status = StepStatus.SKIPPED_MODULE_UNAVAILABLE
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
        # No correlation key — record as completed-no-match (not a fatal gap)
        outcome.reconcile_status = StepStatus.COMPLETED_NO_MATCH
        return
    try:
        rec_outcome = _reconcile_inbound_message(message)
        outcome.reconcile_was_updated = bool(
            getattr(rec_outcome, "was_updated", False)
        )
        outcome.reconcile_status = StepStatus.COMPLETED
    except Exception as exc:
        outcome.reconcile_status = StepStatus.FAILED_EXCEPTION
        outcome._reconcile_exc = exc
        logger.warning(
            "truth_chain step 2 (reconcile) failed: task_id=%r exc=%s",
            outcome.task_id,
            exc,
        )


def _run_authority_state_update(
    task_id: str,
    result_status: str,
    outcome: TruthChainOutcome,
) -> None:
    """Step 3: advance CanonicalTaskRuntime lifecycle to terminal state."""
    if _get_canonical_task_runtime is None or TaskLifecycle is None:
        outcome.authority_update_status = StepStatus.SKIPPED_MODULE_UNAVAILABLE
        return
    if not task_id:
        outcome.authority_update_status = StepStatus.SKIPPED_NO_TASK_ID
        return
    try:
        runtime = _get_canonical_task_runtime()
        # Map result_status to canonical terminal lifecycle state
        _status_lower = (result_status or "").lower()
        if _status_lower in ("failed", "error"):
            target_lifecycle = TaskLifecycle.FAILED
        elif _status_lower == "cancelled":
            target_lifecycle = TaskLifecycle.CANCELLED
        elif _status_lower == "degraded":
            target_lifecycle = TaskLifecycle.DEGRADED
        else:
            target_lifecycle = TaskLifecycle.COMPLETED
        updated = runtime.update_lifecycle(task_id, target_lifecycle)
        if updated is not None:
            outcome.authority_task_found = True
        # Even if no matching task was found (update returns None), the step
        # ran successfully — not every task_result maps to a tracked task.
        outcome.authority_update_status = StepStatus.COMPLETED
    except Exception as exc:
        outcome.authority_update_status = StepStatus.FAILED_EXCEPTION
        outcome._authority_update_exc = exc
        logger.warning(
            "truth_chain step 3 (authority_state_update) failed: task_id=%r exc=%s",
            task_id,
            exc,
        )


def _run_completion_linkage(
    task_id: str,
    message: Dict[str, Any],
    outcome: TruthChainOutcome,
) -> None:
    """Step 4: notify CanonicalCompletionIngress so registered awaiters unblock."""
    if _get_canonical_completion_ingress is None:
        outcome.completion_linkage_status = StepStatus.SKIPPED_MODULE_UNAVAILABLE
        return
    if not task_id:
        outcome.completion_linkage_status = StepStatus.SKIPPED_NO_TASK_ID
        return
    try:
        ingress = _get_canonical_completion_ingress()
        # Build a minimal duck-typed envelope the notify() method can consume.
        # CanonicalCompletionIngress.notify() inspects .is_terminal,
        # .handoff_id, and .task_id on the envelope object.
        class _MinimalEnvelope:
            is_terminal = True
            handoff_id = message.get("handoff_id") or ""
            task_id: str = ""

        envelope = _MinimalEnvelope()
        envelope.task_id = task_id
        # Also try complete_pending_dispatch by task_id directly for robustness.
        resolved_notify = ingress.notify(envelope)
        resolved_direct = ingress.complete_pending_dispatch(task_id, envelope)
        outcome.completion_linkage_resolved = bool(resolved_notify or resolved_direct)
        outcome.completion_linkage_status = StepStatus.COMPLETED
    except Exception as exc:
        outcome.completion_linkage_status = StepStatus.FAILED_EXCEPTION
        outcome._completion_linkage_exc = exc
        logger.warning(
            "truth_chain step 4 (completion_linkage) failed: task_id=%r exc=%s",
            task_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_task_result_truth_chain(
    message: Dict[str, Any],
    *,
    task_id: Optional[str] = None,
    result_status: Optional[str] = None,
) -> TruthChainOutcome:
    """Run the four canonical must-run truth-chain steps for a ``task_result``.

    This is the default strong main path.  All four steps are attempted in
    order.  Each step records its own status in the returned
    :class:`TruthChainOutcome`; no step silently suppresses its own failure
    without recording it.

    Parameters
    ----------
    message:
        The raw inbound ``task_result`` message dict (as received from the
        Android gateway handler).
    task_id:
        The task identifier.  If omitted the function reads it from
        ``message["task_id"]``.
    result_status:
        The terminal status string (e.g. ``"completed"``, ``"failed"``).
        If omitted the function reads it from ``message["status"]``.

    Returns
    -------
    TruthChainOutcome
        Structured outcome recording each step's status.
        ``outcome.is_truth_chain_complete`` is ``True`` only when ALL four
        steps ran without a fatal failure (module-unavailable or exception).

    Notes
    -----
    * This function is **synchronous**.  Async enrichment steps (memory
      backflow, device-router notification) are outside this function's scope.
    * A step that finds no matching record (e.g. reconcile finds no tracked
      execution contract) is NOT a fatal gap — it records ``COMPLETED_NO_MATCH``
      and does not set ``is_truth_chain_complete = False``.
    * If the backing module for any critical step is unavailable at import time,
      that step records ``SKIPPED_MODULE_UNAVAILABLE`` and the overall
      ``is_truth_chain_complete`` is ``False``.
    """
    _task_id: str = task_id or (message.get("task_id") or "")
    _result_status: str = result_status or (message.get("status") or "unknown")

    outcome = TruthChainOutcome(
        task_id=_task_id,
        result_status=_result_status,
    )

    # Step 1: truth ingress
    _run_truth_ingress(message, outcome)

    # Step 2: reconcile
    _run_reconcile(message, outcome)

    # Step 3: authority state update
    _run_authority_state_update(_task_id, _result_status, outcome)

    # Step 4: canonical completion linkage
    _run_completion_linkage(_task_id, message, outcome)

    # Compute top-level completeness verdict
    outcome._compute_completeness()

    if outcome.is_truth_chain_complete:
        logger.info(
            "task_result truth chain complete: task_id=%r status=%r "
            "truth_ingress=%s reconcile=%s authority_update=%s completion_linkage=%s",
            _task_id,
            _result_status,
            outcome.truth_ingress_status,
            outcome.reconcile_status,
            outcome.authority_update_status,
            outcome.completion_linkage_status,
        )
    else:
        logger.warning(
            "task_result truth chain INCOMPLETE: task_id=%r status=%r "
            "reason=%r "
            "truth_ingress=%s reconcile=%s authority_update=%s completion_linkage=%s",
            _task_id,
            _result_status,
            outcome.incomplete_reason,
            outcome.truth_ingress_status,
            outcome.reconcile_status,
            outcome.authority_update_status,
            outcome.completion_linkage_status,
        )

    return outcome


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY",
    "TRUTH_CHAIN_OPTIONAL_ENRICHMENT_POLICY",
    # Status constants
    "StepStatus",
    # Dataclass
    "TruthChainOutcome",
    # Entry point
    "run_task_result_truth_chain",
]
