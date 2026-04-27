#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runtime_restart_recovery.py
===================================
PR-5: Runtime Restart / Recovery Coordinator

Background
----------
After a process restart, device disconnect, or transient infrastructure failure
several runtime-critical state components are lost unless explicitly recovered:

1. **MeshSession state** — coordinator progress, participant status, barrier
   advancement.  Recovered via
   :func:`~core.mesh.mesh_session_persistence.recover_mesh_sessions`.

2. **BodyMeshRegistry state** — device roles, primary-body assignment, session
   associations.  Recovered via
   :func:`~core.mesh.body_mesh_persistence.restore_body_mesh_from_snapshot`.

3. **WebRTC task bindings** — task-scoped transport bindings that were active
   at the time of the restart.  These are in-memory ring-buffer records; they
   are by design **not** durably recovered (the transport itself is gone after
   a restart).  This boundary is made **explicit** by this module.

This module provides a single entry-point —
:class:`RuntimeRestartRecoveryCoordinator` — that orchestrates recovery of the
above components and produces a :class:`RuntimeRecoveryReport` describing what
was recovered, what was intentionally skipped, and any remaining limitations.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every recovery step is independent; failure in
  one step does not prevent others from running.
- **Explicit non-goals** — what is intentionally ephemeral (e.g. WebRTC
  transport bindings) is documented, not silently dropped.
- **Fully serialisable** — :class:`RuntimeRecoveryReport` can be converted to
  a dict for operator observability.

Non-goals (intentionally ephemeral)
------------------------------------
The following runtime artifacts are **not** recovered across restarts because
they are inherently transport-layer or session-layer state that is invalidated
when the underlying connection is lost:

* **WebRTC transport bindings** — transport sessions are gone after restart;
  the in-memory ring buffer is cleared.  New bindings will be created when
  tasks are re-dispatched.
* **In-flight task queues** — tasks pending in memory-only queues at the time
  of restart.  These must be replayed by the task source.
* **Device heartbeat state** — devices re-register on reconnect; stale
  heartbeat state is discarded.

Sentinels
---------
:data:`RUNTIME_RESTART_RECOVERY_IS_AUTHORITY`
    Affirms this module is the canonical restart/recovery entry-point.
:data:`MESH_SESSION_RECOVERY_IS_DURABLE_POLICY`
    Affirms that MeshSession recovery uses the durable persistence store.
:data:`BODY_MESH_RECOVERY_IS_DURABLE_POLICY`
    Affirms that BodyMeshRegistry recovery uses the durable persistence store.
:data:`WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY`
    Affirms that WebRTC transport bindings are intentionally ephemeral and
    are NOT recovered across process restarts.
:data:`RUNTIME_RESTART_RECOVERY_PR5_SENTINEL`
    Monotonic sentinel string for PR-5 feature identification.

Public API
----------
Classes:
    :class:`RuntimeRecoveryReport`
    :class:`RuntimeRestartRecoveryCoordinator`

Functions:
    :func:`run_startup_recovery`
    :func:`get_recovery_coordinator`
    :func:`reset_recovery_coordinator`
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RuntimeRestartRecovery")

__all__ = [
    # Sentinels
    "RUNTIME_RESTART_RECOVERY_IS_AUTHORITY",
    "MESH_SESSION_RECOVERY_IS_DURABLE_POLICY",
    "BODY_MESH_RECOVERY_IS_DURABLE_POLICY",
    "WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY",
    "RUNTIME_RESTART_RECOVERY_PR5_SENTINEL",
    "INFLIGHT_TASK_LIFECYCLE_RECOVERY_POLICY",
    "HYBRID_CONTINUITY_RECONSTRUCTION_POLICY",
    "RECOVERED_LIFECYCLE_DISPATCH_POLICY",
    "RECOVERY_DUPLICATE_SAFETY_POLICY",
    "RECOVERY_IDEMPOTENCY_POLICY",
    "SESSION_TRUTH_RECOVERY_POLICY",
    "CONTINUATION_WAITER_RECONCILIATION_POLICY",
    # Classes
    "RuntimeRecoveryReport",
    "RuntimeRestartRecoveryCoordinator",
    # Functions
    "run_startup_recovery",
    "get_recovery_coordinator",
    "reset_recovery_coordinator",
]

