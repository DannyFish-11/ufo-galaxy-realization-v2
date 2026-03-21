"""core/mesh/mesh_session_coordinator.py
==========================================
Mesh Session Coordinator — PR-37.

This module implements the **canonical Mesh Session Coordinator** layer:
the single coordination object that manages a mesh session across multiple
devices/runtimes, assigns or confirms participant roles, tracks subtask
lifecycle, monitors barriers/merge posture, and emits a stable coordination
summary.

It is the coordinator-side companion to:

- **PR-33** (:class:`~contracts.mesh_session.MeshSession`) — the mesh session
  contract that defines the session being coordinated.
- **PR-34** (``target_takeover``) — target-side execution.
- **PR-35** (``source_dispatch_orchestrator``) — source-side dispatch.
- **PR-36** (``cross_runtime_result_merge``) — cross-runtime result merging.

This module answers the architectural question:

    *"Once a mesh session exists, what canonical coordinator manages
    participation, assignment, status, and merge/barrier posture across
    the session?"*

Public surface
--------------
Handler class:
    :class:`MeshSessionCoordinator` — stateless handler wrapping all
    coordination helpers.

Entry points:
    :func:`coordinate_mesh_session` — convenience entry point: builds a
    coordinator state from a mesh session and available runtime signals.

    :func:`get_coordinator_summary` — build a lightweight summary of the
    current coordination state.

Design principles
-----------------
- **Additive only** — does not modify openclawd.py or any existing module.
- **Graceful degradation** — every function returns a valid result even when
  inputs are partial, None, or raise.
- **Stateless** — the coordinator does not own persistent state; it operates
  on coordinator state objects from the contracts layer.
- **No full distributed scheduler** — deferred to future PRs.
- **No persistence / streaming** — deferred to future PRs.

Usage::

    from core.mesh.mesh_session_coordinator import (
        MeshSessionCoordinator,
        coordinate_mesh_session,
        get_coordinator_summary,
    )

    coordinator = MeshSessionCoordinator()
    state = coordinate_mesh_session(mesh_session=my_session)
    summary = get_coordinator_summary(state)
    print(summary.to_json(indent=2))

See ``docs/MESH_SESSION_COORDINATOR.md`` for the full specification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy contract imports — avoids hard dependency at import time
# ---------------------------------------------------------------------------


def _import_coordinator_contracts() -> Any:
    """Lazily import the coordinator contract module."""
    from contracts import mesh_session_coordinator as _mod
    return _mod


# ---------------------------------------------------------------------------
# MeshSessionCoordinator — stateless handler class
# ---------------------------------------------------------------------------


class MeshSessionCoordinator:
    """Stateless handler that provides coordination helpers for mesh sessions.

    All methods return new coordinator state objects; no mutation of existing
    objects occurs.

    Usage::

        handler = MeshSessionCoordinator()

        # Build initial coordinator state from a mesh session contract
        state = handler.from_mesh_session(mesh_session)

        # Update with dispatch result after source dispatches work
        state = handler.update_with_dispatch_result(state, dispatch_result)

        # Update with takeover result after target executes
        state = handler.update_with_takeover_result(state, takeover_result, device_id="tablet_01")

        # Update with merged result after cross-runtime merge
        state = handler.update_with_merged_result(state, merged_result)

        # Get lightweight summary
        summary = handler.get_summary(state)
    """

    def from_mesh_session(
        self,
        mesh_session: Any,
        *,
        trace_id: Optional[str] = None,
    ) -> Any:
        """Build a :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
        from a :class:`~contracts.mesh_session.MeshSession`.

        Parameters
        ----------
        mesh_session:
            A mesh session contract or compatible dict.
        trace_id:
            Optional trace ID override.

        Returns
        -------
        MeshSessionCoordinatorState
            Never raises.
        """
        try:
            mod = _import_coordinator_contracts()
            return mod.from_mesh_session(mesh_session, trace_id=trace_id)
        except Exception as exc:
            _logger.warning(
                "MeshSessionCoordinator.from_mesh_session: error: %s", exc
            )
            try:
                mod = _import_coordinator_contracts()
                return mod.MeshSessionCoordinatorState()
            except Exception:
                return None

    def update_with_dispatch_result(
        self,
        coordinator: Any,
        dispatch_result: Any,
    ) -> Any:
        """Incorporate a source dispatch result into the coordinator state.

        Parameters
        ----------
        coordinator:
            Existing coordinator state.
        dispatch_result:
            Source dispatch result (PR-35) or compatible dict.

        Returns
        -------
        MeshSessionCoordinatorState
            Updated state.  Never raises.
        """
        try:
            mod = _import_coordinator_contracts()
            return mod.update_coordinator_with_dispatch_result(
                coordinator, dispatch_result
            )
        except Exception as exc:
            _logger.warning(
                "MeshSessionCoordinator.update_with_dispatch_result: error: %s", exc
            )
            return coordinator

    def update_with_takeover_result(
        self,
        coordinator: Any,
        takeover_result: Any,
        *,
        device_id: Optional[str] = None,
    ) -> Any:
        """Incorporate a target takeover result into the coordinator state.

        Parameters
        ----------
        coordinator:
            Existing coordinator state.
        takeover_result:
            Target takeover result (PR-34) or compatible dict.
        device_id:
            Optional device ID override for the executing device.

        Returns
        -------
        MeshSessionCoordinatorState
            Updated state.  Never raises.
        """
        try:
            mod = _import_coordinator_contracts()
            return mod.update_coordinator_with_takeover_result(
                coordinator, takeover_result, device_id=device_id
            )
        except Exception as exc:
            _logger.warning(
                "MeshSessionCoordinator.update_with_takeover_result: error: %s", exc
            )
            return coordinator

    def update_with_merged_result(
        self,
        coordinator: Any,
        merged_result: Any,
    ) -> Any:
        """Incorporate a cross-runtime merged result into the coordinator state.

        Parameters
        ----------
        coordinator:
            Existing coordinator state.
        merged_result:
            Cross-runtime merged result (PR-36) or compatible dict.

        Returns
        -------
        MeshSessionCoordinatorState
            Updated state.  Never raises.
        """
        try:
            mod = _import_coordinator_contracts()
            return mod.update_coordinator_with_merged_result(coordinator, merged_result)
        except Exception as exc:
            _logger.warning(
                "MeshSessionCoordinator.update_with_merged_result: error: %s", exc
            )
            return coordinator

    def get_summary(
        self,
        coordinator: Any,
    ) -> Any:
        """Build a lightweight summary from coordinator state.

        Parameters
        ----------
        coordinator:
            Coordinator state to summarise.

        Returns
        -------
        MeshSessionCoordinatorSummary
            Never raises.
        """
        try:
            mod = _import_coordinator_contracts()
            return mod.build_coordinator_summary(coordinator=coordinator)
        except Exception as exc:
            _logger.warning(
                "MeshSessionCoordinator.get_summary: error: %s", exc
            )
            try:
                mod = _import_coordinator_contracts()
                return mod.MeshSessionCoordinatorSummary()
            except Exception:
                return None

    def build(
        self,
        *,
        session_id: Optional[str] = None,
        mesh_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Build a fresh coordinator state from minimal parameters.

        Parameters
        ----------
        session_id:
            Optional mesh session ID.
        mesh_id:
            Optional mesh ID.
        trace_id:
            Optional trace ID.
        task_id:
            Optional task ID.
        metadata:
            Optional metadata.

        Returns
        -------
        MeshSessionCoordinatorState
            Never raises.
        """
        try:
            mod = _import_coordinator_contracts()
            return mod.build_mesh_session_coordinator(
                session_id=session_id,
                mesh_id=mesh_id,
                trace_id=trace_id,
                task_id=task_id,
                metadata=metadata or {},
            )
        except Exception as exc:
            _logger.warning(
                "MeshSessionCoordinator.build: error: %s", exc
            )
            try:
                mod = _import_coordinator_contracts()
                return mod.MeshSessionCoordinatorState(
                    session_id=session_id, mesh_id=mesh_id
                )
            except Exception:
                return None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def coordinate_mesh_session(
    mesh_session: Any = None,
    *,
    dispatch_result: Any = None,
    takeover_result: Any = None,
    merged_result: Any = None,
    takeover_device_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    mesh_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """Convenience entry point for building or evolving coordinator state.

    This function:
    1. Builds a :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
       from a mesh session (if provided) or from kwargs.
    2. Applies any dispatch/takeover/merge results in order.
    3. Returns the final coordinator state.

    All parameters are optional; partial input always produces a valid result.

    Parameters
    ----------
    mesh_session:
        A :class:`~contracts.mesh_session.MeshSession` or compatible dict
        to seed the coordinator state.
    dispatch_result:
        Optional source dispatch result (PR-35) to incorporate.
    takeover_result:
        Optional target takeover result (PR-34) to incorporate.
    merged_result:
        Optional cross-runtime merged result (PR-36) to incorporate.
    takeover_device_id:
        Optional device ID associated with *takeover_result*.
    trace_id:
        Optional trace ID.
    mesh_id:
        Optional mesh ID (used when *mesh_session* is None).
    session_id:
        Optional session ID (used when *mesh_session* is None).
    task_id:
        Optional task ID.
    metadata:
        Optional metadata dict.

    Returns
    -------
    MeshSessionCoordinatorState
        Never raises.
    """
    try:
        mod = _import_coordinator_contracts()

        # Step 1: Build initial state
        if mesh_session is not None:
            state = mod.from_mesh_session(mesh_session, trace_id=trace_id)
            if task_id and not state.task_id:
                state = state.model_copy(update={"task_id": task_id})
            if mesh_id and not state.mesh_id:
                state = state.model_copy(update={"mesh_id": mesh_id})
        else:
            state = mod.build_mesh_session_coordinator(
                session_id=session_id,
                mesh_id=mesh_id,
                trace_id=trace_id,
                task_id=task_id,
                metadata=metadata or {},
            )

        # Step 2: Apply dispatch result
        if dispatch_result is not None:
            state = mod.update_coordinator_with_dispatch_result(state, dispatch_result)

        # Step 3: Apply takeover result
        if takeover_result is not None:
            state = mod.update_coordinator_with_takeover_result(
                state, takeover_result, device_id=takeover_device_id
            )

        # Step 4: Apply merged result
        if merged_result is not None:
            state = mod.update_coordinator_with_merged_result(state, merged_result)

        return state

    except Exception as exc:
        _logger.warning(
            "coordinate_mesh_session: unexpected error, returning minimal state: %s",
            exc,
        )
        try:
            mod = _import_coordinator_contracts()
            return mod.MeshSessionCoordinatorState(
                session_id=session_id, mesh_id=mesh_id
            )
        except Exception:
            return None


def get_coordinator_summary(
    coordinator: Any,
) -> Any:
    """Build a lightweight :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`.

    Parameters
    ----------
    coordinator:
        Coordinator state to summarise.

    Returns
    -------
    MeshSessionCoordinatorSummary
        Never raises.
    """
    try:
        mod = _import_coordinator_contracts()
        return mod.build_coordinator_summary(coordinator=coordinator)
    except Exception as exc:
        _logger.warning("get_coordinator_summary: error: %s", exc)
        try:
            mod = _import_coordinator_contracts()
            return mod.MeshSessionCoordinatorSummary()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "MeshSessionCoordinator",
    "coordinate_mesh_session",
    "get_coordinator_summary",
]
