#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/liminal_space_mapping.py — Liminal Space Mapping (PR-5)

**Unified-Subject Architecture — Liminal Space Mapping**
---------------------------------------------------------
This module defines the **canonical mapping** from execution and simulation
concepts into liminal-space-facing structures.

Liminal space is the **spatial execution field** of the Galaxy runtime.
It sits in the middle of the tri-state lifecycle (silent → liminal → manifest)
and carries exactly three categories of content:

1. **Local execution chain** — on-device execution path
2. **Cross-device execution chain** — distributed multi-device execution path
3. **Sandbox simulation / speculative execution field** — uncommitted/simulated paths

This module provides lightweight, serialisable, read-only view structures
derived from the canonical execution chain singletons.  These structures are
intended for consumption by liminal-surface renderers, audit logs, and
projection consumers.

Structural separation
---------------------
- **LiminalSpaceMap** wraps all three content classes in one serialisable unit.
- **LocalChainView** is derived from ``LocalChainSnapshot``.
- **CrossDeviceChainView** is derived from ``CrossDeviceChainSnapshot``.
- **SimulationSummary** captures sandbox/speculative execution state.

Boundary rule
-------------
These structures must NOT contain:
- Provider list cards or vendor tags.
- Dashboard-style model panels or routing-authority topology.
- Full metrics/status-board panels (presence_intensity, coherence, etc.).
- Generic operator information blocks.

Those fields belong exclusively to the right-side desktop status board
(``windows_client/status_board_v2/``).

See ``docs/LIMINAL_SPACE_MAPPING.md`` for the full canonical definition and
``docs/SANDBOX_SIMULATION_PROJECTION.md`` for sandbox/simulation semantics.

Public API
----------
:class:`LocalChainView`
    Read-only liminal-facing view of the local execution chain.

:class:`CrossDeviceChainView`
    Read-only liminal-facing view of the cross-device execution chain.

:class:`SimulationSummary`
    Read-only liminal-facing summary of the sandbox/speculative field.

:class:`LiminalSpaceMap`
    Composite serialisable structure holding all three content classes.

:func:`build_local_chain_view`
    Build a :class:`LocalChainView` from a ``LocalChainSnapshot`` dict.

:func:`build_cross_device_chain_view`
    Build a :class:`CrossDeviceChainView` from a ``CrossDeviceChainSnapshot`` dict.

:func:`build_simulation_summary`
    Build a :class:`SimulationSummary` from keyword arguments.

:func:`build_liminal_space_map`
    Build a :class:`LiminalSpaceMap` from the current singleton state.

:func:`get_liminal_space_map`
    Return a :class:`LiminalSpaceMap` built from the current singletons
    (convenience wrapper around :func:`build_liminal_space_map`).
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from typing import Any, Dict, List, Optional

__all__ = [
    "LocalChainView",
    "CrossDeviceChainView",
    "SimulationSummary",
    "LiminalSpaceMap",
    "build_local_chain_view",
    "build_cross_device_chain_view",
    "build_simulation_summary",
    "build_liminal_space_map",
    "get_liminal_space_map",
]

# ---------------------------------------------------------------------------
# Boundary guard — fields prohibited in liminal structures
# ---------------------------------------------------------------------------

#: Fields that must NOT appear in any liminal-space structure.
#: These are right-side status-board fields.
_PROHIBITED_FIELDS = frozenset(
    {
        "primary_model_id",
        "support_model_ids",
        "active_weights",
        "route_reason",
        "routing_authority",
        "oneapi_source",
        "vendor_source",
        "topology_role",
        "presence_intensity",
        "coherence",
        "collapse_tendency",
        "retreat_tendency",
        "provider_list",
    }
)