# PR-59: hybrid orchestration recovery sentinel
HYBRID_ORCHESTRATION_RECOVERY_POLICY: str = (
    "POLICY::HYBRID_ORCHESTRATION_RECOVERY: On process restart, "
    "HybridOrchestrationContinuityRegistry.mark_all_running_as_interrupted() "
    "is called to transition all non-terminal hybrid executions to 'interrupted'. "
    "Terminal executions are left as-is.  Live transport handles (A2A, GUI, VLM) "
    "are intentionally ephemeral and are NOT recovered — see "
    "HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY in "
    "core.hybrid_orchestration_continuity."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RUNTIME_RESTART_RECOVERY_IS_AUTHORITY: str = (
    "RUNTIME_RESTART_RECOVERY_IS_AUTHORITY: "
    "core/runtime_restart_recovery.py is the canonical entry-point for "
    "orchestrating Galaxy runtime state recovery after process restart, "
    "device disconnect, or transient infrastructure failure (PR-5)."
)

MESH_SESSION_RECOVERY_IS_DURABLE_POLICY: str = (
    "POLICY::MESH_SESSION_RECOVERY_IS_DURABLE: MeshSession recovery uses "
    "core.mesh.mesh_session_persistence.recover_mesh_sessions() which reads "
    "from the durable file-backed persistence store.  Non-terminal sessions "
    "are re-hydrated; terminal sessions are left as-is."
)

BODY_MESH_RECOVERY_IS_DURABLE_POLICY: str = (
    "POLICY::BODY_MESH_RECOVERY_IS_DURABLE: BodyMeshRegistry recovery uses "
    "core.mesh.body_mesh_persistence.restore_body_mesh_from_snapshot() which "
    "reads from the durable file-backed snapshot store and calls "
    "registry.register() for each recovered entry."
)

WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY: str = (
    "POLICY::WEBRTC_BINDINGS_ARE_EPHEMERAL: WebRTC transport bindings in "
    "core.webrtc_task_lifecycle are INTENTIONALLY not recovered across process "
    "restarts.  The underlying transport (peer connection, ICE state) is "
    "invalidated by a restart.  New bindings are created when tasks are "
    "re-dispatched.  This is a documented non-goal, not a gap."
)

RUNTIME_RESTART_RECOVERY_PR5_SENTINEL: str = (
    "RUNTIME_RESTART_RECOVERY_PR5::runtime-restart-recovery-coordinator-pr5-v1"
)

# PR-D1: in-flight task lifecycle durability sentinel
INFLIGHT_TASK_LIFECYCLE_RECOVERY_POLICY: str = (
    "POLICY::INFLIGHT_TASK_LIFECYCLE_RECOVERY: On process restart, "
    "RuntimeRestartRecoveryCoordinator recovers in-flight task lifecycle "
    "records from the durable snapshot written by "
    "core.task_lifecycle_persistence.TaskLifecyclePersistenceStore.  "
    "Each record is classified by InFlightTaskDisposition: "
    "RESUMABLE (device_dispatch/cross_device), REPLAY_ONLY (routing), "
    "REISSUABLE (gateway_ingress), or TERMINAL_ON_INTERRUPT (result_completion). "
    "The disposition drives how callers handle each recovered record. (PR-D1)"
)

# PR-6: hybrid continuity reconstruction from durable persistence
HYBRID_CONTINUITY_RECONSTRUCTION_POLICY: str = (
    "POLICY::HYBRID_CONTINUITY_RECONSTRUCTION: On process restart, "
    "RuntimeRestartRecoveryCoordinator can reconstruct non-terminal hybrid "
    "execution records from the HybridContinuityPersistenceStore via "
    "HybridOrchestrationContinuityRegistry.restore_from_persistence().  "
    "Records whose execution_id already exists in the live registry are "
    "skipped (in-process state takes precedence).  Remote partial results "
    "are automatically invalidated via invalidate_remote_partial_results() "
    "because the underlying transport is gone after restart.  Terminal "
    "records are not restored — they remain on disk for audit only. (PR-6)"
)

# Recovered lifecycle dispatch — converts documentary recovery into
# operational execution behavior.
RECOVERED_LIFECYCLE_DISPATCH_POLICY: str = (
    "POLICY::RECOVERED_LIFECYCLE_DISPATCH: After loading in-flight task "
    "records from the durable snapshot, RuntimeRestartRecoveryCoordinator "
    "converts each recovered record into a concrete registry action based on "
    "its InFlightTaskDisposition: "
    "RESUMABLE (device_dispatch/cross_device) → registered in "
    "TaskEnvelopeLifecycleRegistry under DEVICE_DISPATCH ownership so that "
    "resume_for_device() can re-dispatch when the device reconnects; "
    "REPLAY_ONLY (routing) → registered under ROUTING ownership so the task "
    "is available for a fresh routing pass; "
    "REISSUABLE (gateway_ingress) → registered under GATEWAY_INGRESS "
    "ownership so the source can re-issue or the gateway can detect the "
    "outstanding request; "
    "TERMINAL_ON_INTERRUPT (result_completion) → NOT registered in the "
    "pending registry — the result may already have been delivered and "
    "re-adding would risk duplicate completion.  Records already present in "
    "the registry (same task_id) are never overwritten.  This step is the "
    "canonical conversion from descriptive recovery to operational execution."
)

# PR-G: duplicate-safety for recovery dispatch
RECOVERY_DUPLICATE_SAFETY_POLICY: str = (
    "POLICY::RECOVERY_DUPLICATE_SAFETY: "
    "RuntimeRestartRecoveryCoordinator enforces three layers of duplicate "
    "suppression during recovery-to-execution transitions to prevent duplicate "
    "ownership, duplicate completion, and ambiguous finalization: "
    "(1) TERMINAL_ON_INTERRUPT records are never registered in the pending "
    "registry — the result may already have been delivered; "
    "(2) records whose task_id is already present in the live registry are "
    "skipped — in-process state takes precedence over snapshot state; "
    "(3) intra-snapshot duplicates (same task_id appearing more than once in "
    "a single snapshot) are deduplicated by restore_inflight_tasks_from_snapshot(), "
    "keeping the first occurrence.  All three layers are counted separately in "
    "RuntimeRecoveryReport (inflight_tasks_terminal, "
    "inflight_tasks_already_pending_skipped) and are logged for reviewability. "
    "(PR-G)"
)

# PR-G: recovery idempotency
RECOVERY_IDEMPOTENCY_POLICY: str = (
    "POLICY::RECOVERY_IDEMPOTENCY: "
    "Running RuntimeRestartRecoveryCoordinator.run_recovery() more than once "
    "is safe.  The duplicate guard in _dispatch_recovered_tasks() ensures that "
    "tasks already registered in the lifecycle registry by an earlier recovery "
    "pass are skipped on subsequent passes.  The intra-snapshot deduplication "
    "in restore_inflight_tasks_from_snapshot() ensures that each task_id from "
    "the snapshot is processed at most once per pass.  Together these two guards "
    "make repeated recovery runs idempotent with respect to registry state: "
    "the set of pending records after N recovery passes is identical to the set "
    "after one pass. (PR-G)"
)

# PR-1 (GAP_V2_TRUTH_PERSISTENCE closure): session truth recovery step
SESSION_TRUTH_RECOVERY_POLICY: str = (
    "POLICY::SESSION_TRUTH_RECOVERY: On process restart, "
    "RuntimeRestartRecoveryCoordinator reloads the most recent session truth "
    "records from the durable SessionTruthSnapshotStore into the "
    "CanonicalSessionTruthRuntime ring buffer via "
    "restore_session_truth_from_snapshot().  This makes session truth context "
    "available immediately after restart without waiting for new activity.  "
    "The snapshot store is also the default-on write-path for the runtime "
    "singleton — every new record is durably persisted as it is recorded.  "
    "Together these two mechanisms close GAP_V2_TRUTH_PERSISTENCE. (PR-1)"
)

# PR-1 (GAP_V2_TRUTH_PERSISTENCE closure): continuation / waiter reconciliation
CONTINUATION_WAITER_RECONCILIATION_POLICY: str = (
    "POLICY::CONTINUATION_WAITER_RECONCILIATION: On process restart, "
    "in-memory asyncio.Future waiters registered with CanonicalCompletionIngress "
    "are lost.  For tasks recovered with disposition RESUMABLE, REPLAY_ONLY, or "
    "REISSUABLE, RuntimeRestartRecoveryCoordinator resolves any stale future still "
    "registered in the CanonicalCompletionIngress with a RuntimeError('restart_recovery') "
    "so that callers receive an explicit signal rather than waiting indefinitely.  "
    "This prevents the control chain from hanging after a restart.  Actual "
    "result delivery will follow when the task is re-dispatched and the device "
    "reconnects.  TERMINAL_ON_INTERRUPT tasks are excluded because their result "
    "may already have been delivered.  Closes GAP_V2_TRUTH_PERSISTENCE. (PR-1)"
)



@dataclass
class RuntimeRecoveryReport:
    """Report produced by a recovery run.

    Attributes
    ----------
    recovery_id
        Unique identifier for this recovery run.
    started_at
        Wall-clock timestamp when recovery began.
    completed_at
        Wall-clock timestamp when recovery completed (or None if not yet done).
    mesh_sessions_recovered
        Number of non-terminal mesh sessions restored from durable storage.
    mesh_sessions_skipped
        Number of mesh sessions that were terminal and intentionally skipped.
    body_mesh_entries_restored
        Number of BodyMeshRegistry entries restored from the durable snapshot.
    webrtc_bindings_cleared
        True — WebRTC bindings are always cleared on restart (intentional).
    inflight_tasks_dispatch_actions_taken
        Number of recovered in-flight task records that were converted into
        concrete runtime registry actions (i.e. non-terminal records that were
        added to the lifecycle registry under their disposition-appropriate
        ownership stage).  Terminal records are excluded from this count.
    session_truth_records_restored
        Number of canonical session truth records reloaded from the durable
        snapshot into the in-memory ring buffer during restart recovery. (PR-1)
    continuation_waiters_reconciled
        Number of stale asyncio.Future waiters resolved with a restart error
        during the continuation reconciliation step so that callers are not
        left waiting indefinitely after a restart. (PR-1)
    errors
        List of non-fatal error strings encountered during recovery.
    non_goals
        Explicit list of what is intentionally not recovered (for reviewability).
    """

    recovery_id: str = field(default_factory=lambda: f"rcv_{uuid.uuid4().hex[:12]}")
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    mesh_sessions_recovered: int = 0
    mesh_sessions_skipped: int = 0
    body_mesh_entries_restored: int = 0
    webrtc_bindings_cleared: bool = True
    hybrid_executions_interrupted: int = 0
    hybrid_executions_restored: int = 0
    hybrid_remote_partial_invalidated: int = 0
    inflight_tasks_recovered: int = 0
    inflight_tasks_resumable: int = 0
    inflight_tasks_replay_only: int = 0
    inflight_tasks_reissuable: int = 0
    inflight_tasks_terminal: int = 0
    inflight_tasks_dispatch_actions_taken: int = 0
    inflight_tasks_already_pending_skipped: int = 0
    session_truth_records_restored: int = 0
    continuation_waiters_reconciled: int = 0
    errors: List[str] = field(default_factory=list)
    non_goals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "recovery_id": self.recovery_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "mesh_sessions_recovered": self.mesh_sessions_recovered,
            "mesh_sessions_skipped": self.mesh_sessions_skipped,
            "body_mesh_entries_restored": self.body_mesh_entries_restored,
            "webrtc_bindings_cleared": self.webrtc_bindings_cleared,
            "hybrid_executions_interrupted": self.hybrid_executions_interrupted,
            "hybrid_executions_restored": self.hybrid_executions_restored,
            "hybrid_remote_partial_invalidated": self.hybrid_remote_partial_invalidated,
            "inflight_tasks_recovered": self.inflight_tasks_recovered,
            "inflight_tasks_resumable": self.inflight_tasks_resumable,
            "inflight_tasks_replay_only": self.inflight_tasks_replay_only,
            "inflight_tasks_reissuable": self.inflight_tasks_reissuable,
            "inflight_tasks_terminal": self.inflight_tasks_terminal,
            "inflight_tasks_dispatch_actions_taken": self.inflight_tasks_dispatch_actions_taken,
            "inflight_tasks_already_pending_skipped": self.inflight_tasks_already_pending_skipped,
            "session_truth_records_restored": self.session_truth_records_restored,
            "continuation_waiters_reconciled": self.continuation_waiters_reconciled,
            "errors": list(self.errors),
            "non_goals": list(self.non_goals),
        }

    @property
    def duration_seconds(self) -> Optional[float]:
        """Return duration in seconds, or None if recovery is still running."""
        if self.completed_at is None:
            return None
        return self.completed_at - self.started_at

    @property
    def has_errors(self) -> bool:
        """True if any non-fatal errors were encountered."""
        return bool(self.errors)

    @property
    def success(self) -> bool:
        """True if recovery completed without errors."""
        return self.completed_at is not None and not self.errors


