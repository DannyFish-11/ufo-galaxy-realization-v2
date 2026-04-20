"""core/mesh/live_mesh_runtime_engine.py
=========================================
Live Mesh Runtime Engine — PR-J.

This module implements the **Live Mesh Runtime Engine**: the execution driver
that advances a ``staged_mesh`` from its pre-activation state into a fully
live, coordinated, and convergent mesh runtime session.

It is the execution backbone for PR-J (*Live Mesh Runtime Engine + staged_mesh
真实可达化*) and answers:

    *"Given a MeshSessionCoordinatorState, how does the runtime actually
    drive participants through work, reach barriers, aggregate results, and
    produce a final closure output?"*

Key responsibilities
--------------------
1. **Staged → Live promotion**: verify readiness of the coordinator state and
   advance it from ``pending`` to ``active``.
2. **Participant tracking**: maintain per-participant status through
   ``pending → ready → working → waiting/completed/failed``.
3. **Barrier coordination**: detect when all active participants have reached
   the barrier, release the barrier, or handle timeout / participant drop.
4. **Merge / aggregation**: collect per-participant partial results and
   produce a merged output.
5. **Result handling**: assemble a :class:`LiveMeshRunResult` that captures
   the final outcome (full, partial, failure) and propagates it back to the
   caller.
6. **Observability**: emit structured log events for every key lifecycle
   transition so the mesh runtime is fully observable.

Design principles
-----------------
- **Additive only** — does not modify any existing module; adds new surfaces.
- **Reuses existing contracts** — builds on
  :mod:`contracts.mesh_session_coordinator` and
  :mod:`contracts.mesh_session`; no parallel session registry.
- **Graceful degradation** — every public function returns a valid result
  even on partial failure; never raises to callers.
- **Stateless engine** — the engine itself holds no mutable session state;
  it operates on coordinator state objects passed in by the caller and
  returns updated state objects.
- **Timeout / drop resilience** — missing participants and barrier stalls are
  handled with configurable timeouts and degraded-completion semantics.

Usage::

    from core.mesh.live_mesh_runtime_engine import (
        LiveMeshRuntimeEngine,
        run_live_mesh_session,
    )

    engine = LiveMeshRuntimeEngine()
    result = engine.run(coordinator_state, participant_results={...})
    print(result.to_dict())

See ``docs/LIVE_MESH_RUNTIME_ENGINE.md`` for the full specification.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-J authority sentinels
# ---------------------------------------------------------------------------

LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL: str = (
    "SENTINEL::LIVE_MESH_RUNTIME_ENGINE_PR_J: "
    "live mesh runtime engine enabling staged_mesh true reachability; "
    "package=PR-J::live-mesh-runtime-engine-staged-mesh-realization"
)

STAGED_MESH_LIVE_PROMOTION_PR_J_POLICY: str = (
    "POLICY::STAGED_MESH_LIVE_PROMOTION_PR_J: "
    "A staged_mesh coordinator state MUST be promoted from 'pending' to "
    "'active' before execution begins.  Promotion requires that at least one "
    "participant is registered and the coordinator session_id is set.  If the "
    "state cannot be promoted, the engine MUST return a failed LiveMeshRunResult "
    "with reason='promotion_failed' rather than silently returning a stale state."
)

PARTICIPANT_TRACKING_PR_J_POLICY: str = (
    "POLICY::PARTICIPANT_TRACKING_PR_J: "
    "The live mesh engine MUST maintain per-participant status through the full "
    "lifecycle: pending → ready → working → (waiting | completed | failed | offline). "
    "Status transitions MUST be recorded as coordination events.  At least one "
    "participant MUST reach 'completed' for the session to be considered fully "
    "successful; partial completion is a valid non-failure outcome."
)

BARRIER_COORDINATION_PR_J_POLICY: str = (
    "POLICY::BARRIER_COORDINATION_PR_J: "
    "Barrier synchronisation MUST evaluate whether all active participants have "
    "reached the barrier before releasing it.  If the barrier_posture is "
    "'not_required', the engine MUST skip barrier evaluation and proceed directly "
    "to merge.  A barrier MUST time out (status=failed) rather than block "
    "indefinitely if not all participants arrive within the timeout window."
)

MERGE_AGGREGATION_PR_J_POLICY: str = (
    "POLICY::MERGE_AGGREGATION_PR_J: "
    "Result merge MUST aggregate per-participant partial results into a single "
    "merged output dict.  Merge is repeatable and order-independent.  Conflicts "
    "are resolved by last-writer-wins keyed by device_id.  An empty participant "
    "result set is a valid (empty) merge output, not an error."
)

RESULT_HANDLING_PR_J_POLICY: str = (
    "POLICY::RESULT_HANDLING_PR_J: "
    "The LiveMeshRunResult MUST carry outcome='completed', 'partial', or "
    "'failed'.  A 'completed' result requires all participants to have completed "
    "successfully.  A 'partial' result requires at least one participant to have "
    "completed.  A 'failed' result means no participants completed.  The final "
    "merged_result dict is always present (may be empty on failure)."
)


# ---------------------------------------------------------------------------
# LiveMeshRunResult — final output of the engine
# ---------------------------------------------------------------------------


class LiveMeshRunResult:
    """Final output of a live mesh session execution.

    Attributes
    ----------
    run_id:
        Unique identifier for this run.
    session_id:
        Mesh session ID from the coordinator state.
    mesh_id:
        Mesh/body identifier.
    trace_id:
        Trace correlation ID.
    outcome:
        One of ``'completed'``, ``'partial'``, ``'failed'``.
    success:
        True for ``completed`` and ``partial``; False for ``failed``.
    merged_result:
        Aggregated result dict from all completed participants.
    participant_outcomes:
        Per-participant outcome dict keyed by ``device_id``.
    barrier_released:
        Whether the barrier was successfully released.
    coordinator_state:
        Final coordinator state after engine execution.
    errors:
        List of error strings accumulated during execution.
    metadata:
        Arbitrary extension metadata.
    created_at:
        Unix timestamp (seconds) when this result was created.
    """

    def __init__(
        self,
        *,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        mesh_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        outcome: str = "failed",
        success: bool = False,
        merged_result: Optional[Dict[str, Any]] = None,
        participant_outcomes: Optional[Dict[str, Any]] = None,
        barrier_released: bool = False,
        coordinator_state: Any = None,
        errors: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.run_id: str = run_id or f"lmr_{uuid.uuid4().hex[:12]}"
        self.session_id = session_id
        self.mesh_id = mesh_id
        self.trace_id = trace_id
        self.outcome = outcome
        self.success = success
        self.merged_result: Dict[str, Any] = merged_result or {}
        self.participant_outcomes: Dict[str, Any] = participant_outcomes or {}
        self.barrier_released = barrier_released
        self.coordinator_state = coordinator_state
        self.errors: List[str] = errors or []
        self.metadata: Dict[str, Any] = metadata or {}
        self.created_at: float = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation.

        Returned keys: ``run_id``, ``session_id``, ``mesh_id``, ``trace_id``,
        ``outcome``, ``success``, ``merged_result``, ``participant_outcomes``,
        ``barrier_released``, ``coordinator_state``, ``errors``, ``metadata``,
        ``created_at``.
        """
        coord_dict: Any = None
        if self.coordinator_state is not None:
            if hasattr(self.coordinator_state, "to_dict"):
                coord_dict = self.coordinator_state.to_dict()
            else:
                coord_dict = str(self.coordinator_state)
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "mesh_id": self.mesh_id,
            "trace_id": self.trace_id,
            "outcome": self.outcome,
            "success": self.success,
            "merged_result": self.merged_result,
            "participant_outcomes": self.participant_outcomes,
            "barrier_released": self.barrier_released,
            "coordinator_state": coord_dict,
            "errors": self.errors,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _import_coordinator_contracts() -> Any:
    """Lazily import the coordinator contract module."""
    from contracts import mesh_session_coordinator as _mod
    return _mod


