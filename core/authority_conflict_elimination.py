#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/authority_conflict_elimination.py
========================================
PR-514 — Authority Conflict Elimination.

This module is the **authority conflict elimination layer** for the Galaxy
canonical runtime architecture.  It identifies and eliminates the most
important remaining authority collisions left after PRs #506–#513, so that
the system more consistently answers the question:
**which layer is allowed to say what is true?**

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  OPERATOR INSPECTION / STATUS BOARD / PROJECTION SURFACE        │
    │  status_board_v2  ·  desktop_projection  ·  /api/v1/projection  │
    └────────────────────────────┬─────────────────────────────────────┘
                                 │  AUTHORITY-CONFLICT-FREE BOUNDARIES
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  AUTHORITY CONFLICT ELIMINATION LAYER  (this module, Layer 14)  │
    │                                                                  │
    │  Resolves:                                                       │
    │    • GAP-512-003: enrich_runtime_projection() wired into         │
    │      status-board and runtime-projection assembly paths          │
    │    • GAP-512-005: operator snapshot consumed by status board     │
    │      via canonical OperatorSurface (not raw subsystem reads)     │
    │    • GAP-512-008: desktop projection topology representations     │
    │      annotated as projection-derived (not competing authority)   │
    │                                                                  │
    │  Boundary sentinels:                                             │
    │    • RUNTIME_TRUTH_ENDS_AT_BOUNDARY — where runtime truth stops  │
    │    • OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY — operator scope     │
    │    • PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY            │
    │    • STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY        │
    │                                                                  │
    │  Drift sentinels (preventing silent reintroduction):            │
    │    • NO_COMPETING_TOPOLOGY_TRUTH_POLICY                          │
    │    • NO_COMPETING_OPERATOR_INSPECTION_POLICY                     │
    │    • NO_COMPETING_STATUS_ASSEMBLY_POLICY                         │
    └────────────────────────────┬─────────────────────────────────────┘
                                 │  READS CANONICAL LAYERS
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  RUNTIME TRUTH LAYERS (Layers 6–13)                             │
    │  TaskGraphRuntime · CanonicalTaskRuntime · ReplayFoundation     │
    │  OperatorSurface · CapabilityAssimilation                       │
    │  NetworkTopologyRuntime · ClosureAuditRuntime                   │
    │  FailureDegradedRecoveryRuntime                                 │
    └──────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Runtime truth ends at the canonical layer boundary.**
    Canonical layers (TaskGraphRuntime, OperatorSurface,
    NetworkTopologyRuntime, etc.) are the only sources allowed to assert
    runtime facts (readiness, reachability, task state, executor health).
    Governed by :data:`RUNTIME_TRUTH_ENDS_AT_BOUNDARY`.

2.  **Operator inspection begins at OperatorSurface.**
    All operator inspection flows (REST API, CLI, status board) MUST read
    from :class:`~core.operator_surface.OperatorSurface`.  Direct raw reads
    of internal subsystems by presentation layers are prohibited.
    Governed by :data:`OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY`.

3.  **Projection adapts but does not redefine.**
    Projection layers (RuntimeProjection, DesktopStatusProjection) may
    adapt runtime data for display but MUST NOT invent new runtime truth.
    Bridge enrichment (:func:`~core.projection_surface_bridge.enrich_runtime_projection`)
    is the approved mechanism for adding runtime data to projections.
    Governed by :data:`PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY`.

4.  **Status surfaces display but do not invent authority.**
    Status board surfaces (desktop_projection, status_board_v2) MUST assemble
    payloads from the canonical projection and operator layers.  They must
    not maintain independent state stores that compete with those layers.
    Governed by :data:`STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY`.

5.  **No competing topology truth.**
    Only :class:`~core.network_topology_runtime.NetworkTopologyRuntime` may
    assert device/network topology truth.  ContinuumState/TopologyRoutePlan
    are model-provider routing projections and MUST NOT be used as device
    reachability oracles.
    Governed by :data:`NO_COMPETING_TOPOLOGY_TRUTH_POLICY`.

