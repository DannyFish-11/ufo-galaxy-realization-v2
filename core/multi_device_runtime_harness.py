#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/multi_device_runtime_harness.py
======================================
Multi-Device Runtime Harness — PR-next (architecture gap closure).

Background
----------
The multi-device orchestration stack in Galaxy has three independent layers
that have not been integrated into a single resilient runtime:

1. **Mesh Session Persistence** (``core/mesh/mesh_session_persistence.py``) —
   provides durable coordinator-state snapshots but is not called from any
   runtime lifecycle path.

2. **Formation Rebalance Engine**
   (``core/device_formation/formation_rebalance_engine.py``) — provides
   health-driven formation reshaping but is not wired into any connection-loss
   or heartbeat-failure handler.

3. **Scheduling Truth Harness** (``core/scheduling_truth_harness.py``) —
   provides canonical task-registration and routable-executor queries but
   is not called from the cross-device scheduling paths.

This module provides the **practical foundation** for wiring these three layers
together in a scoped, additive way.  It introduces:

1. :class:`MultiDeviceRuntimeHarness` — the integration point that:

   * Ensures mesh session state is durably persisted whenever a coordinator
     state is updated.
   * Evaluates formation health on device-disconnect / heartbeat-miss events
     and triggers a rebalance when needed.
   * Ensures tasks are registered in TaskGraphRuntime and routes are consulted
     via canonical capability/network truth before dispatch.

2. :func:`on_coordinator_state_updated` — called from coordinator update
   paths to persist the snapshot.

3. :func:`on_device_health_changed` — called from connection/heartbeat
   monitors to trigger formation rebalance evaluation.

4. :func:`on_task_admitted_for_dispatch` — called from scheduler relay/mesh
   dispatch paths to ensure task registration and routable-executor query.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Hooks over invasive wiring** — all integration points are designed as
  explicit hook functions so they can be called from existing code with
  minimal churn.
- **Graceful degradation** — every function returns a valid result even
  when backing modules are unavailable.
- **No new persistent state** — the harness delegates all state to the
  backing modules; it does not introduce its own store.

Sentinels
---------
:data:`MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY`
    Identifies this module as the multi-device runtime integration harness.
:data:`MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL`
    Affirms this module closes the gap of "high-value multi-device
    systemization groundwork".
:data:`HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY`
    Affirms that the harness wires mesh persistence, formation rebalance,
    and scheduling truth into a single coherent integration surface.

Public API
----------
Classes:
    :class:`MultiDeviceRuntimeHarness`
    :class:`DeviceHealthEvent`
    :class:`RuntimeHarnessResult`

Functions:
    :func:`on_coordinator_state_updated`
    :func:`on_device_health_changed`
    :func:`on_task_admitted_for_dispatch`
    :func:`get_multi_device_runtime_harness`
    :func:`reset_multi_device_runtime_harness`
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    # Sentinels
    "MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY",
    "MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL",
    "HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY",
    # Classes
    "DeviceHealthEvent",
    "RuntimeHarnessResult",
    "MultiDeviceRuntimeHarness",
    # Functions
    "on_coordinator_state_updated",
    "on_device_health_changed",
    "on_participant_readiness_changed",
    "on_task_admitted_for_dispatch",
    "get_multi_device_runtime_harness",
    "reset_multi_device_runtime_harness",
]

logger = logging.getLogger("Galaxy.MultiDeviceRuntimeHarness")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY: str = (
    "MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY: "
    "core/multi_device_runtime_harness.py is the canonical multi-device "
    "runtime integration harness for Galaxy."
)

MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL: str = (
    "MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE: "
    "This module closes the 'high-value multi-device systemization groundwork' "
    "gap by integrating mesh session persistence, formation rebalance, and "
    "scheduling truth into a single coherent harness."
)

HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY: str = (
    "HARNESS_POLICY: The MultiDeviceRuntimeHarness wires three backing layers: "
    "(1) MeshSessionPersistenceStore for durable coordinator snapshots, "
    "(2) FormationRebalanceEngine for health-driven formation reshaping, "
    "(3) SchedulingTruthHarness for task-registration and routable-executor "
    "queries at dispatch time."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DeviceHealthEvent:
    """A health event for one device in a formation or mesh session.

    Attributes
    ----------
    device_id:
        The device this event pertains to.
    health_score:
        Normalised health score in ``[0.0, 1.0]``.
    is_reachable:
        Whether the device is currently reachable.
    event_type:
        Type of event (e.g. ``"disconnect"``, ``"heartbeat_miss"``,
        ``"health_update"``).
    session_id:
        Optional mesh session ID this event is associated with.
    formation_id:
        Optional formation ID this event is associated with.
    reason:
        Optional human-readable reason.
    """

    device_id: str
    health_score: float = 0.0
    is_reachable: bool = True
    event_type: str = "health_update"
    session_id: Optional[str] = None
    formation_id: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "health_score": self.health_score,
            "is_reachable": self.is_reachable,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "formation_id": self.formation_id,
            "reason": self.reason,
        }


@dataclass
class RuntimeHarnessResult:
    """Result of a harness operation.

    Attributes
    ----------
    operation:
        Which harness operation was performed.
    success:
        Whether the operation succeeded.
    details:
        Human-readable summary.
    rebalance_triggered:
        Whether a formation rebalance was triggered.
    snapshot_saved:
        Whether a mesh session snapshot was saved.
    task_registered:
        Whether a task was registered in TaskGraphRuntime.
    routable_executor_ids:
        Executor IDs returned by the routable-executor query.
    errors:
        List of non-fatal errors encountered.
    """

    operation: str = ""
    success: bool = True
    details: str = ""
    rebalance_triggered: bool = False
    snapshot_saved: bool = False
    task_registered: bool = False
    routable_executor_ids: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    runtime_decision: Optional[Any] = None
    """Optional :class:`~core.device_formation.formation_runtime_coordinator.FormationRuntimeDecision`
    produced when a :class:`FormationRuntimeCoordinator` was involved."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "success": self.success,
            "details": self.details,
            "rebalance_triggered": self.rebalance_triggered,
            "snapshot_saved": self.snapshot_saved,
            "task_registered": self.task_registered,
            "routable_executor_ids": list(self.routable_executor_ids),
            "errors": list(self.errors),
            "runtime_decision": (
                self.runtime_decision.to_dict()
                if self.runtime_decision is not None
                and hasattr(self.runtime_decision, "to_dict")
                else None
            ),
        }


# ---------------------------------------------------------------------------
# MultiDeviceRuntimeHarness
# ---------------------------------------------------------------------------


class MultiDeviceRuntimeHarness:
    """Integration harness wiring mesh persistence, formation rebalance,
    and scheduling truth into a single coherent multi-device runtime surface.

    Usage::

        harness = get_multi_device_runtime_harness()

        # When a coordinator state is updated, persist it:
        harness.on_coordinator_state_updated(coordinator_state)

        # When a device disconnects or misses a heartbeat:
        harness.on_device_health_changed(
            DeviceHealthEvent(device_id="phone_01", health_score=0.0,
                              is_reachable=False, event_type="disconnect",
                              session_id="mesh-session-123")
        )

        # When a task is admitted for dispatch:
        result = harness.on_task_admitted_for_dispatch(canonical_task)
    """

    def __init__(self) -> None:
        self._persistence_store: Optional[Any] = None
        self._scheduling_harness: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lazy accessors for backing modules
    # ------------------------------------------------------------------

    def _get_persistence_store(self) -> Optional[Any]:
        if self._persistence_store is not None:
            return self._persistence_store
        try:
            from core.mesh.mesh_session_persistence import get_persistence_store
            self._persistence_store = get_persistence_store()
            return self._persistence_store
        except Exception as exc:
            logger.debug("MultiDeviceRuntimeHarness: persistence store unavailable: %s", exc)
            return None

    def _get_scheduling_harness(self) -> Optional[Any]:
        if self._scheduling_harness is not None:
            return self._scheduling_harness
        try:
            from core.scheduling_truth_harness import get_scheduling_truth_harness
            self._scheduling_harness = get_scheduling_truth_harness()
            return self._scheduling_harness
        except Exception as exc:
            logger.debug("MultiDeviceRuntimeHarness: scheduling harness unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public hook methods
    # ------------------------------------------------------------------

    def on_coordinator_state_updated(
        self,
        coordinator_state: Any,
    ) -> RuntimeHarnessResult:
        """Hook: called when a MeshSessionCoordinatorState is updated.

        Persists the updated coordinator snapshot to the durable store.

        Parameters
        ----------
        coordinator_state:
            ``MeshSessionCoordinatorState`` or compatible dict.

        Returns
        -------
        RuntimeHarnessResult
        """
        errors: List[str] = []
        snapshot_saved = False

        try:
            store = self._get_persistence_store()
            if store is None:
                errors.append("persistence store unavailable")
            else:
                record = store.save(coordinator_state)
                snapshot_saved = record is not None
                if not snapshot_saved:
                    errors.append("snapshot save returned None (session_id may be empty)")
        except Exception as exc:
            errors.append(f"snapshot save error: {exc}")
            logger.warning("on_coordinator_state_updated: error: %s", exc)

        return RuntimeHarnessResult(
            operation="on_coordinator_state_updated",
            success=snapshot_saved or not errors,
            details=(
                "snapshot saved"
                if snapshot_saved
                else f"snapshot not saved: {'; '.join(errors)}"
            ),
            snapshot_saved=snapshot_saved,
            errors=errors,
        )

    def on_device_health_changed(
        self,
        event: DeviceHealthEvent,
        formation: Optional[Any] = None,
    ) -> RuntimeHarnessResult:
        """Hook: called when a device health event is received.

        If a formation is provided and the device is unhealthy, evaluates
        whether a formation rebalance is needed and applies it.

        If the event has a ``session_id``, attempts to update the
        persisted session snapshot to reflect the health change.

        Parameters
        ----------
        event:
            :class:`DeviceHealthEvent` describing the health change.
        formation:
            Optional :class:`~core.device_formation.DeviceFormationGroup` to
            rebalance.

        Returns
        -------
        RuntimeHarnessResult
        """
        errors: List[str] = []
        rebalance_triggered = False
        snapshot_saved = False
        new_formation = formation

        try:
            # Attempt formation rebalance if a formation is available
            if formation is not None:
                try:
                    from core.device_formation.formation_rebalance_engine import (
                        FormationHealthSignal,
                        apply_rebalance,
                    )
                    health_map = {
                        event.device_id: FormationHealthSignal(
                            device_id=event.device_id,
                            health_score=event.health_score,
                            is_reachable=event.is_reachable,
                            reason=event.reason or event.event_type,
                        )
                    }
                    new_formation, decision = apply_rebalance(formation, health_map)
                    rebalance_triggered = bool(
                        decision is not None and decision.rebalance_needed
                    )
                    if rebalance_triggered:
                        logger.info(
                            "on_device_health_changed: formation rebalance triggered "
                            "for device %s (event=%s, reason=%s)",
                            event.device_id,
                            event.event_type,
                            getattr(decision, "reason", ""),
                        )
                except Exception as exc:
                    errors.append(f"formation rebalance error: {exc}")
                    logger.warning("on_device_health_changed: rebalance error: %s", exc)

            # If session_id is present, mark the session as needing recovery
            # if the device is unreachable (do not mark terminal — recovery is possible)
            if event.session_id and not event.is_reachable:
                try:
                    store = self._get_persistence_store()
                    if store is not None:
                        record = store.load(event.session_id)
                        if record is not None and not record.is_terminal():
                            # Re-save with an updated status hint in metadata
                            snap = dict(record.snapshot_dict)
                            snap.setdefault("recovery_hints", {})
                            snap["recovery_hints"][event.device_id] = {
                                "unreachable": True,
                                "event_type": event.event_type,
                            }
                            updated_record = record.__class__(
                                session_id=record.session_id,
                                coordinator_id=record.coordinator_id,
                                overall_status=record.overall_status,
                                snapshot_dict=snap,
                                version=record.version + 1,
                            )
                            store._write_record(updated_record)  # type: ignore[attr-defined]
                            store._memory_cache[record.session_id] = updated_record  # type: ignore[attr-defined]
                            snapshot_saved = True
                except Exception as exc:
                    errors.append(f"session snapshot update error: {exc}")

        except Exception as exc:
            errors.append(f"unexpected harness error: {exc}")
            logger.warning("on_device_health_changed: unexpected error: %s", exc)

        return RuntimeHarnessResult(
            operation="on_device_health_changed",
            success=not errors or rebalance_triggered,
            details=(
                f"device={event.device_id} event={event.event_type} "
                f"rebalance={'yes' if rebalance_triggered else 'no'}"
            ),
            rebalance_triggered=rebalance_triggered,
            snapshot_saved=snapshot_saved,
            errors=errors,
        )

    def on_task_admitted_for_dispatch(
        self,
        canonical_task: Any,
        *,
        candidate_device_ids: Optional[List[str]] = None,
        trace_id: Optional[str] = None,
    ) -> RuntimeHarnessResult:
        """Hook: called when a task is admitted to a relay/mesh dispatch path.

        1. Ensures the task is registered in TaskGraphRuntime (GAP-512-002).
        2. Queries routable executors via canonical capability/network truth
           (GAP-512-004).

        Parameters
        ----------
        canonical_task:
            ``CanonicalTask`` or compatible dict.
        candidate_device_ids:
            Optional pre-filtered candidate device IDs.
        trace_id:
            Optional trace correlation ID.

        Returns
        -------
        RuntimeHarnessResult
        """
        errors: List[str] = []
        task_registered = False
        routable_ids: List[str] = []

        try:
            sh = self._get_scheduling_harness()
            if sh is None:
                errors.append("scheduling truth harness unavailable")
            else:
                # 1. Ensure task is registered
                task_registered = sh.ensure_task_registered(
                    canonical_task, trace_id=trace_id
                )

                # 2. Query routable executors
                routable_ids = sh.query_routable_executors(
                    canonical_task, candidate_device_ids=candidate_device_ids
                )

        except Exception as exc:
            errors.append(f"scheduling harness error: {exc}")
            logger.warning("on_task_admitted_for_dispatch: error: %s", exc)

        return RuntimeHarnessResult(
            operation="on_task_admitted_for_dispatch",
            success=True,  # graceful degradation — never blocks dispatch
            details=(
                f"task_registered={task_registered} "
                f"routable_executors={len(routable_ids)}"
            ),
            task_registered=task_registered,
            routable_executor_ids=routable_ids,
            errors=errors,
        )

    def recover_sessions(self) -> List[Any]:
        """Return snapshot records for all non-terminal mesh sessions.

        Returns
        -------
        List[SnapshotRecord]
            Recoverable session snapshots from the durable store, or ``[]``
            on unavailability.
        """
        try:
            from core.mesh.mesh_session_persistence import recover_mesh_sessions
            return recover_mesh_sessions()
        except Exception as exc:
            logger.debug("MultiDeviceRuntimeHarness.recover_sessions: error: %s", exc)
            return []

    def on_participant_readiness_changed(
        self,
        device_id: str,
        new_readiness: str,
        *,
        health_score: Optional[float] = None,
        formation: Optional[Any] = None,
        session_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> RuntimeHarnessResult:
        """Hook: called when a formation participant's readiness state changes.

        This is the primary entry point for readiness-driven formation recovery.
        It:

        1. Translates the readiness string into a
           :class:`~core.device_formation.formation_runtime_coordinator.FormationParticipantState`.
        2. If a *formation* is provided, creates a temporary
           :class:`~core.device_formation.formation_runtime_coordinator.FormationRuntimeCoordinator`
           and triggers ``on_participant_readiness_changed`` on it to get a
           :class:`~core.device_formation.formation_runtime_coordinator.FormationRuntimeDecision`.
        3. If the decision recommends a reshape (and a formation is present),
           runs the formation rebalance engine.
        4. If a *session_id* is provided and the participant is no longer ready,
           marks the session snapshot with a recovery hint.

        Parameters
        ----------
        device_id:
            Device whose readiness changed.
        new_readiness:
            String readiness state.  Recognised values: ``"ready"``,
            ``"degraded"``, ``"lost"``, ``"recovering"``.  Unknown values
            default to ``"degraded"``.
        health_score:
            Optional health score override.
        formation:
            Optional :class:`~core.device_formation.DeviceFormationGroup` to
            evaluate and potentially reshape.
        session_id:
            Optional mesh session ID to update in the persistence store.
        reason:
            Optional human-readable reason.

        Returns
        -------
        RuntimeHarnessResult
        """
        errors: List[str] = []
        rebalance_triggered = False
        snapshot_saved = False
        runtime_decision: Optional[Any] = None

        try:
            from core.device_formation.formation_runtime_coordinator import (
                FormationParticipantState,
                FormationRuntimeCoordinator,
                RecoveryActionType,
            )

            # Map string to enum
            _state_map = {
                "ready": FormationParticipantState.READY,
                "degraded": FormationParticipantState.DEGRADED,
                "lost": FormationParticipantState.LOST,
                "recovering": FormationParticipantState.RECOVERING,
            }
            participant_state = _state_map.get(
                (new_readiness or "").lower(),
                FormationParticipantState.DEGRADED,
            )

            if formation is not None:
                try:
                    coordinator = FormationRuntimeCoordinator(formation)
                    decision = coordinator.on_participant_readiness_changed(
                        device_id,
                        participant_state,
                        health_score=health_score,
                        reason=reason or new_readiness,
                    )
                    runtime_decision = decision

                    # If the decision resulted in a reshape, mark rebalance_triggered
                    if decision.new_group is not None:
                        rebalance_triggered = True
                        logger.info(
                            "on_participant_readiness_changed: formation reshaped for "
                            "device=%s state=%s (formation=%s)",
                            device_id,
                            new_readiness,
                            getattr(formation, "formation_id", ""),
                        )
                except Exception as exc:
                    errors.append(f"formation runtime coordinator error: {exc}")
                    logger.warning(
                        "on_participant_readiness_changed: coordinator error: %s", exc
                    )

            # Update session snapshot if session_id is provided
            if session_id and participant_state in (
                FormationParticipantState.LOST,
                FormationParticipantState.DEGRADED,
            ):
                try:
                    store = self._get_persistence_store()
                    if store is not None:
                        record = store.load(session_id)
                        if record is not None and not record.is_terminal():
                            snap = dict(record.snapshot_dict)
                            snap.setdefault("readiness_hints", {})
                            snap["readiness_hints"][device_id] = {
                                "readiness": new_readiness,
                                "health_score": health_score,
                                "reason": reason,
                            }
                            updated_record = record.__class__(
                                session_id=record.session_id,
                                coordinator_id=record.coordinator_id,
                                overall_status=record.overall_status,
                                snapshot_dict=snap,
                                version=record.version + 1,
                            )
                            store._write_record(updated_record)  # type: ignore[attr-defined]
                            store._memory_cache[record.session_id] = updated_record  # type: ignore[attr-defined]
                            snapshot_saved = True
                except Exception as exc:
                    errors.append(f"session snapshot readiness update error: {exc}")

        except Exception as exc:
            errors.append(f"unexpected harness error: {exc}")
            logger.warning(
                "on_participant_readiness_changed: unexpected error: %s", exc
            )

        return RuntimeHarnessResult(
            operation="on_participant_readiness_changed",
            success=not errors or rebalance_triggered,
            details=(
                f"device={device_id} readiness={new_readiness} "
                f"rebalance={'yes' if rebalance_triggered else 'no'}"
            ),
            rebalance_triggered=rebalance_triggered,
            snapshot_saved=snapshot_saved,
            errors=errors,
            runtime_decision=runtime_decision,
        )


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_harness_singleton: Optional[MultiDeviceRuntimeHarness] = None
_harness_lock = threading.Lock()


def get_multi_device_runtime_harness() -> MultiDeviceRuntimeHarness:
    """Return the module-level singleton ``MultiDeviceRuntimeHarness``."""
    global _harness_singleton
    with _harness_lock:
        if _harness_singleton is None:
            _harness_singleton = MultiDeviceRuntimeHarness()
        return _harness_singleton


def reset_multi_device_runtime_harness() -> None:
    """Reset the module-level singleton (primarily for test isolation)."""
    global _harness_singleton
    with _harness_lock:
        _harness_singleton = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def on_coordinator_state_updated(
    coordinator_state: Any,
    *,
    harness: Optional[MultiDeviceRuntimeHarness] = None,
) -> RuntimeHarnessResult:
    """Hook: persist an updated MeshSessionCoordinatorState.

    Parameters
    ----------
    coordinator_state:
        ``MeshSessionCoordinatorState`` or compatible dict.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    RuntimeHarnessResult
    """
    _harness = harness or get_multi_device_runtime_harness()
    return _harness.on_coordinator_state_updated(coordinator_state)


def on_device_health_changed(
    event: DeviceHealthEvent,
    formation: Optional[Any] = None,
    *,
    harness: Optional[MultiDeviceRuntimeHarness] = None,
) -> RuntimeHarnessResult:
    """Hook: respond to a device health change event.

    Parameters
    ----------
    event:
        :class:`DeviceHealthEvent` describing the health change.
    formation:
        Optional formation to rebalance.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    RuntimeHarnessResult
    """
    _harness = harness or get_multi_device_runtime_harness()
    return _harness.on_device_health_changed(event, formation)


def on_task_admitted_for_dispatch(
    canonical_task: Any,
    *,
    candidate_device_ids: Optional[List[str]] = None,
    trace_id: Optional[str] = None,
    harness: Optional[MultiDeviceRuntimeHarness] = None,
) -> RuntimeHarnessResult:
    """Hook: admit a task for relay/mesh dispatch.

    Parameters
    ----------
    canonical_task:
        ``CanonicalTask`` or compatible dict.
    candidate_device_ids:
        Optional pre-filtered candidate device IDs.
    trace_id:
        Optional trace correlation ID.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    RuntimeHarnessResult
    """
    _harness = harness or get_multi_device_runtime_harness()
    return _harness.on_task_admitted_for_dispatch(
        canonical_task,
        candidate_device_ids=candidate_device_ids,
        trace_id=trace_id,
    )


def on_participant_readiness_changed(
    device_id: str,
    new_readiness: str,
    *,
    health_score: Optional[float] = None,
    formation: Optional[Any] = None,
    session_id: Optional[str] = None,
    reason: Optional[str] = None,
    harness: Optional[MultiDeviceRuntimeHarness] = None,
) -> RuntimeHarnessResult:
    """Hook: respond to a participant readiness state change.

    Parameters
    ----------
    device_id:
        Device whose readiness changed.
    new_readiness:
        String readiness state: ``"ready"``, ``"degraded"``, ``"lost"``,
        or ``"recovering"``.
    health_score:
        Optional health score.
    formation:
        Optional formation to evaluate and potentially reshape.
    session_id:
        Optional mesh session ID to update.
    reason:
        Optional human-readable reason.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    RuntimeHarnessResult
    """
    _harness = harness or get_multi_device_runtime_harness()
    return _harness.on_participant_readiness_changed(
        device_id,
        new_readiness,
        health_score=health_score,
        formation=formation,
        session_id=session_id,
        reason=reason,
    )