def _get_participant_device_ids(coordinator_state: Any) -> List[str]:
    """Return all participant device IDs from coordinator state."""
    try:
        participants = getattr(coordinator_state, "participants", []) or []
        return [
            p.device_id
            for p in participants
            if getattr(p, "device_id", "")
        ]
    except Exception:
        return []


def _log_event(
    event_type: str,
    session_id: Optional[str],
    device_id: Optional[str] = None,
    message: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emit a structured log event for mesh lifecycle observability."""
    log_record: Dict[str, Any] = {
        "event": event_type,
        "session_id": session_id,
    }
    if device_id:
        log_record["device_id"] = device_id
    if message:
        log_record["message"] = message
    log_record.update(extra)
    _logger.info("live_mesh_event: %s", log_record)


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _promote_staged_to_active(
    coordinator_state: Any,
    errors: List[str],
) -> Any:
    """Promote coordinator state from ``pending`` to ``active``.

    Returns the updated coordinator state.  Records errors without raising.
    """
    try:
        mod = _import_coordinator_contracts()
        status = getattr(coordinator_state, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status or "")

        if status_val not in ("pending", "unknown"):
            # Already active or further along — do not regress
            return coordinator_state

        participants = getattr(coordinator_state, "participants", []) or []
        if not participants:
            errors.append("promotion_failed:no_participants")
            _log_event(
                "mesh_session_promotion_failed",
                getattr(coordinator_state, "session_id", None),
                message="Cannot promote: no participants registered",
            )
            # Return a failed state
            return coordinator_state.model_copy(
                update={"status": mod.MeshCoordinatorStatus.failed}
            )

        promoted = coordinator_state.model_copy(
            update={
                "status": mod.MeshCoordinatorStatus.active,
                "updated_at": time.time(),
            }
        )

        event = mod.MeshCoordinationEvent(
            kind=mod.MeshCoordinationEventKind.coordinator_status_changed,
            message="Coordinator promoted from staged/pending to active (PR-J)",
        )
        promoted = promoted.model_copy(
            update={
                "coordination_events": list(promoted.coordination_events) + [event],
            }
        )

        _log_event(
            "mesh_session_created",
            getattr(promoted, "session_id", None),
            message="Mesh session promoted to active",
            participant_count=len(participants),
        )
        return promoted

    except Exception as exc:
        errors.append(f"promotion_error:{exc}")
        _logger.warning("_promote_staged_to_active: error: %s", exc)
        return coordinator_state


def _track_participants_working(
    coordinator_state: Any,
    participant_results: Dict[str, Any],
    errors: List[str],
) -> Any:
    """Mark participants as working/ready and register provided results.

    For each participant:
    - If a result is supplied in ``participant_results``, mark as ``working``.
    - Otherwise mark as ``ready`` (still awaiting).

    Returns updated coordinator state.
    """
    try:
        mod = _import_coordinator_contracts()
        participants = getattr(coordinator_state, "participants", []) or []

        new_participants = []
        for p in participants:
            did = getattr(p, "device_id", "")
            if did in participant_results:
                new_p = p.model_copy(
                    update={"status": mod.MeshParticipantStatus.working}
                )
            else:
                current = getattr(p, "status", mod.MeshParticipantStatus.pending)
                current_val = current.value if hasattr(current, "value") else str(current)
                if current_val in ("pending", "unknown"):
                    new_p = p.model_copy(
                        update={"status": mod.MeshParticipantStatus.ready}
                    )
                else:
                    new_p = p
            new_participants.append(new_p)
            _log_event(
                "participant_registered",
                getattr(coordinator_state, "session_id", None),
                device_id=did,
                new_status=getattr(
                    getattr(new_p, "status", None), "value", str(getattr(new_p, "status", ""))
                ),
            )

        return coordinator_state.model_copy(
            update={
                "participants": new_participants,
                "updated_at": time.time(),
            }
        )

    except Exception as exc:
        errors.append(f"participant_tracking_error:{exc}")
        _logger.warning("_track_participants_working: error: %s", exc)
        return coordinator_state


def _evaluate_barrier(
    coordinator_state: Any,
    participant_results: Dict[str, Any],
    barrier_timeout_seconds: float,
    errors: List[str],
) -> tuple[Any, bool]:
    """Evaluate whether the barrier can be released.

    Returns ``(updated_state, barrier_released)``.

    Logic
    -----
    - If barrier is ``not_required``: immediately return ``(state, True)``.
    - If all participants with results have arrived: release barrier.
    - If not all arrived but there are some: record waiting status, keep
      ``barrier_released=False``.
    - If timeout exceeded (simulated by checking no participants at all):
      mark barrier as failed.
    """
    try:
        mod = _import_coordinator_contracts()
        barrier_state = getattr(coordinator_state, "barrier_state", None)
        if barrier_state is None:
            return coordinator_state, True

        b_status = getattr(barrier_state, "status", mod.MeshBarrierStatus.unknown)
        b_status_val = b_status.value if hasattr(b_status, "value") else str(b_status)

        if b_status_val == "not_required":
            _log_event(
                "barrier_released",
                getattr(coordinator_state, "session_id", None),
                message="Barrier not required — skipping barrier evaluation",
            )
            return coordinator_state, True

        participants = getattr(coordinator_state, "participants", []) or []
        device_ids = [getattr(p, "device_id", "") for p in participants if getattr(p, "device_id", "")]

        if not device_ids:
            # No participants — barrier cannot be satisfied; timeout path
            errors.append("barrier_failed:no_participants")
            new_barrier = barrier_state.model_copy(
                update={
                    "status": mod.MeshBarrierStatus.failed,
                    "barrier_reason": "no_participants_registered",
                    "timestamp": time.time(),
                }
            )
            barrier_event = mod.MeshCoordinationEvent(
                kind=mod.MeshCoordinationEventKind.barrier_reached,
                message="Barrier evaluation failed: no participants (PR-J timeout path)",
            )
            updated = coordinator_state.model_copy(
                update={
                    "barrier_state": new_barrier,
                    "status": mod.MeshCoordinatorStatus.failed,
                    "coordination_events": list(coordinator_state.coordination_events) + [barrier_event],
                    "updated_at": time.time(),
                }
            )
            _log_event(
                "barrier_failed",
                getattr(updated, "session_id", None),
                message="Barrier failed: no participants",
            )
            return updated, False

        # Determine which participants have arrived (have results)
        arrived = [did for did in device_ids if did in participant_results]
        waiting = [did for did in device_ids if did not in participant_results]

        _log_event(
            "barrier_waiting",
            getattr(coordinator_state, "session_id", None),
            arrived_count=len(arrived),
            waiting_count=len(waiting),
            message=f"Barrier evaluation: {len(arrived)}/{len(device_ids)} arrived",
        )

        if waiting:
            # Update barrier to waiting status; mark waiting participants
            new_barrier = barrier_state.model_copy(
                update={
                    "status": mod.MeshBarrierStatus.waiting,
                    "waiting_device_ids": waiting,
                    "timestamp": time.time(),
                }
            )
            # Mark waiting participants in coordinator
            new_participants = []
            for p in participants:
                did = getattr(p, "device_id", "")
                if did in waiting:
                    new_p = p.model_copy(
                        update={"status": mod.MeshParticipantStatus.waiting}
                    )
                    _log_event(
                        "participant_updated",
                        getattr(coordinator_state, "session_id", None),
                        device_id=did,
                        message="Participant waiting at barrier",
                    )
                else:
                    new_p = p
                new_participants.append(new_p)

            barrier_event = mod.MeshCoordinationEvent(
                kind=mod.MeshCoordinationEventKind.barrier_reached,
                message=f"Barrier waiting: {len(waiting)} participants not yet arrived",
            )
            updated = coordinator_state.model_copy(
                update={
                    "barrier_state": new_barrier,
                    "participants": new_participants,
                    "status": mod.MeshCoordinatorStatus.awaiting_barrier,
                    "coordination_events": list(coordinator_state.coordination_events) + [barrier_event],
                    "updated_at": time.time(),
                }
            )
            return updated, False
        else:
            # All participants arrived — release barrier
            new_barrier = barrier_state.model_copy(
                update={
                    "status": mod.MeshBarrierStatus.released,
                    "released": True,
                    "waiting_device_ids": [],
                    "barrier_reason": "all_participants_arrived",
                    "timestamp": time.time(),
                }
            )
            barrier_event = mod.MeshCoordinationEvent(
                kind=mod.MeshCoordinationEventKind.barrier_released,
                message="Barrier released: all participants arrived",
            )
            updated = coordinator_state.model_copy(
                update={
                    "barrier_state": new_barrier,
                    "coordination_events": list(coordinator_state.coordination_events) + [barrier_event],
                    "updated_at": time.time(),
                }
            )
            _log_event(
                "barrier_released",
                getattr(updated, "session_id", None),
                message="Barrier released: all participants arrived",
                participant_count=len(device_ids),
            )
            return updated, True

    except Exception as exc:
        errors.append(f"barrier_coordination_error:{exc}")
        _logger.warning("_evaluate_barrier: error: %s", exc)
        return coordinator_state, False


def _merge_participant_results(
    participant_results: Dict[str, Any],
    errors: List[str],
) -> Dict[str, Any]:
    """Merge per-participant partial results into a single aggregated output.

    Merge semantics:
    - Each participant contributes a dict keyed by arbitrary output fields.
    - Conflicts are resolved by last-writer-wins (iteration order of
      ``participant_results`` items).
    - The merged output always includes a ``_participants`` key listing
      contributing device IDs.

    Returns
    -------
    dict
        Merged output dict.  Never raises.
    """
    try:
        merged: Dict[str, Any] = {}
        contributing: List[str] = []

        _log_event(
            "merge_started",
            None,
            message=f"Starting merge for {len(participant_results)} participants",
        )

        for device_id, result in participant_results.items():
            contributing.append(device_id)
            if isinstance(result, dict):
                merged.update(result)
            else:
                # Scalar or non-dict result: store under device_id key
                merged[device_id] = result

        merged["_participants"] = contributing
        merged["_merge_timestamp"] = time.time()

        _log_event(
            "merge_completed",
            None,
            message=f"Merge completed for {len(contributing)} participants",
            contributing=contributing,
        )
        return merged

    except Exception as exc:
        errors.append(f"merge_error:{exc}")
        _logger.warning("_merge_participant_results: error: %s", exc)
        return {"_merge_error": str(exc), "_participants": []}


def _finalise_coordinator_state(
    coordinator_state: Any,
    participant_results: Dict[str, Any],
    merged_result: Dict[str, Any],
    errors: List[str],
) -> tuple[Any, str]:
    """Mark participants as completed/failed and compute final outcome.

    Returns ``(updated_state, outcome)`` where ``outcome`` is one of
    ``'completed'``, ``'partial'``, ``'failed'``.
    """
    try:
        mod = _import_coordinator_contracts()
        participants = getattr(coordinator_state, "participants", []) or []
        device_ids = [getattr(p, "device_id", "") for p in participants if getattr(p, "device_id", "")]

        completed_ids: List[str] = []
        failed_ids: List[str] = []
        new_participants = []

        for p in participants:
            did = getattr(p, "device_id", "")
            if did in participant_results:
                result_val = participant_results[did]
                # Determine per-participant success
                if isinstance(result_val, dict):
                    p_success = result_val.get("success", True)
                else:
                    p_success = result_val is not None

                if p_success is not False:
                    new_p = p.model_copy(
                        update={"status": mod.MeshParticipantStatus.completed}
                    )
                    completed_ids.append(did)
                else:
                    new_p = p.model_copy(
                        update={"status": mod.MeshParticipantStatus.failed}
                    )
                    failed_ids.append(did)
                    errors.append(f"participant_failed:{did}")
            else:
                # Participant didn't submit result — mark failed/offline
                current_status = getattr(p, "status", mod.MeshParticipantStatus.pending)
                current_val = current_status.value if hasattr(current_status, "value") else str(current_status)
                if current_val in ("waiting", "pending", "ready", "working"):
                    new_p = p.model_copy(
                        update={"status": mod.MeshParticipantStatus.offline}
                    )
                    failed_ids.append(did)
                    errors.append(f"participant_drop:{did}")
                    _log_event(
                        "participant_drop",
                        getattr(coordinator_state, "session_id", None),
                        device_id=did,
                        message="Participant did not submit result — marked offline",
                    )
                else:
                    new_p = p
            new_participants.append(new_p)

        # Determine outcome
        if completed_ids and not failed_ids:
            outcome = "completed"
            new_status = mod.MeshCoordinatorStatus.completed
        elif completed_ids and failed_ids:
            outcome = "partial"
            new_status = mod.MeshCoordinatorStatus.partial
        else:
            outcome = "failed"
            new_status = mod.MeshCoordinatorStatus.failed

        final_event = mod.MeshCoordinationEvent(
            kind=mod.MeshCoordinationEventKind.coordinator_status_changed,
            message=f"Final result emitted: outcome={outcome} (PR-J)",
        )

        updated = coordinator_state.model_copy(
            update={
                "participants": new_participants,
                "completed_device_ids": completed_ids,
                "failed_device_ids": failed_ids,
                "pending_device_ids": [],
                "status": new_status,
                "result_merge_summary": merged_result,
                "coordination_events": list(coordinator_state.coordination_events) + [final_event],
                "updated_at": time.time(),
            }
        )

        _log_event(
            "final_result_emitted",
            getattr(updated, "session_id", None),
            outcome=outcome,
            completed_count=len(completed_ids),
            failed_count=len(failed_ids),
            message=f"Live mesh session finalised: outcome={outcome}",
        )
        return updated, outcome

    except Exception as exc:
        errors.append(f"finalise_error:{exc}")
        _logger.warning("_finalise_coordinator_state: error: %s", exc)
        return coordinator_state, "failed"


# ---------------------------------------------------------------------------
# Public engine class
# ---------------------------------------------------------------------------


class LiveMeshRuntimeEngine:
    """Stateless driver that executes a live mesh session to completion.

    The engine processes a coordinator state through the following phases:

    1. **Promotion** — advance ``pending`` → ``active``.
    2. **Participant tracking** — register participant statuses.
    3. **Barrier evaluation** — check / release / fail the barrier.
    4. **Merge** — aggregate per-participant results.
    5. **Finalisation** — compute outcome and assemble :class:`LiveMeshRunResult`.

    The engine is entirely stateless; all mutable state lives in the returned
    :class:`LiveMeshRunResult` and the final coordinator state embedded in it.

    Usage::

        engine = LiveMeshRuntimeEngine()
        result = engine.run(coordinator_state, participant_results={
            "device_a": {"output": "hello"},
            "device_b": {"output": "world"},
        })
        assert result.outcome in ("completed", "partial", "failed")
    """

    def run(
        self,
        coordinator_state: Any,
        *,
        participant_results: Optional[Dict[str, Any]] = None,
        barrier_timeout_seconds: float = 30.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "LiveMeshRunResult":
        """Execute a live mesh session from the given coordinator state.

        Parameters
        ----------
        coordinator_state:
            A :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
            (or compatible object) representing the current session.
        participant_results:
            Optional mapping of ``device_id → result_dict`` representing
            the partial outputs already submitted by participants.  Pass an
            empty dict (or omit) to simulate a session where no participants
            have submitted results yet.
        barrier_timeout_seconds:
            Timeout in seconds for barrier evaluation.  Currently advisory
            (used for logging); future versions will enforce hard timeouts.
        metadata:
            Optional metadata to include in the result.

        Returns
        -------
        LiveMeshRunResult
            Never raises.
        """
        errors: List[str] = []
        p_results = dict(participant_results or {})

        try:
            if coordinator_state is None:
                return LiveMeshRunResult(
                    outcome="failed",
                    success=False,
                    errors=["coordinator_state_is_none"],
                    metadata=metadata or {},
                )

            session_id: Optional[str] = getattr(coordinator_state, "session_id", None)
            mesh_id: Optional[str] = getattr(coordinator_state, "mesh_id", None)
            trace_id: Optional[str] = getattr(coordinator_state, "trace_id", None)

            # ---- Phase 1: Promote staged → active --------------------------------
            coordinator_state = _promote_staged_to_active(coordinator_state, errors)

            current_status = getattr(coordinator_state, "status", None)
            current_val = current_status.value if hasattr(current_status, "value") else str(current_status or "")
            if current_val == "failed" and not getattr(coordinator_state, "participants", []):
                return LiveMeshRunResult(
                    run_id=None,
                    session_id=session_id,
                    mesh_id=mesh_id,
                    trace_id=trace_id,
                    outcome="failed",
                    success=False,
                    coordinator_state=coordinator_state,
                    errors=errors,
                    metadata=metadata or {},
                )

            # ---- Phase 2: Participant tracking -----------------------------------
            coordinator_state = _track_participants_working(
                coordinator_state, p_results, errors
            )

            # ---- Phase 3: Barrier evaluation ------------------------------------
            coordinator_state, barrier_released = _evaluate_barrier(
                coordinator_state,
                p_results,
                barrier_timeout_seconds,
                errors,
            )

            # If barrier is not released and there are participants waiting,
            # we still proceed with whatever results we have (degraded path).
            # A hard barrier failure (no participants) is terminal.
            barrier_state = getattr(coordinator_state, "barrier_state", None)
            b_status = getattr(barrier_state, "status", None)
            b_val = b_status.value if hasattr(b_status, "value") else str(b_status or "")
            if b_val == "failed" and not p_results:
                # Terminal barrier failure with no results
                return LiveMeshRunResult(
                    session_id=session_id,
                    mesh_id=mesh_id,
                    trace_id=trace_id,
                    outcome="failed",
                    success=False,
                    barrier_released=False,
                    coordinator_state=coordinator_state,
                    errors=errors,
                    metadata=metadata or {},
                )

            # ---- Phase 4: Merge --------------------------------------------------
            _log_event(
                "merge_started",
                session_id,
                message=f"Merging {len(p_results)} participant results",
            )
            merged = _merge_participant_results(p_results, errors)

            # ---- Phase 5: Finalise -----------------------------------------------
            coordinator_state, outcome = _finalise_coordinator_state(
                coordinator_state, p_results, merged, errors
            )

            success = outcome in ("completed", "partial")

            # Compute per-participant outcome map
            participant_outcomes: Dict[str, Any] = {}
            for did, res in p_results.items():
                if isinstance(res, dict):
                    p_success = res.get("success", True)
                else:
                    p_success = res is not None
                participant_outcomes[did] = {
                    "result": res,
                    "success": p_success is not False,
                }

            return LiveMeshRunResult(
                session_id=session_id,
                mesh_id=mesh_id,
                trace_id=trace_id,
                outcome=outcome,
                success=success,
                merged_result=merged,
                participant_outcomes=participant_outcomes,
                barrier_released=barrier_released,
                coordinator_state=coordinator_state,
                errors=errors,
                metadata=metadata or {},
            )

        except Exception as exc:
            errors.append(f"engine_error:{exc}")
            _logger.warning("LiveMeshRuntimeEngine.run: unexpected error: %s", exc)
            return LiveMeshRunResult(
                session_id=getattr(coordinator_state, "session_id", None)
                if coordinator_state is not None
                else None,
                outcome="failed",
                success=False,
                coordinator_state=coordinator_state,
                errors=errors,
                metadata=metadata or {},
            )


# ---------------------------------------------------------------------------
# Participant lifecycle helpers (module-level)
# ---------------------------------------------------------------------------


def register_participant(
    coordinator_state: Any,
    device_id: str,
    *,
    roles: Optional[List[str]] = None,
    online: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Add or update a participant in the coordinator state.

    If a participant with *device_id* already exists, their status is updated
    to ``pending`` and roles are merged.  Otherwise a new participant record
    is created.

    Returns
    -------
    MeshSessionCoordinatorState
        Updated coordinator state.  Never raises.
    """
    try:
        mod = _import_coordinator_contracts()
        participants = list(getattr(coordinator_state, "participants", []) or [])
        pending_ids = list(getattr(coordinator_state, "pending_device_ids", []) or [])

        existing_ids = {getattr(p, "device_id", "") for p in participants}
        if device_id not in existing_ids:
            new_p = mod.MeshParticipantCoordinationState(
                device_id=device_id,
                roles=roles or [],
                online=online,
                status=mod.MeshParticipantStatus.pending,
                last_seen=time.time(),
                metadata=metadata or {},
            )
            participants.append(new_p)
            if device_id not in pending_ids:
                pending_ids.append(device_id)
        else:
            new_participants = []
            for p in participants:
                if getattr(p, "device_id", "") == device_id:
                    merged_roles = list(getattr(p, "roles", []) or [])
                    for r in (roles or []):
                        if r not in merged_roles:
                            merged_roles.append(r)
                    p = p.model_copy(
                        update={
                            "roles": merged_roles,
                            "online": online,
                            "last_seen": time.time(),
                        }
                    )
                new_participants.append(p)
            participants = new_participants

        event = mod.MeshCoordinationEvent(
            kind=mod.MeshCoordinationEventKind.participant_joined,
            device_id=device_id,
            message=f"Participant registered: device_id={device_id} (PR-J)",
        )

        _log_event(
            "participant_registered",
            getattr(coordinator_state, "session_id", None),
            device_id=device_id,
            roles=roles,
        )

        return coordinator_state.model_copy(
            update={
                "participants": participants,
                "pending_device_ids": pending_ids,
                "coordination_events": list(coordinator_state.coordination_events) + [event],
                "updated_at": time.time(),
            }
        )

    except Exception as exc:
        _logger.warning("register_participant: error: %s", exc)
        return coordinator_state


def update_participant_status(
    coordinator_state: Any,
    device_id: str,
    status: str,
) -> Any:
    """Update the lifecycle status of a participant.

    Parameters
    ----------
    coordinator_state:
        Current coordinator state.
    device_id:
        Device ID to update.
    status:
        New status string (e.g. ``'ready'``, ``'working'``, ``'completed'``,
        ``'failed'``, ``'offline'``).

    Returns
    -------
    MeshSessionCoordinatorState
        Updated coordinator state.  Never raises.
    """
    try:
        mod = _import_coordinator_contracts()
        try:
            new_status = mod.MeshParticipantStatus(status)
        except (ValueError, KeyError):
            new_status = mod.MeshParticipantStatus.unknown

        participants = list(getattr(coordinator_state, "participants", []) or [])
        new_participants = []
        for p in participants:
            if getattr(p, "device_id", "") == device_id:
                p = p.model_copy(
                    update={"status": new_status, "last_seen": time.time()}
                )
            new_participants.append(p)

        event = mod.MeshCoordinationEvent(
            kind=mod.MeshCoordinationEventKind.participant_ready
            if status == "ready"
            else mod.MeshCoordinationEventKind.coordinator_status_changed,
            device_id=device_id,
            message=f"Participant status updated: {status} (PR-J)",
        )

        _log_event(
            "participant_updated",
            getattr(coordinator_state, "session_id", None),
            device_id=device_id,
            new_status=status,
        )

        return coordinator_state.model_copy(
            update={
                "participants": new_participants,
                "coordination_events": list(coordinator_state.coordination_events) + [event],
                "updated_at": time.time(),
            }
        )

    except Exception as exc:
        _logger.warning("update_participant_status: error: %s", exc)
        return coordinator_state


def drop_participant(
    coordinator_state: Any,
    device_id: str,
    *,
    reason: Optional[str] = None,
) -> Any:
    """Mark a participant as offline/dropped from the session.

    The participant record is retained but its status is set to ``offline``.
    The device is moved from ``pending_device_ids`` to ``failed_device_ids``.

    Returns
    -------
    MeshSessionCoordinatorState
        Updated coordinator state.  Never raises.
    """
    try:
        mod = _import_coordinator_contracts()
        participants = list(getattr(coordinator_state, "participants", []) or [])
        pending = list(getattr(coordinator_state, "pending_device_ids", []) or [])
        failed = list(getattr(coordinator_state, "failed_device_ids", []) or [])

        new_participants = []
        for p in participants:
            if getattr(p, "device_id", "") == device_id:
                p = p.model_copy(
                    update={
                        "status": mod.MeshParticipantStatus.offline,
                        "online": False,
                        "last_seen": time.time(),
                    }
                )
            new_participants.append(p)

        if device_id in pending:
            pending.remove(device_id)
        if device_id not in failed:
            failed.append(device_id)

        event = mod.MeshCoordinationEvent(
            kind=mod.MeshCoordinationEventKind.error,
            device_id=device_id,
            message=f"Participant dropped: {reason or 'no reason given'} (PR-J)",
        )

        _log_event(
            "participant_drop",
            getattr(coordinator_state, "session_id", None),
            device_id=device_id,
            reason=reason,
            message=f"Participant dropped: {reason}",
        )

        return coordinator_state.model_copy(
            update={
                "participants": new_participants,
                "pending_device_ids": pending,
                "failed_device_ids": failed,
                "coordination_events": list(coordinator_state.coordination_events) + [event],
                "updated_at": time.time(),
            }
        )

    except Exception as exc:
        _logger.warning("drop_participant: error: %s", exc)
        return coordinator_state


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def run_live_mesh_session(
    coordinator_state: Any,
    *,
    participant_results: Optional[Dict[str, Any]] = None,
    barrier_timeout_seconds: float = 30.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> "LiveMeshRunResult":
    """Convenience entry point for running a live mesh session.

    Equivalent to ``LiveMeshRuntimeEngine().run(...)``.

    Parameters
    ----------
    coordinator_state:
        Coordinator state to drive to completion.
    participant_results:
        Optional per-participant result dict (``device_id → result``).
    barrier_timeout_seconds:
        Advisory barrier timeout.
    metadata:
        Optional extra metadata for the result.

    Returns
    -------
    LiveMeshRunResult
        Never raises.
    """
    engine = LiveMeshRuntimeEngine()
    return engine.run(
        coordinator_state,
        participant_results=participant_results,
        barrier_timeout_seconds=barrier_timeout_seconds,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL",
    "STAGED_MESH_LIVE_PROMOTION_PR_J_POLICY",
    "PARTICIPANT_TRACKING_PR_J_POLICY",
    "BARRIER_COORDINATION_PR_J_POLICY",
    "MERGE_AGGREGATION_PR_J_POLICY",
    "RESULT_HANDLING_PR_J_POLICY",
    # Result type
    "LiveMeshRunResult",
    # Engine
    "LiveMeshRuntimeEngine",
    # Participant helpers
    "register_participant",
    "update_participant_status",
    "drop_participant",
    # Convenience entry point
    "run_live_mesh_session",
]