6.  **No competing operator inspection.**
    Only :class:`~core.operator_surface.OperatorSurface` may serve as the
    operator inspection authority.  Bypass paths that read raw runtime
    subsystems directly in presentation/API code are prohibited.
    Governed by :data:`NO_COMPETING_OPERATOR_INSPECTION_POLICY`.

7.  **No competing status assembly.**
    Status board payloads MUST be assembled via the bridge-enriched
    projection stack.  Independent assembly paths producing equivalent
    payloads from different sources are prohibited.
    Governed by :data:`NO_COMPETING_STATUS_ASSEMBLY_POLICY`.

Public API
----------
Authority sentinels::

    AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY
    AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION
    AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED

Semantic boundary sentinels::

    RUNTIME_TRUTH_ENDS_AT_BOUNDARY
    OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY
    PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY
    STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY

Drift-prevention policy sentinels::

    NO_COMPETING_TOPOLOGY_TRUTH_POLICY
    NO_COMPETING_OPERATOR_INSPECTION_POLICY
    NO_COMPETING_STATUS_ASSEMBLY_POLICY

Conflict resolution record::

    ConflictResolutionKind
    ConflictResolutionRecord
    AuthorityEliminationSnapshot

Runtime class::

    AuthorityConflictEliminationRuntime
    get_authority_conflict_elimination_runtime()
    reset_authority_conflict_elimination_runtime()

Helpers::

    enrich_projection_with_runtime_authority(projection_dict) -> dict
    build_authority_elimination_snapshot() -> AuthorityEliminationSnapshot
    assert_no_competing_authority(layer_name, fact_name, canonical_source)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.AuthorityConflictElimination")

# ===========================================================================
# Module-level authority / policy sentinels
# ===========================================================================

#: Authority sentinel for this module.  Import-verified by closure audit.
AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY: str = (
    "AUTHORITY_CONFLICT_ELIMINATION::AUTHORITY_V1: "
    "core/authority_conflict_elimination.py is the canonical layer for "
    "identifying, documenting, and preventing authority conflicts in the "
    "Galaxy runtime.  Layer 14."
)

#: Numeric layer position in the Galaxy runtime stack.
AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION: int = 14

# ---------------------------------------------------------------------------
# Semantic boundary sentinels (PR-514 required outcome #3)
# ---------------------------------------------------------------------------

#: Documents where runtime truth ends.
RUNTIME_TRUTH_ENDS_AT_BOUNDARY: str = (
    "RUNTIME_TRUTH_ENDS_AT_BOUNDARY_V1: "
    "Runtime truth ends at the canonical layer boundary. "
    "Only TaskGraphRuntime, OperatorSurface, NetworkTopologyRuntime, "
    "CapabilityAssimilationLayer, ReplayFoundation, AuditEventSemantics, "
    "FailureDegradedRecoveryRuntime, and ClosureAuditRuntime may assert "
    "runtime facts (readiness, reachability, task state, executor health). "
    "Projection/status surfaces MUST read from these layers, never invent "
    "parallel truth."
)

#: Documents where operator inspection begins.
OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY: str = (
    "OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY_V1: "
    "Operator inspection begins at OperatorSurface (core/operator_surface.py). "
    "All operator inspection flows — REST API (core/routes/operator.py), "
    "CLI (cli/operator_inspect.py), and status board surfaces — MUST read "
    "exclusively from OperatorSurface.  Direct reads of raw runtime "
    "subsystems (TaskGraphRuntime, ReplayFoundation, etc.) in presentation "
    "code are prohibited per PR-510 discipline."
)

#: Documents where projection adapts without redefining truth.
PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY: str = (
    "PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY_V1: "
    "Projection layers (RuntimeProjection, DesktopStatusProjection, "
    "TopologyRoutePlan, ContinuumState) may adapt, transform, and display "
    "runtime data but MUST NOT assert new runtime facts.  "
    "enrich_runtime_projection() from ProjectionSurfaceBridge (PR-511) is "
    "the approved mechanism for adding canonical runtime data to projections "
    "without overwriting projection-derived fields."
)

