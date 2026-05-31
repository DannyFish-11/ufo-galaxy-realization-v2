"""core/mesh/mesh_session_progression_driver.py
===============================================
Mesh Session Progression Driver — live coordinator that drives both
``MeshSession.status`` and ``MeshSubtaskAssignment.status`` transitions.

This module closes **MESH-002** from ``docs/DUAL_REPO_GAP_MATRIX.md``:

    *"MeshSessionStatus transitions are not driven by any live engine.
    subtask_assignments statuses are not updated from TaskGraphRuntime
    events."*

Relationship to existing engines
---------------------------------
:class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRuntimeEngine`
    Stateless batch engine: given a snapshot of all participant results,
    drives ``MeshSessionCoordinatorState`` to completion in one shot.

:class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`
    Stateful incremental coordinator: accepts participant lifecycle events
    one at a time, drives ``MeshSessionCoordinatorState``.

:class:`MeshSessionProgressionDriver` (this module)
    Stateful progression driver: wraps a ``MeshSession`` contract object
    together with a ``LiveMeshSessionCoordinator``.  Every participant
    lifecycle event updates **both** the coordinator state (via the
    inner ``LiveMeshSessionCoordinator``) **and** the ``MeshSession``
    object itself — advancing ``MeshSession.status`` and each
    ``MeshSubtaskAssignment.status`` in lock-step with coordinator
    progression.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Builds on existing contracts** — consumes
  :mod:`contracts.mesh_session` (``MeshSession``, ``MeshSessionStatus``,
  ``MeshSubtaskAssignment``) and
  :mod:`contracts.mesh_session_coordinator` without replacing them.
- **Thread-safe** — a single :class:`threading.Lock` guards all state
  mutations; callers may emit events from multiple threads.
- **Graceful degradation** — every public method returns without raising;
  errors are recorded and surfaced in the final
  :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`.
- **Observable** — every state transition emits a structured log event.

Sentinels
---------
:data:`MESH_SESSION_PROGRESSION_DRIVER_SENTINEL`
    Asserts this module is the live progression driver that closes MESH-002.
:data:`SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY`
    Policy: ``MeshSession.status`` MUST be driven by coordinator events.
:data:`SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY`
    Policy: each ``MeshSubtaskAssignment.status`` MUST be updated when the
    assigned device emits a result or failure event.
:data:`MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY`
    Policy: merge MUST be triggered automatically when the barrier is
    released (all participants accounted for).

Usage::

    from core.mesh.mesh_session_progression_driver import (
        MeshSessionProgressionDriver,
        create_progression_driver,
    )
    from contracts.mesh_session import build_mesh_session

    session = build_mesh_session(
        source_device_id="desktop",
        primary_device_id="desktop",
        mesh_id="mesh_alpha",
    )

    driver = MeshSessionProgressionDriver(session)
    driver.add_participant("device_a", roles=["primary"])
    driver.add_participant("device_b", roles=["support"])

    driver.on_participant_ready("device_a")
    driver.on_participant_working("device_a")
    driver.on_participant_result("device_a", {"output": "part_a"})

    driver.on_participant_ready("device_b")
    driver.on_participant_working("device_b")
    driver.on_participant_result("device_b", {"output": "part_b"})

    result = driver.finalize()
    assert result.outcome == "completed"
    assert driver.session.status.value == "completed"

See ``docs/LIVE_MESH_SESSION_COORDINATOR.md`` for the full specification.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

MESH_SESSION_PROGRESSION_DRIVER_SENTINEL: str = (
    "SENTINEL::MESH_SESSION_PROGRESSION_DRIVER: "
    "live progression driver that drives MeshSession.status AND "
    "MeshSubtaskAssignment.status via coordinator events; "
    "closes MESH-002 from docs/DUAL_REPO_GAP_MATRIX.md; "
    "package=mesh-session-progression-driver"
)

SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY: str = (
    "POLICY::SESSION_STATUS_DRIVEN_BY_COORDINATOR: "
    "MeshSession.status MUST advance in lock-step with coordinator "
    "progression.  When the coordinator enters 'active', the session "
    "MUST transition PENDING → ACTIVE.  When the coordinator enters "
    "'merging', the session MUST transition ACTIVE → MERGING.  When "
    "the coordinator enters 'completed'/'partial', the session MUST "
    "transition MERGING → COMPLETED.  When the coordinator fails, the "
    "session MUST transition to FAILED."
)

SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY: str = (
    "POLICY::SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT: "
    "Each MeshSubtaskAssignment whose device_id matches a participant "
    "MUST be updated when that participant emits on_participant_working "
    "('running'), on_participant_result ('success'), or "
    "on_participant_failed/on_participant_dropped ('failed').  The "
    "assignment status MUST NOT remain 'pending' after the participant "
    "has taken action."
)

MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY: str = (
    "POLICY::MERGE_TRIGGERED_WHEN_BARRIER_RELEASED: "
    "Merge MUST be triggered automatically when all active participants "
    "have submitted results (barrier released).  The session status "
    "MUST advance to MERGING before finalize() is called.  Callers "
    "MUST NOT need to manually trigger the merge step."
)


# ---------------------------------------------------------------------------
# Lazy import helpers
# ---------------------------------------------------------------------------


def _import_session_contracts() -> Any:
    """Lazily import contracts.mesh_session."""
    from contracts import mesh_session as _mod
    return _mod


def _import_live_coordinator() -> Any:
    """Lazily import LiveMeshSessionCoordinator."""
    from core.mesh.live_mesh_session_coordinator import LiveMeshSessionCoordinator
    return LiveMeshSessionCoordinator


def _import_coordinator_contracts() -> Any:
    """Lazily import contracts.mesh_session_coordinator."""
    from contracts import mesh_session_coordinator as _mod
    return _mod


# ---------------------------------------------------------------------------
# MeshSessionProgressionFinalResult
# ---------------------------------------------------------------------------


class MeshSessionProgressionFinalResult:
    """Final output of :meth:`MeshSessionProgressionDriver.finalize`.

    Attributes
    ----------
    session:
        The updated :class:`~contracts.mesh_session.MeshSession` with
        final ``status`` and ``subtask_assignments`` statuses.
    run_result:
        The :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`
        produced by the inner coordinator's batch engine.
    outcome:
        Convenience alias for ``run_result.outcome``.
    success:
        ``True`` for ``completed`` and ``partial`` outcomes.
    errors:
        List of accumulated error strings.
    """

    def __init__(
        self,
        *,
        session: Any,
        run_result: Any,
        errors: Optional[List[str]] = None,
    ) -> None:
        self.session = session
        self.run_result = run_result
        self.outcome: str = getattr(run_result, "outcome", "failed") if run_result is not None else "failed"
        self.success: bool = self.outcome in ("completed", "partial")
        self.errors: List[str] = list(errors or [])

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        session_dict = None
        if self.session is not None and hasattr(self.session, "to_dict"):
            session_dict = self.session.to_dict()
        run_dict = None
        if self.run_result is not None and hasattr(self.run_result, "to_dict"):
            run_dict = self.run_result.to_dict()
        return {
            "session": session_dict,
            "run_result": run_dict,
            "outcome": self.outcome,
            "success": self.success,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# MeshSessionProgressionDriver
# ---------------------------------------------------------------------------


class MeshSessionProgressionDriver:
    """Live progression driver that bridges ``MeshSession`` ↔ coordinator.

    This driver accepts incremental participant lifecycle events and updates
    both the inner :class:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator`
    **and** the ``MeshSession`` contract object:

    - ``MeshSession.status`` advances in lock-step with coordinator status.
    - ``MeshSubtaskAssignment.status`` is updated for each device whose
      assignment changes state.

    Thread safety
    -------------
    All public methods acquire :attr:`_lock` before mutating state.  Callers
    may safely emit events from multiple threads simultaneously.

    Parameters
    ----------
    mesh_session:
        A :class:`~contracts.mesh_session.MeshSession` or compatible dict.
        Pass ``None`` to construct in a degraded/no-op state.
    barrier_timeout_seconds:
        Advisory barrier timeout passed to the batch engine on finalisation.
    trace_id:
        Optional trace ID override for the inner coordinator.
    metadata:
        Optional metadata dict propagated to the final result.
    """

    def __init__(
        self,
        mesh_session: Any,
        *,
        barrier_timeout_seconds: float = 30.0,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._errors: List[str] = []
        self._barrier_timeout_seconds: float = barrier_timeout_seconds
        self._metadata: Dict[str, Any] = dict(metadata or {})

        # Normalise session: accept dict, MeshSession object, or None
        self._session: Any = self._normalise_session(mesh_session)

        # Build inner coordinator from the normalised session
        self._coordinator: Any = self._build_coordinator(
            self._session,
            trace_id=trace_id,
            barrier_timeout_seconds=barrier_timeout_seconds,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Internal initialisation helpers
    # ------------------------------------------------------------------

    def _normalise_session(self, mesh_session: Any) -> Any:
        """Return a MeshSession object, converting dicts as needed."""
        try:
            if mesh_session is None:
                return None
            mod = _import_session_contracts()
            if isinstance(mesh_session, mod.MeshSession):
                return mesh_session
            if isinstance(mesh_session, dict):
                return mod.MeshSession(**{
                    k: v for k, v in mesh_session.items()
                    if k in mod.MeshSession.model_fields
                })
            # Accept anything with a to_dict / model_dump surface
            if hasattr(mesh_session, "to_dict"):
                d = mesh_session.to_dict()
                return mod.MeshSession(**{
                    k: v for k, v in d.items()
                    if k in mod.MeshSession.model_fields
                })
            return mesh_session
        except Exception as exc:
            self._errors.append(f"normalise_session_error:{exc}")
            _logger.warning("MeshSessionProgressionDriver._normalise_session: %s", exc)
            return mesh_session

    def _build_coordinator(
        self,
        mesh_session: Any,
        *,
        trace_id: Optional[str],
        barrier_timeout_seconds: float,
        metadata: Optional[Dict[str, Any]],
    ) -> Any:
        """Construct the inner LiveMeshSessionCoordinator."""
        try:
            cls = _import_live_coordinator()
            return cls.from_mesh_session(
                mesh_session,
                trace_id=trace_id,
                barrier_timeout_seconds=barrier_timeout_seconds,
                metadata=metadata,
            )
        except Exception as exc:
            self._errors.append(f"build_coordinator_error:{exc}")
            _logger.warning("MeshSessionProgressionDriver._build_coordinator: %s", exc)
            try:
                cls = _import_live_coordinator()
                return cls(None, barrier_timeout_seconds=barrier_timeout_seconds)
            except Exception as exc:
                return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session(self) -> Any:
        """Current ``MeshSession`` snapshot (thread-safe read)."""
        with self._lock:
            return self._session

    @property
    def coordinator(self) -> Any:
        """Inner ``LiveMeshSessionCoordinator`` (thread-safe read)."""
        with self._lock:
            return self._coordinator

    @property
    def is_complete(self) -> bool:
        """True when all participants are accounted for."""
        with self._lock:
            if self._coordinator is None:
                return False
            return getattr(self._coordinator, "is_complete", False)

    @property
    def outcome(self) -> str:
        """Current outcome string (``'running'``, ``'completed'``, ``'partial'``, ``'failed'``)."""
        with self._lock:
            if self._coordinator is None:
                return "failed"
            return getattr(self._coordinator, "outcome", "failed")

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
        """Register a new participant.

        Delegates to the inner
        :meth:`~core.mesh.live_mesh_session_coordinator.LiveMeshSessionCoordinator.add_participant`.

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
                if self._coordinator is not None:
                    self._coordinator.add_participant(
                        device_id, roles=roles, online=online, metadata=metadata
                    )
                _logger.info(
                    "progression_driver_event: participant_added session=%s device=%s",
                    self._session_id_unlocked(),
                    device_id,
                )
            except Exception as exc:
                self._errors.append(f"add_participant_error:{device_id}:{exc}")
                _logger.warning("MeshSessionProgressionDriver.add_participant [%s]: %s", device_id, exc)

    # ------------------------------------------------------------------
    # Participant lifecycle event handlers
    # ------------------------------------------------------------------

    def on_participant_ready(self, device_id: str) -> None:
        """Signal that a participant is ready to work.

        Delegates to the inner coordinator.
        """
        with self._lock:
            try:
                if self._coordinator is not None:
                    self._coordinator.on_participant_ready(device_id)
            except Exception as exc:
                self._errors.append(f"on_participant_ready_error:{device_id}:{exc}")
                _logger.warning("MeshSessionProgressionDriver.on_participant_ready [%s]: %s", device_id, exc)

    def on_participant_working(self, device_id: str) -> None:
        """Signal that a participant has started executing its subtask.

        In addition to advancing the participant's coordinator status to
        ``working``, this method updates the corresponding
        :class:`~contracts.mesh_session.MeshSubtaskAssignment` (if any)
        to ``status='running'``.
        """
        with self._lock:
            try:
                if self._coordinator is not None:
                    self._coordinator.on_participant_working(device_id)
                self._update_assignment_status_unlocked(device_id, "running")
                self._advance_session_status_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_working_error:{device_id}:{exc}")
                _logger.warning("MeshSessionProgressionDriver.on_participant_working [%s]: %s", device_id, exc)

    def on_participant_result(
        self,
        device_id: str,
        result: Any,
    ) -> None:
        """Submit a participant result and re-evaluate barrier / session status.

        This is the primary progression driver.  After forwarding the result
        to the inner coordinator the driver:

        1. Updates the corresponding ``MeshSubtaskAssignment.status`` to
           ``'success'``.
        2. Re-evaluates ``MeshSession.status`` — advancing to ``MERGING``
           when all participants are accounted for.
        """
        with self._lock:
            try:
                if self._coordinator is not None:
                    self._coordinator.on_participant_result(device_id, result)
                self._update_assignment_status_unlocked(device_id, "success")
                self._advance_session_status_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_result_error:{device_id}:{exc}")
                _logger.warning("MeshSessionProgressionDriver.on_participant_result [%s]: %s", device_id, exc)

    def on_participant_failed(
        self,
        device_id: str,
        *,
        reason: str = "",
    ) -> None:
        """Signal that a participant has failed its subtask.

        Updates the corresponding ``MeshSubtaskAssignment.status`` to
        ``'failed'`` and re-evaluates the session status.
        """
        with self._lock:
            try:
                if self._coordinator is not None:
                    self._coordinator.on_participant_failed(device_id, reason=reason)
                self._update_assignment_status_unlocked(device_id, "failed")
                self._advance_session_status_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_failed_error:{device_id}:{exc}")
                _logger.warning("MeshSessionProgressionDriver.on_participant_failed [%s]: %s", device_id, exc)

    def on_participant_dropped(
        self,
        device_id: str,
        *,
        reason: str = "",
    ) -> None:
        """Drop a participant from the session (e.g. timeout, disconnect).

        Updates the corresponding ``MeshSubtaskAssignment.status`` to
        ``'failed'`` and re-evaluates the session status.
        """
        with self._lock:
            try:
                if self._coordinator is not None:
                    self._coordinator.on_participant_dropped(device_id, reason=reason)
                self._update_assignment_status_unlocked(device_id, "failed")
                self._advance_session_status_unlocked()
            except Exception as exc:
                self._errors.append(f"on_participant_dropped_error:{device_id}:{exc}")
                _logger.warning("MeshSessionProgressionDriver.on_participant_dropped [%s]: %s", device_id, exc)

    # ------------------------------------------------------------------
    # Internal state-advancement helpers  (caller holds _lock)
    # ------------------------------------------------------------------

    def _session_id_unlocked(self) -> Optional[str]:
        """Return session_id without acquiring the lock (caller holds it)."""
        if self._session is None:
            return None
        return getattr(self._session, "session_id", None)

    def _update_assignment_status_unlocked(
        self, device_id: str, status: str
    ) -> None:
        """Update ``MeshSubtaskAssignment.status`` for the given device."""
        try:
            if self._session is None:
                return
            assignments = getattr(self._session, "subtask_assignments", []) or []
            if not assignments:
                return
            new_assignments = []
            changed = False
            for a in assignments:
                a_device = getattr(a, "device_id", "")
                if a_device == device_id:
                    new_a = a.model_copy(update={"status": status})
                    new_assignments.append(new_a)
                    changed = True
                else:
                    new_assignments.append(a)
            if changed:
                self._session = self._session.model_copy(
                    update={
                        "subtask_assignments": new_assignments,
                        "updated_at": time.time(),
                    }
                )
                _logger.info(
                    "progression_driver_event: assignment_updated session=%s device=%s status=%s",
                    self._session_id_unlocked(),
                    device_id,
                    status,
                )
        except Exception as exc:
            self._errors.append(f"update_assignment_status_error:{device_id}:{exc}")
            _logger.warning(
                "MeshSessionProgressionDriver._update_assignment_status_unlocked [%s]: %s",
                device_id,
                exc,
            )

    def _advance_session_status_unlocked(self) -> None:
        """Advance ``MeshSession.status`` based on current coordination progress.

        Logic:
        - At least one participant working → session ``ACTIVE`` (from PENDING)
        - Coordinator ``merging`` status OR all participants accounted for →
          session ``MERGING``
        - Coordinator ``completed``/``partial`` → session ``COMPLETED``
        - Coordinator ``failed`` (and no pending/working participants left) →
          session ``FAILED``
        """
        try:
            if self._session is None:
                return

            mod_session = _import_session_contracts()
            current_session_status = getattr(
                self._session, "status", mod_session.MeshSessionStatus.UNKNOWN
            )
            current_val = (
                current_session_status.value
                if hasattr(current_session_status, "value")
                else str(current_session_status or "")
            )

            # Do not regress a terminal session status
            terminal_vals = {"completed", "failed", "cancelled"}
            if current_val in terminal_vals:
                return

            # Determine target based on coordinator + participant progress
            target: Optional[Any] = None

            # Check coordinator status (may jump to merging or failed)
            coord_state = None
            if self._coordinator is not None:
                # Access internal state directly (avoids lock recursion)
                coord_state = getattr(self._coordinator, "_state", None)
                if coord_state is None:
                    try:
                        coord_state = self._coordinator.state
                    except Exception as exc:
                        _logger.debug("Fallback triggered: %s", exc)
                        coord_state = None

            coord_val = ""
            if coord_state is not None:
                coord_status = getattr(coord_state, "status", None)
                coord_val = (
                    coord_status.value
                    if hasattr(coord_status, "value")
                    else str(coord_status or "")
                )

            # Check if any participants are actively working (for ACTIVE transition)
            has_active_participants = False
            if coord_state is not None:
                participants = getattr(coord_state, "participants", []) or []
                for p in participants:
                    p_status = getattr(p, "status", None)
                    p_val = (
                        p_status.value if hasattr(p_status, "value") else str(p_status or "")
                    )
                    if p_val in ("working", "ready", "completed", "waiting"):
                        has_active_participants = True
                        break

            # Also check if driver has any partial results yet
            coordinator_is_complete = False
            if self._coordinator is not None:
                try:
                    coordinator_is_complete = self._coordinator.is_complete
                except Exception as exc:
                    _logger.warning("Exception suppressed: %s", exc)

            # Priority: highest-status target wins
            if coord_val in ("completed", "partial") and current_val not in terminal_vals:
                target = mod_session.MeshSessionStatus.COMPLETED
            elif coord_val == "failed" and current_val not in terminal_vals:
                target = mod_session.MeshSessionStatus.FAILED
            elif coord_val == "merging" and current_val in ("pending", "active", "unknown"):
                target = mod_session.MeshSessionStatus.MERGING
            elif coordinator_is_complete and current_val in ("pending", "active", "unknown"):
                # All participants accounted for → transition to MERGING
                target = mod_session.MeshSessionStatus.MERGING
            elif has_active_participants and current_val in ("pending", "unknown"):
                target = mod_session.MeshSessionStatus.ACTIVE

            if target is None:
                return

            # Validate transition
            valid_map = getattr(mod_session, "MESH_SESSION_VALID_TRANSITIONS", {})
            allowed = valid_map.get(current_session_status, set())
            if target not in allowed:
                _logger.debug(
                    "progression_driver_event: skipping_invalid_transition "
                    "session=%s from=%s to=%s",
                    self._session_id_unlocked(),
                    current_val,
                    target.value if hasattr(target, "value") else str(target),
                )
                return

            self._session = self._session.model_copy(
                update={"status": target, "updated_at": time.time()}
            )
            _logger.info(
                "progression_driver_event: session_status_advanced session=%s "
                "from=%s to=%s coordinator_status=%s",
                self._session_id_unlocked(),
                current_val,
                target.value if hasattr(target, "value") else str(target),
                coord_val,
            )
        except Exception as exc:
            self._errors.append(f"advance_session_status_error:{exc}")
            _logger.warning(
                "MeshSessionProgressionDriver._advance_session_status_unlocked: %s", exc
            )

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------

    def finalize(
        self,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MeshSessionProgressionFinalResult:
        """Finalise the live session.

        Passes accumulated partial results to the batch engine and
        assembles the final ``MeshSession`` snapshot.  Returns a
        :class:`MeshSessionProgressionFinalResult` that carries both
        the updated :class:`~contracts.mesh_session.MeshSession` and
        the :class:`~core.mesh.live_mesh_runtime_engine.LiveMeshRunResult`.

        Calling :meth:`finalize` does not prevent further event emission;
        it captures a stable snapshot of the current state.

        Parameters
        ----------
        metadata:
            Optional extra metadata to include in the result.

        Returns
        -------
        MeshSessionProgressionFinalResult
            Never raises.
        """
        with self._lock:
            snapshot_session = self._session
            snapshot_errors = list(self._errors)
            merged_meta = dict(self._metadata)
            if metadata:
                merged_meta.update(metadata)
            coordinator = self._coordinator

        try:
            run_result = None
            if coordinator is not None:
                run_result = coordinator.finalize(metadata=merged_meta)

            # After finalize, advance session to its terminal status
            with self._lock:
                self._advance_session_status_from_run_result_unlocked(run_result)
                final_session = self._session

            # Propagate coordinator errors
            if run_result is not None and hasattr(run_result, "errors") and snapshot_errors:
                combined = list(run_result.errors) + [
                    e for e in snapshot_errors if e not in run_result.errors
                ]
                run_result.errors = combined

            return MeshSessionProgressionFinalResult(
                session=final_session,
                run_result=run_result,
                errors=snapshot_errors,
            )

        except Exception as exc:
            snapshot_errors.append(f"finalize_error:{exc}")
            _logger.warning("MeshSessionProgressionDriver.finalize: %s", exc)
            return MeshSessionProgressionFinalResult(
                session=snapshot_session,
                run_result=None,
                errors=snapshot_errors,
            )

    def _advance_session_status_from_run_result_unlocked(
        self, run_result: Any
    ) -> None:
        """Final session status update based on the run_result outcome."""
        try:
            if self._session is None or run_result is None:
                return
            mod_session = _import_session_contracts()
            outcome = getattr(run_result, "outcome", "failed")
            current = getattr(self._session, "status", None)
            current_val = current.value if hasattr(current, "value") else str(current or "")
            terminal_vals = {"completed", "failed", "cancelled"}
            if current_val in terminal_vals:
                return

            if outcome in ("completed", "partial"):
                target = mod_session.MeshSessionStatus.COMPLETED
            else:
                target = mod_session.MeshSessionStatus.FAILED

            valid_map = getattr(mod_session, "MESH_SESSION_VALID_TRANSITIONS", {})
            allowed = valid_map.get(current, set())
            if target not in allowed:
                return

            self._session = self._session.model_copy(
                update={"status": target, "updated_at": time.time()}
            )
            _logger.info(
                "progression_driver_event: session_finalized session=%s outcome=%s final_status=%s",
                self._session_id_unlocked(),
                outcome,
                target.value if hasattr(target, "value") else str(target),
            )
        except Exception as exc:
            self._errors.append(f"advance_from_run_result_error:{exc}")
            _logger.warning(
                "MeshSessionProgressionDriver._advance_session_status_from_run_result_unlocked: %s",
                exc,
            )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def create_progression_driver(
    mesh_session: Any = None,
    *,
    session_id: Optional[str] = None,
    mesh_id: Optional[str] = None,
    source_device_id: str = "",
    primary_device_id: str = "",
    barrier_timeout_seconds: float = 30.0,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MeshSessionProgressionDriver:
    """Convenience factory for :class:`MeshSessionProgressionDriver`.

    If *mesh_session* is ``None`` a minimal session is built from kwargs.

    Parameters
    ----------
    mesh_session:
        A :class:`~contracts.mesh_session.MeshSession` or compatible dict.
    session_id:
        Used when *mesh_session* is ``None``.
    mesh_id:
        Used when *mesh_session* is ``None``.
    source_device_id:
        Used when *mesh_session* is ``None``.
    primary_device_id:
        Used when *mesh_session* is ``None``.
    barrier_timeout_seconds:
        Advisory barrier timeout.
    trace_id:
        Optional trace ID override.
    metadata:
        Optional metadata dict.

    Returns
    -------
    MeshSessionProgressionDriver
        Never raises.
    """
    try:
        if mesh_session is None:
            mod = _import_session_contracts()
            mesh_session = mod.build_mesh_session(
                source_device_id=source_device_id or "unknown",
                primary_device_id=primary_device_id or "unknown",
                mesh_id=mesh_id,
                session_id=session_id,
            )
        return MeshSessionProgressionDriver(
            mesh_session,
            barrier_timeout_seconds=barrier_timeout_seconds,
            trace_id=trace_id,
            metadata=metadata,
        )
    except Exception as exc:
        _logger.warning("create_progression_driver: error: %s", exc)
        return MeshSessionProgressionDriver(
            None,
            barrier_timeout_seconds=barrier_timeout_seconds,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "MESH_SESSION_PROGRESSION_DRIVER_SENTINEL",
    "SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY",
    "SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY",
    "MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY",
    "MeshSessionProgressionFinalResult",
    "MeshSessionProgressionDriver",
    "create_progression_driver",
]