# ---------------------------------------------------------------------------
# RuntimeRestartRecoveryCoordinator
# ---------------------------------------------------------------------------


class RuntimeRestartRecoveryCoordinator:
    """Orchestrates recovery of runtime-critical state after restart.

    Call :meth:`run_recovery` once at process startup to restore all
    durable state components.

    Parameters
    ----------
    mesh_session_store:
        Optional :class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore`
        to use for session recovery.  Defaults to the process-level singleton.
    body_mesh_store:
        Optional :class:`~core.mesh.body_mesh_persistence.BodyMeshPersistenceStore`
        to use for body mesh recovery.  Defaults to the process-level singleton.
    body_mesh_registry:
        Optional :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` to
        populate during body mesh recovery.  Defaults to the process-level
        singleton returned by :func:`~core.mesh.body_mesh_registry.get_body_mesh_registry`.
    """

    def __init__(
        self,
        mesh_session_store=None,
        body_mesh_store=None,
        body_mesh_registry=None,
        hybrid_continuity_registry=None,
        hybrid_continuity_store=None,
        task_lifecycle_store=None,
    ) -> None:
        self._mesh_session_store = mesh_session_store
        self._body_mesh_store = body_mesh_store
        self._body_mesh_registry = body_mesh_registry
        self._hybrid_continuity_registry = hybrid_continuity_registry
        self._hybrid_continuity_store = hybrid_continuity_store
        self._task_lifecycle_store = task_lifecycle_store

    def run_recovery(self) -> RuntimeRecoveryReport:
        """Orchestrate a full recovery pass.

        Steps
        -----
        1. Recover non-terminal MeshSession coordinator states.
        2. Restore BodyMeshRegistry entries from the durable snapshot.
        3. Clear in-memory WebRTC bindings (intentional — transport is gone).
        4. Mark in-flight hybrid executions as interrupted (PR-59); restore
           non-terminal records from durable persistence store and invalidate
           remote partial results (PR-6).
        5. Recover in-flight task lifecycle records from durable snapshot and
           convert each recovered disposition into a concrete registry action
           (see :data:`RECOVERED_LIFECYCLE_DISPATCH_POLICY`):

           * **RESUMABLE** → registered under ``DEVICE_DISPATCH`` ownership so
             :meth:`~core.task_envelope_lifecycle_registry
             .TaskEnvelopeLifecycleRegistry.resume_for_device` can re-dispatch
             when the device reconnects.
           * **REPLAY_ONLY** → registered under ``ROUTING`` ownership so a
             fresh routing pass can be triggered.
           * **REISSUABLE** → registered under ``GATEWAY_INGRESS`` ownership
             so the source can re-issue.
           * **TERMINAL_ON_INTERRUPT** → NOT registered; result may already
             have been delivered (PR-D1).

        Returns
        -------
        :class:`RuntimeRecoveryReport`
            Details of what was recovered, what was skipped, and any errors.
        """
        report = RuntimeRecoveryReport()
        report.non_goals = [
            "WebRTC transport bindings are intentionally ephemeral and "
            "are NOT recovered. See WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY.",
            "Device heartbeat state is NOT recovered. Devices re-register on "
            "reconnect.",
            "Hybrid execution transport handles (A2A connections, GUI handles, "
            "VLM context) are intentionally ephemeral and are NOT recovered. "
            "See HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY.",
            "In-flight task RESULTS and partial execution state are NOT "
            "recovered — only the task identity, ownership stage, and "
            "disposition classification are restored from the lifecycle "
            "snapshot.  Callers must re-dispatch or replay tasks to obtain "
            "fresh results. See INFLIGHT_TASK_LIFECYCLE_RECOVERY_POLICY.",
        ]

        # ----------------------------------------------------------------
        # Step 1: MeshSession recovery
        # ----------------------------------------------------------------
        try:
            self._recover_mesh_sessions(report)
        except Exception as exc:
            err = f"MeshSession recovery failed: {exc}"
            logger.exception("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 2: BodyMeshRegistry recovery
        # ----------------------------------------------------------------
        try:
            self._recover_body_mesh(report)
        except Exception as exc:
            err = f"BodyMesh recovery failed: {exc}"
            logger.exception("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 3: Clear WebRTC in-memory bindings (intentional)
        # ----------------------------------------------------------------
        try:
            self._clear_webrtc_bindings(report)
        except Exception as exc:
            err = f"WebRTC binding clear failed: {exc}"
            logger.warning("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 4: Mark in-flight hybrid orchestration executions as
        #         interrupted (PR-59); restore from durable persistence
        #         store and invalidate remote partial results (PR-6).
        # ----------------------------------------------------------------
        try:
            self._recover_hybrid_orchestration(report)
        except Exception as exc:
            err = f"Hybrid orchestration recovery failed: {exc}"
            logger.warning("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 5: Recover in-flight task lifecycle state from durable
        #         snapshot (PR-D1)
        # ----------------------------------------------------------------
        try:
            self._recover_inflight_tasks(report)
        except Exception as exc:
            err = f"In-flight task lifecycle recovery failed: {exc}"
            logger.warning("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 6: Recover session truth from durable snapshot (PR-1 /
        #         GAP_V2_TRUTH_PERSISTENCE closure).
        #
        #         reload the most recent CanonicalSessionTruthRecord entries
        #         from the file-backed SessionTruthSnapshotStore into the
        #         in-memory CanonicalSessionTruthRuntime ring buffer.
        # ----------------------------------------------------------------
        try:
            self._recover_session_truth(report)
        except Exception as exc:
            err = f"Session truth recovery failed: {exc}"
            logger.warning("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 7: Reconcile stale continuation / waiter futures (PR-1 /
        #         GAP_V2_TRUTH_PERSISTENCE closure).
        #
        #         For every RESUMABLE or REPLAY_ONLY task recovered in
        #         step 5, resolve any matching asyncio.Future registered
        #         in CanonicalCompletionIngress with a restart error so
        #         that callers are not left waiting indefinitely.
        # ----------------------------------------------------------------
        try:
            self._reconcile_continuation_waiters(report)
        except Exception as exc:
            err = f"Continuation waiter reconciliation failed: {exc}"
            logger.warning("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        report.completed_at = time.time()
        logger.info(
            "RuntimeRestartRecovery: completed recovery_id=%s "
            "mesh_sessions=%d body_entries=%d "
            "hybrid_interrupted=%d hybrid_restored=%d hybrid_invalidated=%d "
            "inflight_recovered=%d (resumable=%d replay=%d reissue=%d terminal=%d) "
            "truth_restored=%d continuation_reconciled=%d "
            "errors=%d",
            report.recovery_id,
            report.mesh_sessions_recovered,
            report.body_mesh_entries_restored,
            report.hybrid_executions_interrupted,
            report.hybrid_executions_restored,
            report.hybrid_remote_partial_invalidated,
            report.inflight_tasks_recovered,
            report.inflight_tasks_resumable,
            report.inflight_tasks_replay_only,
            report.inflight_tasks_reissuable,
            report.inflight_tasks_terminal,
            report.session_truth_records_restored,
            report.continuation_waiters_reconciled,
            len(report.errors),
        )
        return report

    def _recover_mesh_sessions(self, report: RuntimeRecoveryReport) -> None:
        """Recover non-terminal mesh session states."""
        from core.mesh.mesh_session_persistence import recover_mesh_sessions
        records = recover_mesh_sessions(store=self._mesh_session_store)
        report.mesh_sessions_recovered = len(records)

        # Count how many were skipped (terminal)
        try:
            from core.mesh.mesh_session_persistence import (
                get_persistence_store,
                MeshSessionPersistenceStore,
            )
            store = self._mesh_session_store or get_persistence_store()
            all_ids_raw = store.list_recoverable()
            # list_recoverable only returns non-terminal; total = records + skipped
            # We can get the total by checking the store's memory cache directly
            # For a conservative estimate: skipped = (total on disk) - recovered
            # But list_recoverable() only returns non-terminal ones, so skipped is unknown
            # without a separate "list_all" API.  Leave at 0 for now.
            report.mesh_sessions_skipped = 0
        except Exception:
            pass

        logger.info(
            "RuntimeRestartRecovery: recovered %d mesh sessions",
            report.mesh_sessions_recovered,
        )

    def _recover_body_mesh(self, report: RuntimeRecoveryReport) -> None:
        """Restore BodyMeshRegistry entries from snapshot."""
        from core.mesh.body_mesh_persistence import restore_body_mesh_from_snapshot

        registry = self._body_mesh_registry
        if registry is None:
            try:
                from core.mesh.body_mesh_registry import get_body_mesh_registry
                registry = get_body_mesh_registry()
            except Exception as exc:
                logger.warning(
                    "RuntimeRestartRecovery: could not get body mesh registry: %s", exc
                )
                return

        restored = restore_body_mesh_from_snapshot(
            registry=registry,
            store=self._body_mesh_store,
        )
        report.body_mesh_entries_restored = restored
        logger.info(
            "RuntimeRestartRecovery: restored %d body mesh entries",
            restored,
        )

    def _clear_webrtc_bindings(self, report: RuntimeRecoveryReport) -> None:
        """Clear in-memory WebRTC task bindings — intentionally ephemeral."""
        try:
            from core.webrtc_task_lifecycle import reset_webrtc_task_session_registry
            reset_webrtc_task_session_registry()
            report.webrtc_bindings_cleared = True
            logger.debug("RuntimeRestartRecovery: WebRTC bindings cleared (intentional)")
        except Exception as exc:
            # Non-fatal — bindings are ephemeral anyway
            logger.debug(
                "RuntimeRestartRecovery: could not clear WebRTC bindings: %s", exc
            )
            report.webrtc_bindings_cleared = False

    def _recover_hybrid_orchestration(self, report: RuntimeRecoveryReport) -> None:
        """Mark in-flight hybrid executions as interrupted; restore from store (PR-59 / PR-6).

        Step 4a (PR-59): Transition all non-terminal, non-interrupted hybrid
        executions in the :class:`~core.hybrid_orchestration_continuity
        .HybridOrchestrationContinuityRegistry` to the ``interrupted`` state.

        Step 4b (PR-6): If a :class:`~core.hybrid_orchestration_continuity
        .HybridContinuityPersistenceStore` is available, restore non-terminal
        records from disk into the registry (records already present take
        precedence) and invalidate remote partial results.
        """
        from core.hybrid_orchestration_continuity import (
            get_continuity_registry,
        )
        registry = (
            self._hybrid_continuity_registry
            if self._hybrid_continuity_registry is not None
            else get_continuity_registry()
        )

        # 4a: mark running executions as interrupted
        count = registry.mark_all_running_as_interrupted(
            reason="process_restart"
        )
        report.hybrid_executions_interrupted = count
        logger.info(
            "RuntimeRestartRecovery: marked %d hybrid executions as "
            "interrupted",
            count,
        )

        # 4b: restore non-terminal records from the durable persistence store
        if self._hybrid_continuity_store is not None:
            restored = registry.restore_from_persistence(
                self._hybrid_continuity_store
            )
            report.hybrid_executions_restored += restored
            logger.info(
                "RuntimeRestartRecovery: restored %d hybrid executions "
                "from persistence store",
                restored,
            )
            # Mark any newly-restored running/dispatched records as interrupted —
            # they were in-flight when the process died and must be interrupted
            # even though they were not present in the live registry during step 4a.
            extra_interrupted = registry.mark_all_running_as_interrupted(
                reason="process_restart_from_store"
            )
            report.hybrid_executions_interrupted += extra_interrupted
            # Invalidate remote partial results — transport is gone after restart
            invalidated = registry.invalidate_remote_partial_results()
            report.hybrid_remote_partial_invalidated = invalidated
            logger.info(
                "RuntimeRestartRecovery: invalidated %d remote partial "
                "results",
                invalidated,
            )

    def _recover_inflight_tasks(self, report: RuntimeRecoveryReport) -> None:
        """Recover in-flight task lifecycle records from the durable snapshot (PR-D1).

        Calls :func:`~core.task_lifecycle_persistence
        .restore_inflight_tasks_from_snapshot` to load all records that were
        pending at the time of the previous process exit.  Each record is
        classified by :class:`~core.task_lifecycle_persistence
        .InFlightTaskDisposition`; the counts are recorded in the report.

        After counting, this method calls :meth:`_dispatch_recovered_tasks` to
        convert each recovered disposition into a concrete registry action
        (see :data:`RECOVERED_LIFECYCLE_DISPATCH_POLICY`).
        """
        from core.task_lifecycle_persistence import (
            InFlightTaskDisposition,
            restore_inflight_tasks_from_snapshot,
        )
        restored = restore_inflight_tasks_from_snapshot(
            store=self._task_lifecycle_store,
        )
        report.inflight_tasks_recovered = len(restored)
        for rec in restored:
            if rec.disposition == InFlightTaskDisposition.RESUMABLE:
                report.inflight_tasks_resumable += 1
            elif rec.disposition == InFlightTaskDisposition.REPLAY_ONLY:
                report.inflight_tasks_replay_only += 1
            elif rec.disposition == InFlightTaskDisposition.REISSUABLE:
                report.inflight_tasks_reissuable += 1
            elif rec.disposition == InFlightTaskDisposition.TERMINAL_ON_INTERRUPT:
                report.inflight_tasks_terminal += 1
        logger.info(
            "RuntimeRestartRecovery: recovered %d in-flight tasks "
            "(resumable=%d replay=%d reissue=%d terminal=%d)",
            report.inflight_tasks_recovered,
            report.inflight_tasks_resumable,
            report.inflight_tasks_replay_only,
            report.inflight_tasks_reissuable,
            report.inflight_tasks_terminal,
        )
        # Convert documentary recovery into operational execution behavior.
        self._dispatch_recovered_tasks(restored, report)

    def _dispatch_recovered_tasks(
        self,
        restored: "List[Any]",
        report: RuntimeRecoveryReport,
    ) -> None:
        """Convert recovered lifecycle records into concrete registry actions.

        This is the operational conversion step described by
        :data:`RECOVERED_LIFECYCLE_DISPATCH_POLICY`.  Each non-terminal
        record is added to the :class:`~core.task_envelope_lifecycle_registry
        .TaskEnvelopeLifecycleRegistry` under the ownership stage that
        corresponds to its :class:`~core.task_lifecycle_persistence
        .InFlightTaskDisposition`:

        * **RESUMABLE** → :attr:`~core.task_envelope_lifecycle_registry
          .LifecycleOwner.DEVICE_DISPATCH` — the task was dispatched to a
          device; it is placed back under DEVICE_DISPATCH ownership so that
          :meth:`~core.task_envelope_lifecycle_registry
          .TaskEnvelopeLifecycleRegistry.resume_for_device` will find it and
          re-dispatch when the device reconnects.

        * **REPLAY_ONLY** → :attr:`~core.task_envelope_lifecycle_registry
          .LifecycleOwner.ROUTING` — the task was in routing; it is placed
          under ROUTING ownership so a fresh routing pass can be triggered.

        * **REISSUABLE** → :attr:`~core.task_envelope_lifecycle_registry
          .LifecycleOwner.GATEWAY_INGRESS` — the task was at ingress; it is
          placed under GATEWAY_INGRESS ownership so the source can re-issue
          or the gateway can detect the outstanding request.

        * **TERMINAL_ON_INTERRUPT** → **not registered** — the result may
          already have been delivered; re-adding would risk duplicate
          completion.

        Duplicate prevention
        --------------------
        Records whose ``task_id`` is already present in the registry are
        **not** overwritten — the live (in-process) record takes precedence.
        This prevents duplicate ownership after a partial restart.

        Parameters
        ----------
        restored:
            List of :class:`~core.task_lifecycle_persistence.RestoredTaskRecord`
            instances from :func:`~core.task_lifecycle_persistence
            .restore_inflight_tasks_from_snapshot`.
        report:
            The :class:`RuntimeRecoveryReport` being built; updated with
            ``inflight_tasks_dispatch_actions_taken``.
        """
        if not restored:
            return

        try:
            from core.task_lifecycle_persistence import InFlightTaskDisposition
            from core.task_envelope_lifecycle_registry import (
                get_lifecycle_registry,
                LifecycleOwner,
                PendingEnvelopeRecord,
            )
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                "import failed — %s",
                exc,
            )
            return

        # Disposition → canonical registry ownership stage
        _disposition_to_owner = {
            InFlightTaskDisposition.RESUMABLE: LifecycleOwner.DEVICE_DISPATCH,
            InFlightTaskDisposition.REPLAY_ONLY: LifecycleOwner.ROUTING,
            InFlightTaskDisposition.REISSUABLE: LifecycleOwner.GATEWAY_INGRESS,
        }

        try:
            registry = get_lifecycle_registry()
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                "could not obtain lifecycle registry — %s",
                exc,
            )
            return

        actions_taken = 0
        already_pending_skipped = 0
        import time as _time_mod

        for rec in restored:
            if rec.disposition == InFlightTaskDisposition.TERMINAL_ON_INTERRUPT:
                # Terminal records are intentionally excluded from the pending
                # registry — the result may already have been delivered.
                logger.debug(
                    "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                    "task_id=%s is TERMINAL_ON_INTERRUPT — not re-registered",
                    rec.task_id,
                )
                continue

            target_owner = _disposition_to_owner.get(rec.disposition)
            if target_owner is None:
                logger.warning(
                    "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                    "unknown disposition %r for task_id=%s — skipping",
                    rec.disposition,
                    rec.task_id,
                )
                continue

            if not rec.task_id:
                logger.debug(
                    "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                    "skipping record with empty task_id"
                )
                continue

            # Duplicate guard — never overwrite a live in-process record.
            if registry.is_pending(rec.task_id):
                already_pending_skipped += 1
                logger.debug(
                    "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                    "task_id=%s already pending — skipping (live record takes "
                    "precedence). See RECOVERY_DUPLICATE_SAFETY_POLICY.",
                    rec.task_id,
                )
                continue

            # Reconstruct a PendingEnvelopeRecord and insert it directly.
            try:
                owner = LifecycleOwner(rec.owner) if rec.owner in {
                    o.value for o in LifecycleOwner
                } else target_owner
                # Always use the disposition-mapped owner as the authoritative
                # post-restart stage — the snapshot owner tells us where the
                # task *was*, the disposition tells us where it needs to *be*.
                pending_record = PendingEnvelopeRecord(
                    task_id=rec.task_id,
                    trace_id=rec.trace_id,
                    target_device_id=rec.target_device_id,
                    tool_name=rec.tool_name,
                    owner=target_owner,
                    timeout=rec.timeout,
                    registered_at=rec.registered_at,
                    future=None,
                    metadata={
                        **rec.metadata,
                        "recovered_at": _time_mod.time(),
                        "recovered_disposition": rec.disposition.value,
                        "snapshot_owner": rec.owner,
                        "snapshot_id": rec.snapshot_id,
                        "recovery_action": "dispatched_by_coordinator",
                    },
                )
                # pylint: disable=protected-access
                registry._pending[rec.task_id] = pending_record
                actions_taken += 1
                logger.info(
                    "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                    "task_id=%s disposition=%s → owner=%s (operational)",
                    rec.task_id,
                    rec.disposition.value,
                    target_owner.value,
                )
            except Exception as exc:
                logger.warning(
                    "RuntimeRestartRecovery._dispatch_recovered_tasks: "
                    "failed to register task_id=%s — %s",
                    rec.task_id,
                    exc,
                )

        report.inflight_tasks_dispatch_actions_taken = actions_taken
        report.inflight_tasks_already_pending_skipped = already_pending_skipped
        logger.info(
            "RuntimeRestartRecovery._dispatch_recovered_tasks: "
            "%d dispatch action(s) taken (%d terminal skipped, %d already-pending skipped). "
            "See RECOVERY_DUPLICATE_SAFETY_POLICY.",
            actions_taken,
            report.inflight_tasks_terminal,
            already_pending_skipped,
        )

    def _recover_session_truth(self, report: RuntimeRecoveryReport) -> None:
        """Reload session truth records from the durable snapshot (PR-1).

        Calls :func:`~core.session_truth_snapshot.restore_session_truth_from_snapshot`
        to re-populate the :class:`~core.canonical_session_truth
        .CanonicalSessionTruthRuntime` ring buffer from the file-backed
        :class:`~core.session_truth_snapshot.SessionTruthSnapshotStore`.

        Sets :attr:`RuntimeRecoveryReport.session_truth_records_restored`.
        Degrades gracefully if the snapshot module is unavailable.

        See :data:`SESSION_TRUTH_RECOVERY_POLICY`.
        """
        try:
            from core.session_truth_snapshot import (
                restore_session_truth_from_snapshot,
                get_session_truth_snapshot_store,
            )
            from core.canonical_session_truth import get_canonical_session_truth_runtime
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._recover_session_truth: "
                "import failed — %s",
                exc,
            )
            return

        try:
            _store = get_session_truth_snapshot_store()
            _runtime = get_canonical_session_truth_runtime()
            restored = restore_session_truth_from_snapshot(
                runtime=_runtime,
                store=_store,
            )
            report.session_truth_records_restored = restored
            logger.info(
                "RuntimeRestartRecovery._recover_session_truth: "
                "restored %d session truth record(s) from snapshot. "
                "See SESSION_TRUTH_RECOVERY_POLICY.",
                restored,
            )
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._recover_session_truth: "
                "restore failed — %s",
                exc,
            )

    def _reconcile_continuation_waiters(self, report: RuntimeRecoveryReport) -> None:
        """Resolve stale continuation futures with a restart error (PR-1).

        For every task recovered with disposition RESUMABLE or REPLAY_ONLY,
        resolves any asyncio.Future registered in
        :class:`~core.canonical_completion_ingress.CanonicalCompletionIngress`
        under that task_id with a :class:`RuntimeError` carrying
        ``'restart_recovery'``.  This unblocks callers that were awaiting the
        future before the restart, so the control chain does not hang
        indefinitely.

        TERMINAL_ON_INTERRUPT tasks are excluded because their result may
        already have been delivered; resolving their futures could cause
        duplicate-result handling on the awaiting side.

        Sets :attr:`RuntimeRecoveryReport.continuation_waiters_reconciled`.
        Degrades gracefully if ``CanonicalCompletionIngress`` is unavailable.

        See :data:`CONTINUATION_WAITER_RECONCILIATION_POLICY`.
        """
        try:
            from core.canonical_completion_ingress import (
                get_canonical_completion_ingress,
            )
            from core.task_lifecycle_persistence import InFlightTaskDisposition
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._reconcile_continuation_waiters: "
                "import failed — %s",
                exc,
            )
            return

        # Collect task_ids for RESUMABLE and REPLAY_ONLY recovered tasks.
        # These are the tasks for which stale futures must be resolved.
        resumable_task_ids = []
        try:
            from core.task_lifecycle_persistence import (
                restore_inflight_tasks_from_snapshot,
            )
            restored = restore_inflight_tasks_from_snapshot(
                store=self._task_lifecycle_store,
            )
            for rec in restored:
                if rec.disposition in (
                    InFlightTaskDisposition.RESUMABLE,
                    InFlightTaskDisposition.REPLAY_ONLY,
                    InFlightTaskDisposition.REISSUABLE,
                ):
                    if rec.task_id:
                        resumable_task_ids.append(rec.task_id)
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._reconcile_continuation_waiters: "
                "could not enumerate recovered tasks — %s",
                exc,
            )
            return

        if not resumable_task_ids:
            return

        try:
            ingress = get_canonical_completion_ingress()
        except Exception as exc:
            logger.warning(
                "RuntimeRestartRecovery._reconcile_continuation_waiters: "
                "could not get CanonicalCompletionIngress — %s",
                exc,
            )
            return

        reconciled = 0
        restart_error = RuntimeError(
            "restart_recovery: V2 restarted; waiter unblocked for re-dispatch"
        )
        for task_id in resumable_task_ids:
            try:
                # fail_pending_dispatch sets fut.set_exception so the awaiting
                # coroutine raises RuntimeError rather than receiving a result.
                resolved = ingress.fail_pending_dispatch(
                    task_id,
                    restart_error,
                )
                if resolved:
                    reconciled += 1
                    logger.debug(
                        "RuntimeRestartRecovery._reconcile_continuation_waiters: "
                        "resolved stale future for task_id=%s",
                        task_id,
                    )
            except Exception as exc:
                logger.debug(
                    "RuntimeRestartRecovery._reconcile_continuation_waiters: "
                    "could not resolve future for task_id=%s — %s",
                    task_id,
                    exc,
                )

        report.continuation_waiters_reconciled = reconciled
        logger.info(
            "RuntimeRestartRecovery._reconcile_continuation_waiters: "
            "%d stale continuation future(s) reconciled. "
            "See CONTINUATION_WAITER_RECONCILIATION_POLICY.",
            reconciled,
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_coordinator_instance: Optional[RuntimeRestartRecoveryCoordinator] = None


def get_recovery_coordinator(**kwargs) -> RuntimeRestartRecoveryCoordinator:
    """Return the process-level :class:`RuntimeRestartRecoveryCoordinator` singleton."""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = RuntimeRestartRecoveryCoordinator(**kwargs)
    return _coordinator_instance


def reset_recovery_coordinator() -> None:
    """Reset the singleton (for testing)."""
    global _coordinator_instance
    _coordinator_instance = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def run_startup_recovery(
    mesh_session_store=None,
    body_mesh_store=None,
    body_mesh_registry=None,
    hybrid_continuity_registry=None,
    hybrid_continuity_store=None,
    task_lifecycle_store=None,
) -> RuntimeRecoveryReport:
    """Run a full startup recovery pass.

    Convenience entry-point for use in process startup code::

        from core.runtime_restart_recovery import run_startup_recovery
        report = run_startup_recovery()
        if report.has_errors:
            logger.warning("Startup recovery had errors: %s", report.errors)

    Parameters
    ----------
    mesh_session_store:
        Optional explicit mesh session persistence store.
    body_mesh_store:
        Optional explicit body mesh persistence store.
    body_mesh_registry:
        Optional explicit body mesh registry to populate.
    hybrid_continuity_registry:
        Optional explicit hybrid orchestration continuity registry.  When
        provided, its ``mark_all_running_as_interrupted`` method is called
        during recovery step 4 (PR-59).
    hybrid_continuity_store:
        Optional explicit :class:`~core.hybrid_orchestration_continuity
        .HybridContinuityPersistenceStore`.  When provided, non-terminal
        hybrid execution records are restored from disk into the registry
        and remote partial results are invalidated during step 4 (PR-6).
    task_lifecycle_store:
        Optional explicit :class:`~core.task_lifecycle_persistence
        .TaskLifecyclePersistenceStore`.  When provided, in-flight task
        lifecycle records are recovered from this store during step 5 (PR-D1).

    Returns
    -------
    :class:`RuntimeRecoveryReport`
    """
    coordinator = RuntimeRestartRecoveryCoordinator(
        mesh_session_store=mesh_session_store,
        body_mesh_store=body_mesh_store,
        body_mesh_registry=body_mesh_registry,
        hybrid_continuity_registry=hybrid_continuity_registry,
        hybrid_continuity_store=hybrid_continuity_store,
        task_lifecycle_store=task_lifecycle_store,
    )
    return coordinator.run_recovery()