#: Documents where status surfaces display without inventing authority.
STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY: str = (
    "STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY_V1: "
    "Status board surfaces (desktop_projection, status_board_v2, "
    "GET /api/v1/projection/runtime, GET /api/v1/projection/desktop-status-board) "
    "assemble payloads for display only.  They MUST consume from the "
    "canonical projection stack (enriched by ProjectionSurfaceBridge) and "
    "the OperatorSurface.  They MUST NOT maintain independent state stores "
    "that compete with canonical layers.  "
    "Resolves GAP-512-003 and GAP-512-005."
)

# ---------------------------------------------------------------------------
# Drift-prevention policy sentinels (PR-514 required outcome #4)
# ---------------------------------------------------------------------------

#: Prevents silent reintroduction of competing topology truth paths.
NO_COMPETING_TOPOLOGY_TRUTH_POLICY: str = (
    "NO_COMPETING_TOPOLOGY_TRUTH_POLICY_V1: "
    "Only NetworkTopologyRuntime (core/network_topology_runtime.py) may "
    "assert device/network topology truth (reachability, transport paths, "
    "connectivity state).  ContinuumState and TopologyRoutePlan are "
    "model-provider routing projections; they MUST NOT be used as oracles "
    "for device reachability.  Any new code that derives topology truth "
    "independently of NetworkTopologyRuntime constitutes a prohibited "
    "authority conflict.  Resolves GAP-512-008."
)

#: Prevents silent reintroduction of competing operator inspection paths.
NO_COMPETING_OPERATOR_INSPECTION_POLICY: str = (
    "NO_COMPETING_OPERATOR_INSPECTION_POLICY_V1: "
    "Only OperatorSurface (core/operator_surface.py) may serve as the "
    "operator inspection authority.  Presentation and API layers that read "
    "raw runtime subsystems directly (bypassing OperatorSurface) introduce "
    "a competing inspection path and are prohibited.  "
    "Resolves GAP-512-005."
)

#: Prevents silent reintroduction of competing status-board assembly.
NO_COMPETING_STATUS_ASSEMBLY_POLICY: str = (
    "NO_COMPETING_STATUS_ASSEMBLY_POLICY_V1: "
    "Status board payloads (desktop status board, runtime projection) MUST "
    "be assembled via the bridge-enriched projection stack "
    "(ProjectionSurfaceBridge.enrich_runtime_projection).  Independent "
    "assembly paths that build equivalent payloads from different source "
    "layers are prohibited competing-truth paths.  "
    "Resolves GAP-512-003."
)

#: Integration sentinel — verifiable by closure audit.
AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED: str = (
    "AUTHORITY_CONFLICT_ELIMINATION::INTEGRATED_V1: "
    "PR-514 authority conflict elimination is wired into "
    "core/routes/projection.py (_assemble_projection, "
    "_assemble_desktop_status_board_payload) via enrich_runtime_projection "
    "from ProjectionSurfaceBridge (resolves GAP-512-003 and GAP-512-005). "
    "Semantic boundary and drift-prevention sentinels are established "
    "for GAP-512-008."
)

__all__ = [
    # Authority / policy sentinels
    "AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY",
    "AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION",
    "AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED",
    # Semantic boundary sentinels
    "RUNTIME_TRUTH_ENDS_AT_BOUNDARY",
    "OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY",
    "PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY",
    "STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY",
    # Drift-prevention policy sentinels
    "NO_COMPETING_TOPOLOGY_TRUTH_POLICY",
    "NO_COMPETING_OPERATOR_INSPECTION_POLICY",
    "NO_COMPETING_STATUS_ASSEMBLY_POLICY",
    # Enums
    "ConflictResolutionKind",
    # Dataclasses
    "ConflictResolutionRecord",
    "AuthorityEliminationSnapshot",
    # Runtime class
    "AuthorityConflictEliminationRuntime",
    "get_authority_conflict_elimination_runtime",
    "reset_authority_conflict_elimination_runtime",
    # Helpers
    "enrich_projection_with_runtime_authority",
    "build_authority_elimination_snapshot",
    "assert_no_competing_authority",
]