# ---------------------------------------------------------------------------
# LocalChainView
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LocalChainView:
    """Read-only liminal-space view of the local execution chain.

    Derived from :class:`core.local_execution_chain.LocalChainSnapshot`.
    Suitable for liminal-surface rendering and audit consumption.

    This structure must NOT contain provider/model topology fields.

    Attributes
    ----------
    total_executions:
        Total local executions recorded in the current session.
    canonical_executions:
        Executions that followed the full canonical chain.
    legacy_executions:
        Executions that used a legacy / non-canonical path.
    canonical_chain_order:
        Ordered list of canonical step names.
    last_task_id:
        Task ID of the most recent local execution, if any.
    last_step:
        Most recent chain step reached, if available.
    is_active:
        Whether at least one execution has been recorded.
    timestamp:
        UNIX timestamp when this view was built.
    """

    total_executions: int = 0
    canonical_executions: int = 0
    legacy_executions: int = 0
    canonical_chain_order: List[str] = dataclasses.field(default_factory=list)
    last_task_id: Optional[str] = None
    last_step: Optional[str] = None
    is_active: bool = False
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict.  Safe for JSON encoding."""
        return {
            "total_executions": self.total_executions,
            "canonical_executions": self.canonical_executions,
            "legacy_executions": self.legacy_executions,
            "canonical_chain_order": list(self.canonical_chain_order),
            "last_task_id": self.last_task_id,
            "last_step": self.last_step,
            "is_active": self.is_active,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# CrossDeviceChainView
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CrossDeviceChainView:
    """Read-only liminal-space view of the cross-device execution chain.

    Derived from :class:`core.cross_device_execution_chain.CrossDeviceChainSnapshot`.
    Suitable for liminal-surface rendering and audit consumption.

    This structure must NOT contain provider/model topology fields.

    Attributes
    ----------
    total_executions:
        Total cross-device executions recorded in the current session.
    canonical_executions:
        Executions that followed the full canonical chain.
    legacy_executions:
        Executions that used a legacy / non-canonical path.
    canonical_chain_order:
        Ordered list of canonical step names.
    last_device_id:
        Device ID of the most recent cross-device execution, if any.
    last_step:
        Most recent chain step reached, if available.
    is_active:
        Whether at least one execution has been recorded.
    timestamp:
        UNIX timestamp when this view was built.
    """

    total_executions: int = 0
    canonical_executions: int = 0
    legacy_executions: int = 0
    canonical_chain_order: List[str] = dataclasses.field(default_factory=list)
    last_device_id: Optional[str] = None
    last_step: Optional[str] = None
    is_active: bool = False
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict.  Safe for JSON encoding."""
        return {
            "total_executions": self.total_executions,
            "canonical_executions": self.canonical_executions,
            "legacy_executions": self.legacy_executions,
            "canonical_chain_order": list(self.canonical_chain_order),
            "last_device_id": self.last_device_id,
            "last_step": self.last_step,
            "is_active": self.is_active,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# SimulationSummary
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SimulationSummary:
    """Read-only liminal-space summary of the sandbox/speculative execution field.

    Captures uncommitted or sandboxed execution paths that have not yet
    resolved to either the local or cross-device chain.

    See ``docs/SANDBOX_SIMULATION_PROJECTION.md`` for full semantics.

    Attributes
    ----------
    summary_id:
        Auto-generated UUID for this summary.
    is_active:
        Whether a simulation or speculative execution is currently running.
    simulation_kind:
        One of ``"speculative"``, ``"sandbox"``, or ``"none"``.
    candidate_paths:
        Labels of candidate execution paths under evaluation.
    committed_path:
        The path committed to (``None`` if still speculative).
    scenario_label:
        Human-readable label for the current scenario, if any.
    step_count:
        Number of simulation steps completed.
    is_committed:
        Whether this simulation has resolved to a committed path.
    timestamp:
        UNIX timestamp when this summary was built.
    """

    summary_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    is_active: bool = False
    simulation_kind: str = "none"
    candidate_paths: List[str] = dataclasses.field(default_factory=list)
    committed_path: Optional[str] = None
    scenario_label: Optional[str] = None
    step_count: int = 0
    is_committed: bool = False
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict.  Safe for JSON encoding."""
        return {
            "summary_id": self.summary_id,
            "is_active": self.is_active,
            "simulation_kind": self.simulation_kind,
            "candidate_paths": list(self.candidate_paths),
            "committed_path": self.committed_path,
            "scenario_label": self.scenario_label,
            "step_count": self.step_count,
            "is_committed": self.is_committed,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# LiminalSpaceMap
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LiminalSpaceMap:
    """Composite serialisable structure for liminal-space consumption.

    Holds exactly the three allowed content classes for liminal space:

    1. ``local_chain`` — on-device execution path
    2. ``cross_device_chain`` — distributed multi-device execution path
    3. ``simulation_summary`` — sandbox / speculative execution field

    This structure is read-only, serialisable, and suitable for:
    - Liminal surface rendering (``windows_client/status_board_v2/liminal_surface.py``)
    - Audit/debug endpoints
    - Projection consumer attachment

    Boundary rule: this structure must NOT contain provider/model topology
    fields or status-board-style information.  See ``docs/LIMINAL_SPACE_MAPPING.md``.

    Attributes
    ----------
    map_id:
        Auto-generated UUID for this map instance.
    local_chain:
        Liminal-facing view of the local execution chain.
    cross_device_chain:
        Liminal-facing view of the cross-device execution chain.
    simulation_summary:
        Liminal-facing summary of the sandbox/speculative field.
    timestamp:
        UNIX timestamp when this map was built.
    """

    map_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    local_chain: LocalChainView = dataclasses.field(
        default_factory=LocalChainView
    )
    cross_device_chain: CrossDeviceChainView = dataclasses.field(
        default_factory=CrossDeviceChainView
    )
    simulation_summary: SimulationSummary = dataclasses.field(
        default_factory=SimulationSummary
    )
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict.  Safe for JSON encoding."""
        return {
            "map_id": self.map_id,
            "local_chain": self.local_chain.to_dict(),
            "cross_device_chain": self.cross_device_chain.to_dict(),
            "simulation_summary": self.simulation_summary.to_dict(),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Builder: LocalChainView
# ---------------------------------------------------------------------------


def build_local_chain_view(
    snapshot_dict: Optional[Dict[str, Any]] = None,
) -> LocalChainView:
    """Build a :class:`LocalChainView` from a ``LocalChainSnapshot`` dict.

    Parameters
    ----------
    snapshot_dict:
        A plain dict as produced by ``LocalChainSnapshot.to_dict()``.
        If ``None`` or empty, returns a zero-state view.

    Returns
    -------
    LocalChainView
        Read-only view suitable for liminal-surface rendering.
    """
    if not snapshot_dict:
        return LocalChainView()

    total = int(snapshot_dict.get("total_executions", 0))
    canonical = int(snapshot_dict.get("canonical_executions", 0))
    legacy = int(snapshot_dict.get("legacy_executions", 0))
    chain_order: List[str] = list(snapshot_dict.get("canonical_chain_order", []))

    # Extract last task ID and last step from the most recent record.
    last_task_id: Optional[str] = None
    last_step: Optional[str] = None
    recent: List[Dict[str, Any]] = snapshot_dict.get("recent_records", []) or []
    if recent:
        last_record = recent[-1]
        last_task_id = last_record.get("task_id") or None
        steps = last_record.get("steps_completed") or []
        if steps:
            last_step = steps[-1]

    return LocalChainView(
        total_executions=total,
        canonical_executions=canonical,
        legacy_executions=legacy,
        canonical_chain_order=chain_order,
        last_task_id=last_task_id,
        last_step=last_step,
        is_active=total > 0,
    )


# ---------------------------------------------------------------------------
# Builder: CrossDeviceChainView
# ---------------------------------------------------------------------------


def build_cross_device_chain_view(
    snapshot_dict: Optional[Dict[str, Any]] = None,
) -> CrossDeviceChainView:
    """Build a :class:`CrossDeviceChainView` from a ``CrossDeviceChainSnapshot`` dict.

    Parameters
    ----------
    snapshot_dict:
        A plain dict as produced by ``CrossDeviceChainSnapshot.to_dict()``.
        If ``None`` or empty, returns a zero-state view.

    Returns
    -------
    CrossDeviceChainView
        Read-only view suitable for liminal-surface rendering.
    """
    if not snapshot_dict:
        return CrossDeviceChainView()

    total = int(snapshot_dict.get("total_executions", 0))
    canonical = int(snapshot_dict.get("canonical_executions", 0))
    legacy = int(snapshot_dict.get("legacy_executions", 0))
    chain_order: List[str] = list(snapshot_dict.get("canonical_chain_order", []))

    # Extract last device ID and last step from the most recent record.
    last_device_id: Optional[str] = None
    last_step: Optional[str] = None
    recent: List[Dict[str, Any]] = snapshot_dict.get("recent_records", []) or []
    if recent:
        last_record = recent[-1]
        last_device_id = last_record.get("device_id") or None
        steps = last_record.get("steps_completed") or []
        if steps:
            last_step = steps[-1]

    return CrossDeviceChainView(
        total_executions=total,
        canonical_executions=canonical,
        legacy_executions=legacy,
        canonical_chain_order=chain_order,
        last_device_id=last_device_id,
        last_step=last_step,
        is_active=total > 0,
    )


# ---------------------------------------------------------------------------
# Builder: SimulationSummary
# ---------------------------------------------------------------------------


def build_simulation_summary(
    *,
    is_active: bool = False,
    simulation_kind: str = "none",
    candidate_paths: Optional[List[str]] = None,
    committed_path: Optional[str] = None,
    scenario_label: Optional[str] = None,
    step_count: int = 0,
) -> SimulationSummary:
    """Build a :class:`SimulationSummary` from keyword arguments.

    Parameters
    ----------
    is_active:
        Whether a simulation is currently running.
    simulation_kind:
        One of ``"speculative"``, ``"sandbox"``, or ``"none"``.
    candidate_paths:
        Candidate execution path labels under evaluation.
    committed_path:
        The path committed to (``None`` if still speculative).
    scenario_label:
        Human-readable label for the scenario.
    step_count:
        Number of simulation steps completed.

    Returns
    -------
    SimulationSummary
        Read-only summary suitable for liminal-surface rendering.
    """
    valid_kinds = {"speculative", "sandbox", "none"}
    kind = simulation_kind if simulation_kind in valid_kinds else "none"
    paths = list(candidate_paths) if candidate_paths else []
    is_committed = committed_path is not None

    return SimulationSummary(
        is_active=is_active,
        simulation_kind=kind,
        candidate_paths=paths,
        committed_path=committed_path,
        scenario_label=scenario_label,
        step_count=step_count,
        is_committed=is_committed,
    )


# ---------------------------------------------------------------------------
# Builder: LiminalSpaceMap
# ---------------------------------------------------------------------------


def build_liminal_space_map(
    *,
    local_snapshot_dict: Optional[Dict[str, Any]] = None,
    cross_device_snapshot_dict: Optional[Dict[str, Any]] = None,
    simulation_summary: Optional[SimulationSummary] = None,
) -> LiminalSpaceMap:
    """Build a :class:`LiminalSpaceMap` from the given snapshot dicts.

    This is the canonical entry point for constructing a liminal-space map
    for rendering or audit.  In production, callers should obtain the
    snapshot dicts from the execution chain singletons:

    .. code-block:: python

        from core.local_execution_chain import build_local_chain_snapshot
        from core.cross_device_execution_chain import build_cross_device_chain_snapshot
        from core.liminal_space_mapping import build_liminal_space_map

        local_snap = build_local_chain_snapshot().to_dict()
        cd_snap = build_cross_device_chain_snapshot().to_dict()
        lmap = build_liminal_space_map(
            local_snapshot_dict=local_snap,
            cross_device_snapshot_dict=cd_snap,
        )

    Parameters
    ----------
    local_snapshot_dict:
        Dict from ``LocalChainSnapshot.to_dict()``.  ``None`` → zero-state.
    cross_device_snapshot_dict:
        Dict from ``CrossDeviceChainSnapshot.to_dict()``.  ``None`` → zero-state.
    simulation_summary:
        A pre-built :class:`SimulationSummary`.  ``None`` → inactive summary.

    Returns
    -------
    LiminalSpaceMap
        Composite read-only liminal-space map.
    """
    local_view = build_local_chain_view(local_snapshot_dict)
    cd_view = build_cross_device_chain_view(cross_device_snapshot_dict)
    sim = simulation_summary if simulation_summary is not None else SimulationSummary()

    return LiminalSpaceMap(
        local_chain=local_view,
        cross_device_chain=cd_view,
        simulation_summary=sim,
    )


# ---------------------------------------------------------------------------
# Convenience: get from live singletons
# ---------------------------------------------------------------------------


def get_liminal_space_map(
    simulation_summary: Optional[SimulationSummary] = None,
) -> LiminalSpaceMap:
    """Return a :class:`LiminalSpaceMap` built from the current singleton state.

    Reads live snapshots from :func:`core.local_execution_chain.build_local_chain_snapshot`
    and :func:`core.cross_device_execution_chain.build_cross_device_chain_snapshot`.

    Parameters
    ----------
    simulation_summary:
        Optional pre-built :class:`SimulationSummary`.  ``None`` → inactive.

    Returns
    -------
    LiminalSpaceMap
        Composite read-only liminal-space map reflecting live chain state.
    """
    local_snap_dict: Optional[Dict[str, Any]] = None
    cd_snap_dict: Optional[Dict[str, Any]] = None

    try:
        from core.local_execution_chain import build_local_chain_snapshot
        local_snap_dict = build_local_chain_snapshot().to_dict()
    except Exception as exc:
        logger.debug("Suppressed: %s", exc)

    try:
        from core.cross_device_execution_chain import build_cross_device_chain_snapshot
        cd_snap_dict = build_cross_device_chain_snapshot().to_dict()
    except Exception as exc:
        logger.debug("Suppressed: %s", exc)

    return build_liminal_space_map(
        local_snapshot_dict=local_snap_dict,
        cross_device_snapshot_dict=cd_snap_dict,
        simulation_summary=simulation_summary,
    )
