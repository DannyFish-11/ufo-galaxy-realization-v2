"""core/mesh/live_mesh_session_coordinator.py
==============================================
Live MeshSession Coordinator — incremental event-driven runtime driver.

This module implements :class:`LiveMeshSessionCoordinator`: the stateful,
event-driven runtime driver that advances a :class:`MeshSession` through its
full lifecycle by accepting participant events one at a time rather than
requiring a pre-collected batch of results.

Relationship to the batch engine
---------------------------------
:class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRuntimeEngine` is the
*batch* processor — given a snapshot of all participant results, it processes
them in one shot and returns a :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`.

:class:`LiveMeshSessionCoordinator` is the *live* layer — it wraps the
coordinator state, accepts incremental participant events (ready, working,
result, failure, dropout), tracks barrier progression after each event, and
can be finalised at any time to produce a :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`
that reflects the current accumulated state.

Design principles
-----------------
- **Event-driven** — participant state is driven by explicit runtime events,
  not pre-collected batch data.
- **Barrier-aware** — the coordinator evaluates barrier readiness after every
  result event so that merge and completion can begin as soon as all active
  participants have contributed.
- **Thread-safe** — all state mutations are protected by a
  :class:`threading.Lock`.
- **Graceful degradation** — every method returns without raising; errors are
  recorded and surfaced in the final result.
- **Additive only** — does not modify any existing module; builds on
  :mod:`core.mesh.live_mesh_runtime_engine` and
  :mod:`contracts.mesh_session_coordinator`.

Sentinels
---------
:data:`LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL`
    Asserts this module is the live/incremental coordinator for PR-J.
:data:`INCREMENTAL_PARTICIPANT_EVENTS_PR_J_POLICY`
    Policy: participant events MUST drive coordinator state one at a time.
:data:`BARRIER_TRACKS_ACROSS_EVENTS_PR_J_POLICY`
    Policy: barrier status MUST be re-evaluated after each result event.
:data:`COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J_POLICY`
    Policy: finalize() MUST always produce a stable LiveMeshRunResult.

Usage::

    from core.mesh.live_mesh_session_coordinator import LiveMeshSessionCoordinator
    from contracts.mesh_session_coordinator import (
        build_mesh_session_coordinator,
    )

    # Build the initial coordinator state
    state = build_mesh_session_coordinator(
        session_id="session_123",
        mesh_id="mesh_456",
    )

    # Create the live coordinator
    coordinator = LiveMeshSessionCoordinator(state)

    # Register participants
    coordinator.add_participant("device_a", roles=["primary"])
    coordinator.add_participant("device_b", roles=["support"])

    # Drive participant lifecycle via runtime events
    coordinator.on_participant_ready("device_a")
    coordinator.on_participant_working("device_a")
    coordinator.on_participant_result("device_a", {"output": "hello"})

    coordinator.on_participant_ready("device_b")
    coordinator.on_participant_working("device_b")
    coordinator.on_participant_result("device_b", {"output": "world"})

    # Finalize and get the result
    result = coordinator.finalize()
    assert result.outcome == "completed"
    assert result.success is True

See ``docs/LIVE_MESH_SESSION_COORDINATOR.md`` for the full specification.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-J authority sentinels
# ---------------------------------------------------------------------------

LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL: str = (
    "SENTINEL::LIVE_MESH_SESSION_COORDINATOR_PR_J: "
    "live/incremental MeshSession coordinator that drives participant lifecycle "
    "via runtime events rather than batch pre-collected results; "
    "package=PR-J::live-mesh-session-coordinator-incremental-event-driver"
)

INCREMENTAL_PARTICIPANT_EVENTS_PR_J_POLICY: str = (
    "POLICY::INCREMENTAL_PARTICIPANT_EVENTS_PR_J: "
    "Participant state MUST be driven by explicit runtime events "
    "(on_participant_ready, on_participant_working, on_participant_result, "
    "on_participant_failed, on_participant_dropped) rather than batch "
    "pre-collection.  Each event MUST update the coordinator state and "
    "emit a structured log event for observability."
)

BARRIER_TRACKS_ACROSS_EVENTS_PR_J_POLICY: str = (
    "POLICY::BARRIER_TRACKS_ACROSS_EVENTS_PR_J: "
    "After every on_participant_result call the coordinator MUST re-evaluate "
    "whether all active participants have contributed.  When the last expected "
    "participant result arrives the barrier MUST transition from 'waiting' or "
    "'open' to 'released' and the coordinator status MUST advance to "
    "'merging' in preparation for finalisation."
)

COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J_POLICY: str = (
    "POLICY::COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J: "
    "finalize() MUST always produce a stable LiveMeshRunResult regardless of "
    "how many participants have completed, failed, or dropped.  An empty "
    "coordinator (no results at all) MUST produce outcome='failed'.  At least "
    "one completed participant MUST produce outcome='partial' or 'completed'."
)

PARTICIPANT_DROPOUT_AFFECTS_OUTCOME_PR_J_POLICY: str = (
    "POLICY::PARTICIPANT_DROPOUT_AFFECTS_OUTCOME_PR_J: "
    "When a participant is dropped via on_participant_dropped(), it MUST be "
    "counted as failed for the purposes of final outcome determination.  If "
    "the only remaining active participant drops, the session MUST resolve to "
    "outcome='failed' rather than blocking indefinitely."
)


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------


def _import_engine() -> Any:
    """Lazily import the live mesh runtime engine module."""
    from core.mesh import live_mesh_runtime_engine as _mod

    return _mod


def _import_coordinator_contracts() -> Any:
    """Lazily import the coordinator contract module."""
    from contracts import mesh_session_coordinator as _mod

    return _mod


# ---------------------------------------------------------------------------
# LiveMeshSessionCoordinator
# ---------------------------------------------------------------------------


class LiveMeshSessionCoordinator:
    """Stateful, event-driven coordinator that drives a MeshSession to completion.

    This coordinator accepts incremental participant lifecycle events — one at
    a time — and tracks barrier state, partial results, and session health
    continuously.  It can be finalised at any time to produce a
    :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`.

    Thread safety
    -------------
    All public methods acquire :attr:`_lock` before mutating state.  Callers
    may safely emit events from multiple threads simultaneously.

    Parameters
    ----------
    coordinator_state:
        Initial :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`.
        May be ``None``; the coordinator will create an empty state and
        immediately mark the result as failed on finalisation.
    barrier_timeout_seconds:
        Advisory barrier timeout.  Passed through to the batch engine on
        finalisation.
    metadata:
        Optional metadata dict propagated to the final result.
    """

    def __init__(
        self,
        coordinator_state: Any,
        *,
        barrier_timeout_seconds: float = 30.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._state: Any = coordinator_state
        self._barrier_timeout_seconds: float = barrier_timeout_seconds
        self._metadata: Dict[str, Any] = dict(metadata or {})
        self._partial_results: Dict[str, Any] = {}
        self._lock: threading.Lock = threading.Lock()
        self._finalized: bool = False
        self._errors: List[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> Any:
        """Current coordinator state (immutable snapshot, thread-safe)."""
        with self._lock:
            return self._state

    @property
    def partial_results(self) -> Dict[str, Any]:
        """Copy of accumulated partial results keyed by device_id."""
        with self._lock:
            return dict(self._partial_results)

    @property
    def is_complete(self) -> bool:
        """True when all registered participants have contributed or dropped.

        A coordinator with no participants is *not* considered complete; the
        caller must explicitly call :meth:`finalize` to obtain the final result.
        """
        with self._lock:
            return self._is_complete_unlocked()

    def _is_complete_unlocked(self) -> bool:
        """Non-locking implementation of is_complete."""
        try:
            participants = getattr(self._state, "participants", []) or []
            if not participants:
                return False
            device_ids = [getattr(p, "device_id", "") for p in participants if getattr(p, "device_id", "")]
            if not device_ids:
                return False
            # A participant is accounted-for if we have a result OR the
            # participant is already marked offline/failed in the state.
            mod = _import_coordinator_contracts()
            failed_statuses = {
                mod.MeshParticipantStatus.offline.value,
                mod.MeshParticipantStatus.failed.value,
            }
            for p in participants:
                did = getattr(p, "device_id", "")
                if not did:
                    continue
                status_obj = getattr(p, "status", None)
                status_val = status_obj.value if hasattr(status_obj, "value") else str(status_obj or "")
                if did not in self._partial_results and status_val not in failed_statuses:
                    return False
            return True
        except Exception:
            return False

    @property
    def outcome(self) -> str:
        """Current outcome string.

        Returns
        -------
        str
            ``'running'`` while the session is still in progress; ``'completed'``,
            ``'partial'``, or ``'failed'`` once all participants are accounted
            for or the coordinator is finalised.
        """
        with self._lock:
            if not self._is_complete_unlocked():
                return "running"
            return self._compute_outcome_unlocked()

    def _compute_outcome_unlocked(self) -> str:
        """Determine current outcome without acquiring the lock."""
        try:
            participants = getattr(self._state, "participants", []) or []
            completed_count = 0
            failed_count = 0
            for p in participants:
                did = getattr(p, "device_id", "")
                if not did:
                    continue
                if did in self._partial_results:
                    res = self._partial_results[did]
                    if isinstance(res, dict):
                        p_success = res.get("success", True)
                    else:
                        p_success = res is not None
                    if p_success is not False:
                        completed_count += 1
                    else:
                        failed_count += 1
                else:
                    # Not in results → must be failed/offline (checked by
                    # _is_complete_unlocked)
                    failed_count += 1
            if completed_count > 0 and failed_count == 0:
                return "completed"
            if completed_count > 0 and failed_count > 0:
                return "partial"
            return "failed"
        except Exception:
            return "failed"

    # ------------------------------------------------------------------
    # Participant management
    # ------------------------------------------------------------------

    def add_participant(
        self,
        device_id: str,
        *,
        roles: Optional[List[str]] = None,
        online: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a new participant or update an existing one.

        Delegates to :func:`~core.mesh.live_mesh_runtime_engine.register_participant`.

        Parameters
        ----------
        device_id:
            Unique device identifier.
        roles:
            Optional list of role strings (e.g. ``['primary']``).
        online:
            Whether the participant is currently online.
        metadata:
            Optional per-participant metadata.
        """
        with self._lock:
            try:
                engine = _import_engine()
                self._state = engine.register_participant(
                    self._state,
                    device_id,
                    roles=roles,
                    online=online,
                    metadata=metadata,
                )
                _logger.info(
                    "live_coordinator_event: participant_added session_id=%s device_id=%s",
                    getattr(self._state, "session_id", None),
                    device_id,
                )
            except Exception as exc:
                self._errors.append(f"add_participant_error:{device_id}:{exc}")
                _logger.warning("LiveMeshSessionCoordinator.add_participant: %s", exc)

    # ------------------------------------------------------------------
    # Participant lifecycle event handlers
    # ------------------------------------------------------------------

    def on_participant_ready(self, device_id: str) -> None:
        """Signal that a participant has become ready to work.

        Transitions the participant from ``pending`` → ``ready`` and emits a
        ``participant_ready`` coordination event.

        Parameters
        ----------
        device_id:
            The device that is now ready.
        """
        with self._lock:
            try:
                engine = _import_engine()
                self._state = engine.update_participant_status(self._state, device_id, "ready")
                _logger.info(
                    "live_coordinator_event: participant_ready session_id=%s device_id=%s",
                    getattr(self._state, "session_id", None),
                    device_id,
                )
            except Exception as exc:
                self._errors.append(f"on_participant_ready_error:{device_id}:{exc}")
                _logger.warning(
                    "LiveMeshSessionCoordinator.on_participant_ready [%s]: %s",
                    device_id,
                    exc,
                )

    def on_participant_working(self, device_id: str) -> None:
        """Signal that a participant has started working on its subtask.

        Transitions the participant to ``working``.

        Parameters
        ----------
        device_id:
            The device that is now working.
        """
        with self._lock:
            try:
                engine = _import_engine()
                self._state = engine.update_participant_status(self._state, device_id, "working")
                _logger.info(
                    "live_coordinator_event: participant_working session_id=%s device_id=%s",
                    getattr(self._state, "session_id", None),
                    device_id,
                )
            except Exception as exc:
                self._errors.append(f"on_participant_working_error:{device_id}:{exc}")
                _logger.warning(
                    "LiveMeshSessionCoordinator.on_participant_working [%s]: %s",
                    device_id,
                    exc,
                )

    def on_participant_result(
        self,
        device_id: str,
        result: Any,
    ) -> None:
        """Submit a result from a participant and re-evaluate barrier readiness.

        This is the primary progression driver.  After storing the result the
        coordinator:

        1. Marks the participant as ``completed`` in the coordinator state.
        2. Re-evaluates whether all active participants have submitted results.
        3. If all participants are now accounted for, marks the barrier as
           ``released`` and advances the coordinator status to ``merging``.

        Parameters
        ----------
        device_id:
            The device submitting the result.
        result:
            The result payload.  Typically a dict; other values are stored
            as-is.
        """
        with self._lock:
            try:
                self._partial_results[device_id] = result
                engine = _import_engine()
                self._state = engine.update_participant_status(self._state, device_id, "completed")
                _logger.info(
                    "live_coordinator_event: participant_result session_id=%s device_id=%s",
                    getattr(self._state, "session_id", None),
                    device_id,
                )
                # Re-evaluate barrier after each result
                self._try_advance_barrier_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_result_error:{device_id}:{exc}")
                _logger.warning(
                    "LiveMeshSessionCoordinator.on_participant_result [%s]: %s",
                    device_id,
                    exc,
                )

    def on_participant_failed(
        self,
        device_id: str,
        *,
        reason: str = "",
    ) -> None:
        """Signal that a participant has failed its subtask.

        The participant is marked as ``failed``.  If the failure means no
        remaining active participants can complete, the coordinator
        re-evaluates the barrier and may resolve to a ``failed`` or
        ``partial`` outcome.

        Parameters
        ----------
        device_id:
            The device that failed.
        reason:
            Optional human-readable failure reason.
        """
        with self._lock:
            try:
                engine = _import_engine()
                self._state = engine.update_participant_status(self._state, device_id, "failed")
                self._errors.append(f"participant_failed:{device_id}:{reason}")
                _logger.info(
                    "live_coordinator_event: participant_failed session_id=%s " "device_id=%s reason=%s",
                    getattr(self._state, "session_id", None),
                    device_id,
                    reason,
                )
                self._try_advance_barrier_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_failed_error:{device_id}:{exc}")
                _logger.warning(
                    "LiveMeshSessionCoordinator.on_participant_failed [%s]: %s",
                    device_id,
                    exc,
                )

    def on_participant_dropped(
        self,
        device_id: str,
        *,
        reason: str = "",
    ) -> None:
        """Drop a participant from the session (e.g. timeout, disconnect).

        The participant is marked as ``offline`` and removed from the pending
        set.  The coordinator re-evaluates whether the remaining participants
        are sufficient to make progress.

        Parameters
        ----------
        device_id:
            The device to drop.
        reason:
            Optional reason string (e.g. ``'timeout'``, ``'disconnect'``).
        """
        with self._lock:
            try:
                engine = _import_engine()
                self._state = engine.drop_participant(self._state, device_id, reason=reason or "dropped_by_coordinator")
                _logger.info(
                    "live_coordinator_event: participant_dropped session_id=%s " "device_id=%s reason=%s",
                    getattr(self._state, "session_id", None),
                    device_id,
                    reason,
                )
                self._try_advance_barrier_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_dropped_error:{device_id}:{exc}")
                _logger.warning(
                    "LiveMeshSessionCoordinator.on_participant_dropped [%s]: %s",
                    device_id,
                    exc,
                )

    # ------------------------------------------------------------------
    # Internal barrier tracking
    # ------------------------------------------------------------------

    def _try_advance_barrier_unlocked(self) -> None:
        """Re-evaluate whether all participants are accounted for.

        Called without the lock held (caller holds it).  When all active
        participants have either submitted a result, failed, or been dropped,
        the coordinator advances to the ``merging`` phase.
        """
        try:
            if not self._is_complete_unlocked():
                return
            # All participants are accounted for — advance to merging
            mod = _import_coordinator_contracts()
            current_status = getattr(self._state, "status", None)
            current_val = current_status.value if hasattr(current_status, "value") else str(current_status or "")
            if current_val in ("completed", "partial", "failed", "merging"):
                # Already at or past merging — nothing to do
                return

            event = mod.MeshCoordinationEvent(
                kind=mod.MeshCoordinationEventKind.barrier_released,
                message="All participants accounted — advancing to merging (PR-J live coordinator)",
            )
            self._state = self._state.model_copy(
                update={
                    "status": mod.MeshCoordinatorStatus.merging,
                    "coordination_events": list(self._state.coordination_events) + [event],
                    "updated_at": time.time(),
                }
            )
            _logger.info(
                "live_coordinator_event: advancing_to_merging session_id=%s",
                getattr(self._state, "session_id", None),
            )
        except Exception as exc:
            self._errors.append(f"try_advance_barrier_error:{exc}")
            _logger.warning("LiveMeshSessionCoordinator._try_advance_barrier_unlocked: %s", exc)

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------

    def finalize(
        self,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Finalise the live session and return a :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`.

        This method passes the accumulated partial results and current
        coordinator state to the batch
        :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRuntimeEngine`
        to produce the final authoritative result.

        Calling ``finalize()`` does not prevent further event emission; it
        captures a stable snapshot of the current state.

        Parameters
        ----------
        metadata:
            Optional extra metadata to include in the result.

        Returns
        -------
        LiveMeshRunResult
            Never raises.
        """
        with self._lock:
            snapshot_state = self._state
            snapshot_results = dict(self._partial_results)
            accumulated_errors = list(self._errors)
            merged_metadata = dict(self._metadata)
            if metadata:
                merged_metadata.update(metadata)

        try:
            engine_mod = _import_engine()
            result = engine_mod.run_live_mesh_session(
                snapshot_state,
                participant_results=snapshot_results,
                barrier_timeout_seconds=self._barrier_timeout_seconds,
                metadata=merged_metadata,
            )
            # Propagate any coordinator-level errors into the result
            if accumulated_errors and hasattr(result, "errors"):
                combined = list(result.errors) + [e for e in accumulated_errors if e not in result.errors]
                result.errors = combined
            return result
        except Exception as exc:
            _logger.warning("LiveMeshSessionCoordinator.finalize: %s", exc)
            try:
                engine_mod = _import_engine()
                return engine_mod.LiveMeshRunResult(
                    session_id=getattr(snapshot_state, "session_id", None),
                    outcome="failed",
                    success=False,
                    errors=accumulated_errors + [f"finalize_error:{exc}"],
                    metadata=merged_metadata,
                )
            except Exception:
                return None

    # ------------------------------------------------------------------
    # Convenience: build from a MeshSession contract dict/object
    # ------------------------------------------------------------------

    @classmethod
    def from_mesh_session(
        cls,
        mesh_session: Any,
        *,
        trace_id: Optional[str] = None,
        barrier_timeout_seconds: float = 30.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "LiveMeshSessionCoordinator":
        """Construct a :class:`LiveMeshSessionCoordinator` from a MeshSession.

        Parameters
        ----------
        mesh_session:
            A :class:`~contracts.mesh_session.MeshSession` or compatible dict.
        trace_id:
            Optional trace ID override.
        barrier_timeout_seconds:
            Advisory barrier timeout passed to the batch engine on
            finalisation.
        metadata:
            Optional metadata dict.

        Returns
        -------
        LiveMeshSessionCoordinator
            Never raises.  Returns a coordinator wrapping an empty state on
            error.
        """
        try:
            mod = _import_coordinator_contracts()
            state = mod.from_mesh_session(mesh_session, trace_id=trace_id)
            return cls(
                state,
                barrier_timeout_seconds=barrier_timeout_seconds,
                metadata=metadata,
            )
        except Exception as exc:
            _logger.warning("LiveMeshSessionCoordinator.from_mesh_session: %s", exc)
            try:
                mod = _import_coordinator_contracts()
                empty_state = mod.build_mesh_session_coordinator()
                return cls(
                    empty_state,
                    barrier_timeout_seconds=barrier_timeout_seconds,
                    metadata=metadata,
                )
            except Exception:
                return cls(
                    None,
                    barrier_timeout_seconds=barrier_timeout_seconds,
                    metadata=metadata,
                )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def create_live_mesh_session_coordinator(
    mesh_session: Any = None,
    *,
    session_id: Optional[str] = None,
    mesh_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    barrier_timeout_seconds: float = 30.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> LiveMeshSessionCoordinator:
    """Create a :class:`LiveMeshSessionCoordinator` from a mesh session or IDs.

    Parameters
    ----------
    mesh_session:
        Optional :class:`~contracts.mesh_session.MeshSession` or compatible
        dict to seed the coordinator state.
    session_id:
        Optional session ID (used when *mesh_session* is None).
    mesh_id:
        Optional mesh ID (used when *mesh_session* is None).
    trace_id:
        Optional trace ID override.
    barrier_timeout_seconds:
        Advisory barrier timeout in seconds.
    metadata:
        Optional metadata dict.

    Returns
    -------
    LiveMeshSessionCoordinator
        Never raises.
    """
    try:
        if mesh_session is not None:
            return LiveMeshSessionCoordinator.from_mesh_session(
                mesh_session,
                trace_id=trace_id,
                barrier_timeout_seconds=barrier_timeout_seconds,
                metadata=metadata,
            )
        mod = _import_coordinator_contracts()
        state = mod.build_mesh_session_coordinator(
            session_id=session_id,
            mesh_id=mesh_id,
            trace_id=trace_id,
            metadata=metadata or {},
        )
        return LiveMeshSessionCoordinator(
            state,
            barrier_timeout_seconds=barrier_timeout_seconds,
            metadata=metadata,
        )
    except Exception as exc:
        _logger.warning("create_live_mesh_session_coordinator: %s", exc)
        return LiveMeshSessionCoordinator(
            None,
            barrier_timeout_seconds=barrier_timeout_seconds,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL",
    "INCREMENTAL_PARTICIPANT_EVENTS_PR_J_POLICY",
    "BARRIER_TRACKS_ACROSS_EVENTS_PR_J_POLICY",
    "COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J_POLICY",
    "PARTICIPANT_DROPOUT_AFFECTS_OUTCOME_PR_J_POLICY",
    # Coordinator
    "LiveMeshSessionCoordinator",
    # Convenience
    "create_live_mesh_session_coordinator",
]