# ===========================================================================
# Enums
# ===========================================================================

_RING_BUFFER_SIZE = 256


class ConflictResolutionKind(str, Enum):
    """Describes how an authority conflict was resolved.

    Values
    ------
    NARROWED:
        One competing truth path was narrowed (scope reduced, not removed).
    ELIMINATED:
        A competing truth path was fully removed in favour of the canonical one.
    BRIDGED:
        A non-destructive bridge was established so one layer enriches from
        the canonical layer without replacing it.
    ANNOTATED:
        The conflict is documented with boundary sentinels to prevent drift,
        but the two representations serve genuinely distinct purposes.
    DEFERRED:
        Resolution deferred to a future PR with documented rationale.
    """

    NARROWED = "narrowed"
    ELIMINATED = "eliminated"
    BRIDGED = "bridged"
    ANNOTATED = "annotated"
    DEFERRED = "deferred"


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class ConflictResolutionRecord:
    """Documents the resolution of a single authority conflict.

    Attributes
    ----------
    conflict_id:
        Stable identifier (e.g. ``"CONFLICT-002"`` from PR-512).
    gap_id:
        Related residual gap from PR-512 (e.g. ``"GAP-512-003"``).
    runtime_fact:
        The runtime fact that had competing truth sources.
    canonical_layer:
        The layer established as the single authoritative source.
    competing_layer:
        The layer that previously competed or potentially competed.
    resolution_kind:
        How the conflict was resolved (see :class:`ConflictResolutionKind`).
    resolution_note:
        Human-readable description of what was done.
    resolved_in_pr:
        The PR that resolved this conflict.
    resolved_at:
        UNIX timestamp when this record was created.
    """

    conflict_id: str
    gap_id: str = ""
    runtime_fact: str = ""
    canonical_layer: str = ""
    competing_layer: str = ""
    resolution_kind: ConflictResolutionKind = ConflictResolutionKind.NARROWED
    resolution_note: str = ""
    resolved_in_pr: str = "PR-514"
    resolved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "gap_id": self.gap_id,
            "runtime_fact": self.runtime_fact,
            "canonical_layer": self.canonical_layer,
            "competing_layer": self.competing_layer,
            "resolution_kind": self.resolution_kind.value
            if hasattr(self.resolution_kind, "value")
            else str(self.resolution_kind),
            "resolution_note": self.resolution_note,
            "resolved_in_pr": self.resolved_in_pr,
            "resolved_at": self.resolved_at,
        }


@dataclass
class AuthorityEliminationSnapshot:
    """Point-in-time snapshot of authority conflict elimination state.

    Attributes
    ----------
    resolution_records:
        All :class:`ConflictResolutionRecord` entries documented in this
        module.
    assertion_violations:
        Any competing-authority assertion violations recorded at runtime
        (see :func:`assert_no_competing_authority`).
    total_conflicts_resolved:
        Count of conflicts documented as resolved.
    total_assertion_violations:
        Count of runtime violations logged (should be zero in production).
    snapshot_at:
        UNIX timestamp of this snapshot.
    """

    resolution_records: List[ConflictResolutionRecord] = field(default_factory=list)
    assertion_violations: List[Dict[str, Any]] = field(default_factory=list)
    total_conflicts_resolved: int = 0
    total_assertion_violations: int = 0
    snapshot_at: float = field(default_factory=time.time)

    def summary(self) -> Dict[str, Any]:
        return {
            "total_conflicts_resolved": self.total_conflicts_resolved,
            "total_assertion_violations": self.total_assertion_violations,
            "resolution_records_count": len(self.resolution_records),
            "assertion_violations_count": len(self.assertion_violations),
            "snapshot_at": self.snapshot_at,
        }


# ===========================================================================
# Documented conflict resolutions
# ===========================================================================

_CONFLICT_RESOLUTIONS: List[Dict[str, Any]] = [
    {
        "conflict_id": "CONFLICT-002",
        "gap_id": "GAP-512-003",
        "runtime_fact": "network topology / device reachability",
        "canonical_layer": "core.network_topology_runtime.NetworkTopologyRuntime",
        "competing_layer": (
            "ContinuumState / TopologyRoutePlan (projection stack) — "
            "status board assembly via _assemble_desktop_status_board_payload()"
        ),
        "resolution_kind": ConflictResolutionKind.BRIDGED,
        "resolution_note": (
            "PR-514 wires enrich_runtime_projection() (from ProjectionSurfaceBridge, "
            "PR-511) into _assemble_projection() and "
            "_assemble_desktop_status_board_payload() in core/routes/projection.py. "
            "The bridge reads from OperatorSurface (which reads "
            "NetworkTopologyRuntime), adding canonical runtime data to projections "
            "without overwriting projection-derived fields.  "
            "Boundary sentinel PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY "
            "and drift policy NO_COMPETING_TOPOLOGY_TRUTH_POLICY prevent "
            "reintroduction.  Resolves GAP-512-003."
        ),
        "resolved_in_pr": "PR-514",
    },
    {
        "conflict_id": "CONFLICT-005-STATUS",
        "gap_id": "GAP-512-005",
        "runtime_fact": "operator runtime snapshot / executor health",
        "canonical_layer": "core.operator_surface.OperatorSurface",
        "competing_layer": (
            "desktop_projection / status_board_v2 assembly paths "
            "that build their own runtime view without consuming OperatorSurface"
        ),
        "resolution_kind": ConflictResolutionKind.BRIDGED,
        "resolution_note": (
            "PR-514 ensures the status board's runtime projection assembly path "
            "consumes enrich_runtime_projection(), which reads OperatorSurface via "
            "ProjectionSurfaceBridge.get_runtime_augmentation().  The "
            "operator_snapshot_dict field in RuntimeAugmentation carries the "
            "canonical OperatorSurface snapshot into the projection payload.  "
            "Boundary sentinels OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY and "
            "STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY, plus drift "
            "policy NO_COMPETING_OPERATOR_INSPECTION_POLICY, prevent reintroduction.  "
            "Resolves GAP-512-005."
        ),
        "resolved_in_pr": "PR-514",
    },
    {
        "conflict_id": "CONFLICT-008-TOPOLOGY",
        "gap_id": "GAP-512-008",
        "runtime_fact": "desktop projection topology representation",
        "canonical_layer": "core.network_topology_runtime.NetworkTopologyRuntime",
        "competing_layer": (
            "ContinuumState / DesktopStatusProjection topology representations "
            "in desktop_projection / status_board_v2"
        ),
        "resolution_kind": ConflictResolutionKind.ANNOTATED,
        "resolution_note": (
            "PR-514 establishes boundary sentinel NO_COMPETING_TOPOLOGY_TRUTH_POLICY "
            "and documents that ContinuumState/TopologyRoutePlan are "
            "model-provider routing projections, not device/network topology truth. "
            "They serve a genuinely distinct semantic domain "
            "(GAP-512-009: model-provider topology is deferred to PR-515). "
            "The drift-prevention sentinel makes future authority conflicts detectable. "
            "Full decommission of competing topology paths deferred to PR-515 per "
            "GAP-512-009 rationale.  Resolves GAP-512-008 semantics boundary."
        ),
        "resolved_in_pr": "PR-514",
    },
]


# ===========================================================================
# Runtime singleton
# ===========================================================================


class AuthorityConflictEliminationRuntime:
    """Singleton runtime for authority conflict elimination tracking.

    This class maintains:
    - The static catalog of documented conflict resolutions.
    - A ring-buffer log of runtime assertion violations (should be empty
      in a correctly configured system).

    **Read-only with respect to canonical layers.**  This class does not
    write to TaskGraphRuntime, OperatorSurface, or any other canonical
    layer.  It only tracks conflict elimination metadata.
    """

    def __init__(self) -> None:
        self._violation_log: Deque[Dict[str, Any]] = deque(
            maxlen=_RING_BUFFER_SIZE
        )
        self._lock = threading.Lock()
        self._total_violations = 0
        logger.debug(
            "AuthorityConflictEliminationRuntime: initialised "
            "(layer=%d, conflicts=%d)",
            AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION,
            len(_CONFLICT_RESOLUTIONS),
        )

    # -----------------------------------------------------------------------
    # Resolution catalog
    # -----------------------------------------------------------------------

    def get_resolution_records(self) -> List[ConflictResolutionRecord]:
        """Return all documented conflict resolution records.

        Returns
        -------
        List[ConflictResolutionRecord]
            Static catalog of all conflicts resolved in PR-514.
        """
        records = []
        for entry in _CONFLICT_RESOLUTIONS:
            records.append(
                ConflictResolutionRecord(
                    conflict_id=entry["conflict_id"],
                    gap_id=entry.get("gap_id", ""),
                    runtime_fact=entry.get("runtime_fact", ""),
                    canonical_layer=entry.get("canonical_layer", ""),
                    competing_layer=entry.get("competing_layer", ""),
                    resolution_kind=entry.get(
                        "resolution_kind", ConflictResolutionKind.NARROWED
                    ),
                    resolution_note=entry.get("resolution_note", ""),
                    resolved_in_pr=entry.get("resolved_in_pr", "PR-514"),
                )
            )
        return records

    # -----------------------------------------------------------------------
    # Assertion violation tracking
    # -----------------------------------------------------------------------

    def record_assertion_violation(
        self,
        layer_name: str,
        fact_name: str,
        canonical_source: str,
        message: str = "",
    ) -> None:
        """Record a runtime competing-authority assertion violation.

        Call this when code detects that a fact is being produced by a layer
        other than the canonical source (see :func:`assert_no_competing_authority`).

        Parameters
        ----------
        layer_name:
            The layer that is asserting the fact (should not be).
        fact_name:
            The runtime fact being asserted outside its canonical source.
        canonical_source:
            The canonical layer that should be the single source for this fact.
        message:
            Optional human-readable context.
        """
        violation = {
            "layer_name": layer_name,
            "fact_name": fact_name,
            "canonical_source": canonical_source,
            "message": message,
            "detected_at": time.time(),
        }
        with self._lock:
            self._violation_log.append(violation)
            self._total_violations += 1
        logger.warning(
            "AuthorityConflictElimination: competing-authority violation — "
            "layer=%r fact=%r canonical=%r",
            layer_name,
            fact_name,
            canonical_source,
        )

    def get_violation_log(self) -> List[Dict[str, Any]]:
        """Return a snapshot of the assertion violation ring buffer.

        Returns
        -------
        List[dict]
            Recent violation entries (up to 256).
        """
        with self._lock:
            return list(self._violation_log)

    # -----------------------------------------------------------------------
    # Snapshot
    # -----------------------------------------------------------------------

    def build_snapshot(self) -> AuthorityEliminationSnapshot:
        """Build an :class:`AuthorityEliminationSnapshot`.

        Returns
        -------
        AuthorityEliminationSnapshot
            Current state of conflict resolutions and assertion violations.
        """
        resolution_records = self.get_resolution_records()
        violations = self.get_violation_log()
        return AuthorityEliminationSnapshot(
            resolution_records=resolution_records,
            assertion_violations=violations,
            total_conflicts_resolved=len(resolution_records),
            total_assertion_violations=self._total_violations,
            snapshot_at=time.time(),
        )


# ===========================================================================
# Singleton management
# ===========================================================================

_SINGLETON: Optional[AuthorityConflictEliminationRuntime] = None
_SINGLETON_LOCK = threading.Lock()


def get_authority_conflict_elimination_runtime() -> (
    AuthorityConflictEliminationRuntime
):
    """Return the global :class:`AuthorityConflictEliminationRuntime` singleton."""
    global _SINGLETON  # noqa: PLW0603
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = AuthorityConflictEliminationRuntime()
    return _SINGLETON


def reset_authority_conflict_elimination_runtime() -> None:
    """Reset the singleton (for testing only)."""
    global _SINGLETON  # noqa: PLW0603
    _SINGLETON = None


# ===========================================================================
# Public helper functions
# ===========================================================================


def enrich_projection_with_runtime_authority(
    projection_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich *projection_dict* with canonical runtime authority data.

    This is the PR-514 resolution for GAP-512-003 and GAP-512-005.
    It calls :func:`~core.projection_surface_bridge.enrich_runtime_projection`
    from the ProjectionSurfaceBridge (PR-511), which reads from
    :class:`~core.operator_surface.OperatorSurface` and other canonical
    runtime layers.

    This function is the approved path for status board and projection
    route handlers to add canonical runtime data without inventing new truth.

    Parameters
    ----------
    projection_dict:
        A dict representation of a RuntimeProjection or
        DesktopStatusProjection (as returned by ``.to_dict()``).

    Returns
    -------
    dict
        A new dict that is a copy of *projection_dict* with runtime
        augmentation fields added.  The original is not mutated.
        Falls back to the original dict if the bridge is unavailable.

    Notes
    -----
    Per :data:`PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY`:
    Projection-derived fields are never overwritten.  Only runtime-augmented
    fields (``active_task_count``, ``executor_count``,
    ``network_reachable_node_count``, ``replay_event_count``,
    ``operator_snapshot_dict``, ``task_graph_snapshot_dict``) are added
    when not already present.
    """
    try:
        from core.projection_surface_bridge import (
            enrich_runtime_projection,
        )
        return enrich_runtime_projection(projection_dict)
    except Exception as exc:  # pragma: no cover
        logger.debug(
            "enrich_projection_with_runtime_authority: enrichment unavailable "
            "(bridge import or enrichment error), returning original dict: %s",
            exc,
        )
        return dict(projection_dict)


def build_authority_elimination_snapshot() -> AuthorityEliminationSnapshot:
    """Return a snapshot of authority conflict elimination state.

    Convenience wrapper around
    :meth:`AuthorityConflictEliminationRuntime.build_snapshot`.
    """
    return get_authority_conflict_elimination_runtime().build_snapshot()


def assert_no_competing_authority(
    layer_name: str,
    fact_name: str,
    canonical_source: str,
) -> None:
    """Assert that no competing authority exists for *fact_name*.

    This function is a **drift-prevention sentinel**.  Call it from tests or
    guards that verify a specific runtime fact is only sourced from
    *canonical_source*.

    If a violation is detected (i.e. this function is called from a layer
    other than the canonical source), the violation is logged via
    :meth:`AuthorityConflictEliminationRuntime.record_assertion_violation`
    and a warning is emitted.  The function does NOT raise; it is non-blocking
    per the Galaxy governance pattern.

    In tests, inspect the violation log via :func:`build_authority_elimination_snapshot`
    to assert zero violations.

    Parameters
    ----------
    layer_name:
        The name of the calling layer (passed by the caller for identification).
    fact_name:
        The runtime fact being asserted (e.g. ``"device_reachability"``).
    canonical_source:
        The expected canonical layer for this fact
        (e.g. ``"NetworkTopologyRuntime"``).
    """
    runtime = get_authority_conflict_elimination_runtime()
    if layer_name != canonical_source:
        runtime.record_assertion_violation(
            layer_name=layer_name,
            fact_name=fact_name,
            canonical_source=canonical_source,
            message=(
                f"Layer '{layer_name}' is asserting fact '{fact_name}' "
                f"but canonical source is '{canonical_source}'."
            ),
        )
