#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/legacy_system_decommission.py
====================================
PR-516 — Legacy / Parallel System Decommission Sweep.

This module is the **formal decommission authority** for legacy and parallel
system paths that can still confuse authority, reintroduce drift, or silently
bypass the canonical mainline architecture established in PRs #506–#515.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  OPERATOR / PROJECTION / STATUS SURFACES                            │
    └────────────────────────────┬────────────────────────────────────────┘
                                 │  DECOMMISSION-GATED EVIDENCE
                                 ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  LEGACY SYSTEM DECOMMISSION LAYER  (this module, Layer 16)         │
    │                                                                     │
    │  Decommissions (formal gating + retirement markers):               │
    │    • Legacy CapabilityRegistry parallel to CapabilityAssimilation  │
    │    • Legacy TaskRouter / TaskScheduler parallel to CommandRouter   │
    │    • Legacy TaskDecomposer / IntelligentTaskPlanner parallel to    │
    │      canonical TaskGraph                                           │
    │    • Legacy LocalAgentRuntime as server-side planner               │
    │    • Legacy dashboard-era direct projection contracts              │
    │    • Legacy envelope-first (pre-spine) ingress paths               │
    │                                                                     │
    │  Closes:                                                            │
    │    • CONFLICT-003: executor readiness — CapabilityAssimilationLayer│
    │      vs legacy CapabilityRegistry                                  │
    │    • CONFLICT-009: task decomposition — canonical TaskGraph vs     │
    │      legacy TaskDecomposer/IntelligentTaskPlanner                  │
    │    • CONFLICT-010: projection contract — canonical projection      │
    │      bridge vs legacy dashboard-era direct payload contracts       │
    │                                                                     │
    │  Adds:                                                              │
    │    • DecommissionedPathKind enum (6 path categories)               │
    │    • DecommissionStatus enum (RETIRED/GATED/RESIDUAL)              │
    │    • DecommissionEntry dataclass                                    │
    │    • DecommissionSnapshot dataclass                                 │
    │    • LegacySystemDecommissionRuntime singleton (256-entry ring buf)│
    │    • record_decommission_activation() helper (non-blocking)        │
    │    • assert_path_not_active() guard helper                         │
    │    • snapshot_decommission() module-level helper                   │
    │                                                                     │
    │  Policy sentinels:                                                  │
    │    • CANONICAL_CAPABILITY_SOURCE_POLICY                            │
    │    • CANONICAL_DECOMPOSITION_PATH_POLICY                           │
    │    • CANONICAL_PROJECTION_CONTRACT_POLICY                          │
    │    • NO_PARALLEL_DISPATCH_AUTHORITY_POLICY                         │
    │    • DECOMMISSION_NON_REGRESSION_POLICY                            │
    └────────────────────────────┬────────────────────────────────────────┘
                                 │  READS CANONICAL LAYERS 6–15
                                 ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  RUNTIME TRUTH LAYERS (Layers 6–15)                                │
    │  TaskGraphRuntime · CanonicalTaskRuntime · ReplayFoundation        │
    │  AuditEventSemantics · OperatorSurface                             │
    │  CapabilityAssimilationLayer · NetworkTopologyRuntime              │
    │  ClosureAuditRuntime · FailureDegradedRecoveryRuntime              │
    │  AuthorityConflictEliminationRuntime · CriticalPathHarnessRuntime  │
    └─────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Decommission layer is audit-only.**
    This module gates and records legacy path activations.  It MUST NOT
    write task state, trigger dispatch, or alter routing decisions.
    Governed by :data:`DECOMMISSION_AUDIT_ONLY_POLICY`.

2.  **Canonical capability source is CapabilityAssimilationLayer.**
    All executor-readiness and capability-set queries MUST read from
    ``core.capability_assimilation.CapabilityAssimilationLayer``.  The legacy
    ``galaxy_gateway.capability_registry.CapabilityRegistry`` is formally
    retired as a parallel authority.
    Governed by :data:`CANONICAL_CAPABILITY_SOURCE_POLICY`.

3.  **Canonical task decomposition is TaskGraph.**
    All task-splitting logic MUST go through ``core.task_graph.TaskGraph``.
    The legacy ``galaxy_gateway.task_decomposer.TaskDecomposer`` and
    ``IntelligentTaskPlanner`` are formally demoted to compatibility shims.
    Governed by :data:`CANONICAL_DECOMPOSITION_PATH_POLICY`.

4.  **Canonical projection contract is ProjectionSurfaceBridge.**
    Status board and desktop projection surfaces MUST consume
    ``core.projection_surface_bridge.ProjectionSurfaceBridge``.
    Legacy direct payload contracts (dashboard-era) must not be used
    as the primary projection assembly authority.
    Governed by :data:`CANONICAL_PROJECTION_CONTRACT_POLICY`.

5.  **No parallel dispatch authority.**
    All task dispatch MUST flow through
    ``core.command_router.CommandRouter.route_envelope()``.
    Legacy routing helpers (TaskRouter, TaskScheduler) are formally
    retired from dispatch authority.
    Governed by :data:`NO_PARALLEL_DISPATCH_AUTHORITY_POLICY`.

6.  **Non-regression policy — retired paths must not silently regain control.**
    Tests MUST assert that each retired path is present in the
    decommission catalog and has status RETIRED or GATED.
    Governed by :data:`DECOMMISSION_NON_REGRESSION_POLICY`.

Public API
----------
Authority sentinels::

    LEGACY_SYSTEM_DECOMMISSION_AUTHORITY
    LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION
    LEGACY_SYSTEM_DECOMMISSION_INTEGRATED

Policy sentinels::

    DECOMMISSION_AUDIT_ONLY_POLICY
    CANONICAL_CAPABILITY_SOURCE_POLICY
    CANONICAL_DECOMPOSITION_PATH_POLICY
    CANONICAL_PROJECTION_CONTRACT_POLICY
    NO_PARALLEL_DISPATCH_AUTHORITY_POLICY
    DECOMMISSION_NON_REGRESSION_POLICY

Enumerations::

    DecommissionedPathKind
    DecommissionStatus

Dataclasses::

    DecommissionEntry
    DecommissionActivationRecord
    DecommissionSnapshot

Class::

    LegacySystemDecommissionRuntime

Module-level helpers::

    get_legacy_system_decommission_runtime() -> LegacySystemDecommissionRuntime
    reset_legacy_system_decommission_runtime() -> None
    record_decommission_activation(path_id, caller, reason) -> None
    assert_path_not_active(path_id, caller) -> None
    get_decommission_catalog() -> List[DecommissionEntry]
    snapshot_decommission() -> DecommissionSnapshot
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.LegacySystemDecommission")

# ===========================================================================
# Module-level authority / policy sentinels
# ===========================================================================

#: Authority sentinel — import-verified by closure audit.
LEGACY_SYSTEM_DECOMMISSION_AUTHORITY: str = (
    "LEGACY_SYSTEM_DECOMMISSION::AUTHORITY_V1: "
    "core/legacy_system_decommission.py is the formal decommission layer "
    "for legacy and parallel system paths in the Galaxy canonical runtime. "
    "Layer 16 — above CriticalPathHarness (Layer 15). "
    "Closes CONFLICT-003, CONFLICT-009, CONFLICT-010."
)

#: Layer position in the canonical authority stack.
LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION: int = 16

#: Integration sentinel — verifiable by closure audit and tests.
LEGACY_SYSTEM_DECOMMISSION_INTEGRATED: str = (
    "LEGACY_SYSTEM_DECOMMISSION::INTEGRATED_V1: "
    "PR-516 decommission sweep formally retires / gates: "
    "galaxy_gateway.capability_registry (CONFLICT-003), "
    "galaxy_gateway.task_decomposer (CONFLICT-009), "
    "legacy dashboard-era projection contracts (CONFLICT-010), "
    "galaxy_gateway.task_router.TaskRouter / TaskScheduler (dispatch authority), "
    "core.local_agent_runtime.LocalAgentRuntime (server-side planner). "
    "Canonical replacements: CapabilityAssimilationLayer, TaskGraph, "
    "ProjectionSurfaceBridge, CommandRouter."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

#: This module gates and records legacy path activations only.
DECOMMISSION_AUDIT_ONLY_POLICY: str = (
    "DECOMMISSION_AUDIT_ONLY_V1: "
    "LegacySystemDecommissioner MUST NOT write task state, trigger "
    "dispatch, or alter routing decisions.  It is a gating and "
    "recording layer only."
)

#: Canonical capability source is CapabilityAssimilationLayer.
CANONICAL_CAPABILITY_SOURCE_POLICY: str = (
    "CANONICAL_CAPABILITY_SOURCE_V1: "
    "All executor-readiness and capability-set queries MUST read from "
    "core.capability_assimilation.CapabilityAssimilationLayer.  "
    "galaxy_gateway.capability_registry.CapabilityRegistry is formally "
    "retired as a parallel capability authority.  "
    "Closes CONFLICT-003."
)

#: Canonical task decomposition is TaskGraph.
CANONICAL_DECOMPOSITION_PATH_POLICY: str = (
    "CANONICAL_DECOMPOSITION_PATH_V1: "
    "All task-splitting and sub-task creation MUST go through "
    "core.task_graph.TaskGraph.  "
    "galaxy_gateway.task_decomposer.TaskDecomposer and "
    "IntelligentTaskPlanner are formally demoted to compatibility shims "
    "that MUST NOT create TaskGraph-bypassing sub-task graphs.  "
    "Closes CONFLICT-009."
)

#: Canonical projection contract is ProjectionSurfaceBridge.
CANONICAL_PROJECTION_CONTRACT_POLICY: str = (
    "CANONICAL_PROJECTION_CONTRACT_V1: "
    "Status board and desktop projection surfaces MUST consume "
    "core.projection_surface_bridge.ProjectionSurfaceBridge as the "
    "primary runtime enrichment source.  "
    "Legacy dashboard-era direct payload construction (building runtime "
    "snapshots independently of ProjectionSurfaceBridge) is retired.  "
    "Closes CONFLICT-010."
)

#: No parallel dispatch authority — all dispatch through CommandRouter.
NO_PARALLEL_DISPATCH_AUTHORITY_POLICY: str = (
    "NO_PARALLEL_DISPATCH_AUTHORITY_V1: "
    "All task dispatch MUST flow through "
    "core.command_router.CommandRouter.route_envelope(). "
    "galaxy_gateway.task_router.TaskRouter and TaskScheduler are "
    "formally retired from top-level dispatch authority.  "
    "New code MUST NOT call TaskRouter or TaskScheduler directly."
)

#: Retired paths must not silently regain control.
DECOMMISSION_NON_REGRESSION_POLICY: str = (
    "DECOMMISSION_NON_REGRESSION_V1: "
    "Tests MUST assert that each retired path is present in the "
    "decommission catalog with status RETIRED or GATED.  "
    "Any re-introduction of a retired path MUST produce a failing test."
)

__all__ = [
    # Authority / policy sentinels
    "LEGACY_SYSTEM_DECOMMISSION_AUTHORITY",
    "LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION",
    "LEGACY_SYSTEM_DECOMMISSION_INTEGRATED",
    "DECOMMISSION_AUDIT_ONLY_POLICY",
    "CANONICAL_CAPABILITY_SOURCE_POLICY",
    "CANONICAL_DECOMPOSITION_PATH_POLICY",
    "CANONICAL_PROJECTION_CONTRACT_POLICY",
    "NO_PARALLEL_DISPATCH_AUTHORITY_POLICY",
    "DECOMMISSION_NON_REGRESSION_POLICY",
    # Enums
    "DecommissionedPathKind",
    "DecommissionStatus",
    # Dataclasses
    "DecommissionEntry",
    "DecommissionActivationRecord",
    "DecommissionSnapshot",
    # Singleton
    "LegacySystemDecommissionRuntime",
    "get_legacy_system_decommission_runtime",
    "reset_legacy_system_decommission_runtime",
    # Helpers
    "record_decommission_activation",
    "assert_path_not_active",
    "get_decommission_catalog",
    "snapshot_decommission",
]

# ===========================================================================
# Constants
# ===========================================================================

_RING_BUFFER_SIZE: int = 256

# ===========================================================================
# Enums
# ===========================================================================


class DecommissionedPathKind(str, Enum):
    """Category of a decommissioned legacy / parallel path.

    Each value represents a class of legacy path that has been formally
    retired, gated, or demoted in PR-516.
    """

    CAPABILITY_REGISTRY = "capability_registry"
    """Legacy in-gateway capability stores that parallel CapabilityAssimilationLayer."""

    TASK_DECOMPOSER = "task_decomposer"
    """Legacy task-splitting helpers that bypass the canonical TaskGraph."""

    DISPATCH_AUTHORITY = "dispatch_authority"
    """Legacy routers/schedulers that parallel CommandRouter dispatch authority."""

    AGENT_PLANNER = "agent_planner"
    """Legacy server-side planning components that pre-date the canonical pipeline."""

    PROJECTION_CONTRACT = "projection_contract"
    """Legacy dashboard-era direct projection contracts that bypass ProjectionSurfaceBridge."""

    ENVELOPE_INGRESS = "envelope_ingress"
    """Legacy pre-spine ingress paths that bypass the canonical execution spine."""


class DecommissionStatus(str, Enum):
    """Formal decommission status of a legacy path.

    ``RETIRED``
        Path has been formally retired.  No new code should use it.
        It is kept only for backward-compatibility with existing callers
        that cannot be migrated in this PR.

    ``GATED``
        Path is still used but gated behind an explicit compatibility
        boundary.  Any invocation is recorded in the ring buffer so that
        silent reactivation is detectable.

    ``RESIDUAL``
        Path is acknowledged as still active for legitimate reasons
        (e.g., device-side execution sandbox).  It is documented here
        so future cleanup work does not have to rediscover it.
    """

    RETIRED = "retired"
    GATED = "gated"
    RESIDUAL = "residual"


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class DecommissionEntry:
    """A single entry in the legacy system decommission catalog.

    Attributes
    ----------
    path_id:
        Stable dotted identifier for this legacy path (never reused).
    kind:
        :class:`DecommissionedPathKind` category.
    status:
        :class:`DecommissionStatus` — RETIRED, GATED, or RESIDUAL.
    canonical_replacement:
        Module path of the canonical replacement that supersedes this path.
    reason:
        Human-readable explanation of why this path is decommissioned.
    conflict_closed:
        CONFLICT-* identifier closed by this decommission (if any).
    pr_origin:
        PR that originally created this path.
    pr_decommission:
        PR that formally decommissioned this path.
    notes:
        Additional notes for future cleanup work.
    """

    path_id: str = ""
    kind: DecommissionedPathKind = DecommissionedPathKind.DISPATCH_AUTHORITY
    status: DecommissionStatus = DecommissionStatus.RETIRED
    canonical_replacement: str = ""
    reason: str = ""
    conflict_closed: str = ""
    pr_origin: str = ""
    pr_decommission: str = "PR-516"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "canonical_replacement": self.canonical_replacement,
            "reason": self.reason,
            "conflict_closed": self.conflict_closed,
            "pr_origin": self.pr_origin,
            "pr_decommission": self.pr_decommission,
            "notes": self.notes,
        }


@dataclass
class DecommissionActivationRecord:
    """Record of a legacy path activation attempt intercepted by this layer.

    Created by :func:`record_decommission_activation` and
    :func:`assert_path_not_active` when a decommissioned path is invoked.

    Attributes
    ----------
    record_id:
        Monotonically increasing record identifier.
    path_id:
        The decommissioned path that was activated.
    caller:
        Module/function that invoked the decommissioned path.
    reason:
        Why the invocation was triggered (debugging information).
    status:
        :class:`DecommissionStatus` of the path at the time of invocation.
    timestamp:
        Unix timestamp of the activation.
    """

    record_id: int = 0
    path_id: str = ""
    caller: str = ""
    reason: str = ""
    status: DecommissionStatus = DecommissionStatus.RETIRED
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "path_id": self.path_id,
            "caller": self.caller,
            "reason": self.reason,
            "status": self.status.value,
            "timestamp": self.timestamp,
        }


@dataclass
class DecommissionSnapshot:
    """Point-in-time snapshot of the decommission runtime state.

    Attributes
    ----------
    authority:
        Module authority sentinel.
    layer_position:
        Layer position in the canonical authority stack.
    total_retired:
        Number of paths with status RETIRED.
    total_gated:
        Number of paths with status GATED.
    total_residual:
        Number of paths with status RESIDUAL.
    total_activation_records:
        Number of activation records in the ring buffer.
    recent_activations:
        Last N activation records (list of dicts).
    conflicts_closed:
        List of CONFLICT-* identifiers formally closed by this sweep.
    decommission_catalog:
        Full catalog of decommission entries (list of dicts).
    """

    authority: str = ""
    layer_position: int = 0
    total_retired: int = 0
    total_gated: int = 0
    total_residual: int = 0
    total_activation_records: int = 0
    recent_activations: List[Dict[str, Any]] = field(default_factory=list)
    conflicts_closed: List[str] = field(default_factory=list)
    decommission_catalog: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "layer_position": self.layer_position,
            "total_retired": self.total_retired,
            "total_gated": self.total_gated,
            "total_residual": self.total_residual,
            "total_activation_records": self.total_activation_records,
            "conflicts_closed": self.conflicts_closed,
        }


# ===========================================================================
# Decommission catalog — static registry of retired / gated paths
# ===========================================================================

#: The canonical decommission catalog for PR-516.
#: This list is the single source of truth for all decommissioned paths.
_DECOMMISSION_CATALOG: List[DecommissionEntry] = [
    # ------------------------------------------------------------------
    # CONFLICT-003: Executor readiness — CapabilityAssimilationLayer
    # vs legacy CapabilityRegistry.
    # Decommissioned in PR-516 by formally retiring GatewayCapabilityRegistry
    # as a parallel capability authority.
    # ------------------------------------------------------------------
    DecommissionEntry(
        path_id="galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
        kind=DecommissionedPathKind.CAPABILITY_REGISTRY,
        status=DecommissionStatus.RETIRED,
        canonical_replacement="core.capability_assimilation.CapabilityAssimilationLayer",
        reason=(
            "GatewayCapabilityRegistry was an in-gateway per-device action-schema "
            "store introduced before core.capability_bus existed.  It is a parallel "
            "capability authority that competes with CapabilityAssimilationLayer "
            "(Layer 7) for executor-readiness truth.  All capability registration "
            "and lookup must use core.capability_assimilation or "
            "core.capability_bus.CapabilityBus.  "
            "Closes CONFLICT-003."
        ),
        conflict_closed="CONFLICT-003",
        pr_origin="pre-PR-7",
        notes=(
            "DeviceRouter capability-report pathways may still call "
            "GatewayCapabilityRegistry for backward-compat.  Those call sites "
            "are gated and should be migrated to CapabilityAssimilationLayer "
            "in a future PR."
        ),
    ),
    DecommissionEntry(
        path_id="core.capability_registry.CapabilityRegistry",
        kind=DecommissionedPathKind.CAPABILITY_REGISTRY,
        status=DecommissionStatus.GATED,
        canonical_replacement="core.capability_assimilation.CapabilityAssimilationLayer",
        reason=(
            "core.capability_registry.CapabilityRegistry is a legacy device-side "
            "capability store that pre-dates CapabilityAssimilationLayer.  "
            "It is gated: existing callers may continue to use it for device-local "
            "capability bookkeeping, but it must NOT be used as the authoritative "
            "source for executor-readiness in routing decisions."
        ),
        conflict_closed="CONFLICT-003",
        pr_origin="pre-PR-7",
        notes="Gated — kept for device-local capability bookkeeping only.",
    ),
    # ------------------------------------------------------------------
    # CONFLICT-009: Task decomposition — canonical TaskGraph
    # vs legacy TaskDecomposer / IntelligentTaskPlanner.
    # ------------------------------------------------------------------
    DecommissionEntry(
        path_id="galaxy_gateway.task_decomposer.TaskDecomposer",
        kind=DecommissionedPathKind.TASK_DECOMPOSER,
        status=DecommissionStatus.RETIRED,
        canonical_replacement="core.task_graph.TaskGraph",
        reason=(
            "TaskDecomposer is a rule-based complex-task splitter that creates "
            "sub-tasks independently of the canonical TaskGraph "
            "(core.task_graph.TaskGraph).  It represents a parallel task-graph "
            "authority that can produce sub-tasks not tracked by TaskGraphRuntime.  "
            "New task decomposition must use core.task_graph.TaskGraph directly.  "
            "Closes CONFLICT-009."
        ),
        conflict_closed="CONFLICT-009",
        pr_origin="pre-PR-S6",
        notes=(
            "Retained as a compatibility shim for gateway-internal callers "
            "that have not yet been migrated.  Must not be invoked as a "
            "primary server-side task planner."
        ),
    ),
    DecommissionEntry(
        path_id="galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
        kind=DecommissionedPathKind.TASK_DECOMPOSER,
        status=DecommissionStatus.RETIRED,
        canonical_replacement="core.task_graph.TaskGraph",
        reason=(
            "IntelligentTaskPlanner is an LLM-based task planner that invokes "
            "TaskDecomposer independently of the canonical "
            "OpenClawd → CommandRouter → TaskGraph pipeline.  It is a parallel "
            "planning authority.  New planning must route through "
            "core.e2e_orchestrator.process_user_input() or the canonical "
            "OpenClawd pipeline.  Closes CONFLICT-009."
        ),
        conflict_closed="CONFLICT-009",
        pr_origin="pre-PR-S6",
        notes=(
            "Retained as a compatibility shim.  Must not be invoked as a "
            "primary server-side task planner."
        ),
    ),
    # ------------------------------------------------------------------
    # Dispatch authority: TaskRouter / TaskScheduler retired.
    # ------------------------------------------------------------------
    DecommissionEntry(
        path_id="galaxy_gateway.task_router.TaskRouter",
        kind=DecommissionedPathKind.DISPATCH_AUTHORITY,
        status=DecommissionStatus.RETIRED,
        canonical_replacement="core.command_router.CommandRouter",
        reason=(
            "TaskRouter is a standalone task-dispatch loop that routes tasks "
            "to devices via raw websocket/device calls, bypassing the canonical "
            "CommandRouter → TaskEnvelope → DeviceRouter chain.  It was formally "
            "demoted in PR-S6.  In PR-516 it is retired as a dispatch authority: "
            "all new dispatch must go through CommandRouter.route_envelope()."
        ),
        conflict_closed="",
        pr_origin="pre-PR-S6",
        pr_decommission="PR-516",
        notes="Retained for backward-compat gateway-internal callers; no new dispatch.",
    ),
    DecommissionEntry(
        path_id="galaxy_gateway.task_router.TaskScheduler",
        kind=DecommissionedPathKind.DISPATCH_AUTHORITY,
        status=DecommissionStatus.RETIRED,
        canonical_replacement="core.task_graph.TaskGraph",
        reason=(
            "TaskScheduler is a standalone topological scheduler that builds "
            "ExecutionPlan objects independently of the canonical TaskGraph.  "
            "It was formally demoted in PR-S6.  In PR-516 it is retired as a "
            "top-level scheduling authority: new scheduling must use TaskGraph."
        ),
        conflict_closed="",
        pr_origin="pre-PR-S6",
        pr_decommission="PR-516",
        notes="Retained for backward-compat gateway-internal callers; no new scheduling.",
    ),
    # ------------------------------------------------------------------
    # Agent planner: LocalAgentRuntime retired as server-side planner.
    # ------------------------------------------------------------------
    DecommissionEntry(
        path_id="core.local_agent_runtime.LocalAgentRuntime",
        kind=DecommissionedPathKind.AGENT_PLANNER,
        status=DecommissionStatus.GATED,
        canonical_replacement="core.command_router.CommandRouter",
        reason=(
            "LocalAgentRuntime is a Phase-1 Matrix OS component that ran its own "
            "Thought/Action/Observation loop.  Server-side agent execution is now "
            "brokered via the canonical OpenClawd → CommandRouter → TaskEnvelope "
            "→ DeviceRouter pipeline.  LocalAgentRuntime is retained as a "
            "device-side execution sandbox that receives already-dispatched "
            "manifests; it must NOT be invoked as a primary server-side "
            "execution planner."
        ),
        conflict_closed="",
        pr_origin="PR-S5",
        pr_decommission="PR-516",
        notes=(
            "Gated — RESIDUAL: device-side sandbox only.  "
            "Server-side planner role is retired."
        ),
    ),
    # ------------------------------------------------------------------
    # CONFLICT-010: Projection contract — canonical ProjectionSurfaceBridge
    # vs legacy dashboard-era direct payload contracts.
    # ------------------------------------------------------------------
    DecommissionEntry(
        path_id="desktop_projection.projection_engine.ProjectionEngine",
        kind=DecommissionedPathKind.PROJECTION_CONTRACT,
        status=DecommissionStatus.GATED,
        canonical_replacement="core.projection_surface_bridge.ProjectionSurfaceBridge",
        reason=(
            "ProjectionEngine was a direct payload assembler that built runtime "
            "snapshots independently of ProjectionSurfaceBridge, creating a "
            "legacy parallel projection contract.  "
            "PR-514 wired enrich_runtime_projection() into the main assembly "
            "paths.  In PR-516, ProjectionEngine's independent assembly is "
            "formally gated: it must not be used as the primary projection "
            "authority.  Closes CONFLICT-010."
        ),
        conflict_closed="CONFLICT-010",
        pr_origin="pre-PR-511",
        pr_decommission="PR-516",
        notes=(
            "Gated — still called as a thin adapter.  Must delegate to "
            "ProjectionSurfaceBridge for runtime enrichment."
        ),
    ),
    DecommissionEntry(
        path_id="dashboard.backend.legacy_projection_contract",
        kind=DecommissionedPathKind.PROJECTION_CONTRACT,
        status=DecommissionStatus.RETIRED,
        canonical_replacement="core.projection_surface_bridge.ProjectionSurfaceBridge",
        reason=(
            "Dashboard-era direct projection contracts (building runtime views "
            "by directly reading raw subsystems) are retired.  All projection "
            "assembly must use ProjectionSurfaceBridge.enrich_runtime_projection() "
            "and consume from OperatorSurface.  Closes CONFLICT-010."
        ),
        conflict_closed="CONFLICT-010",
        pr_origin="pre-PR-511",
        pr_decommission="PR-516",
        notes="Dashboard backend should consume /api/v1/operator/snapshot endpoint.",
    ),
    # ------------------------------------------------------------------
    # Envelope ingress: legacy pre-spine ingress paths.
    # ------------------------------------------------------------------
    DecommissionEntry(
        path_id="galaxy_gateway.handlers.message_handler.MessageHandler",
        kind=DecommissionedPathKind.ENVELOPE_INGRESS,
        status=DecommissionStatus.GATED,
        canonical_replacement="galaxy_gateway.websocket_handler",
        reason=(
            "MessageHandler is a legacy gateway ingress chain B "
            "(handlers/message_handler → TaskOrchestrator).  "
            "The canonical server ingress is chain A: "
            "websocket_handler → DeviceRouter.  "
            "MessageHandler was formally demoted in PR-S6.  In PR-516 it is "
            "explicitly gated: new message routing must be wired through "
            "websocket_handler (chain A) only."
        ),
        conflict_closed="",
        pr_origin="PR-S6",
        pr_decommission="PR-516",
        notes=(
            "Gated — retained so existing integrations wired to chain B do not "
            "immediately break.  Must not be used for new message routing."
        ),
    ),
]

# Lookup index for fast path_id → entry resolution
_CATALOG_INDEX: Dict[str, DecommissionEntry] = {
    e.path_id: e for e in _DECOMMISSION_CATALOG
}

# Conflicts formally closed by this PR-516 sweep
_CONFLICTS_CLOSED: List[str] = sorted(
    {e.conflict_closed for e in _DECOMMISSION_CATALOG if e.conflict_closed}
)


# ===========================================================================
# LegacySystemDecommissionRuntime
# ===========================================================================


class LegacySystemDecommissionRuntime:
    """Singleton runtime for the legacy system decommission layer.

    Maintains a ring buffer of :class:`DecommissionActivationRecord` entries
    recording any invocations of decommissioned paths that were intercepted
    during this process lifetime.

    Usage::

        runtime = get_legacy_system_decommission_runtime()
        runtime.record_activation("galaxy_gateway.task_router.TaskRouter",
                                  caller="some.module", reason="compat call")
        snap = runtime.snapshot()
        print(snap.summary())
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ring: Deque[DecommissionActivationRecord] = deque(maxlen=_RING_BUFFER_SIZE)
        self._counter: int = 0
        self._logger = logging.getLogger("Galaxy.LegacySystemDecommissionRuntime")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_activation(
        self,
        path_id: str,
        caller: str = "",
        reason: str = "",
    ) -> Optional[DecommissionActivationRecord]:
        """Record an activation attempt of a decommissioned path.

        Parameters
        ----------
        path_id:
            Dotted path identifier of the decommissioned path invoked.
        caller:
            Module/function that triggered the activation.
        reason:
            Why the activation occurred (for debugging).

        Returns
        -------
        DecommissionActivationRecord | None
            The record if ``path_id`` is in the catalog; ``None`` otherwise.
        """
        try:
            entry = _CATALOG_INDEX.get(path_id)
            if entry is None:
                self._logger.debug(
                    "record_activation: path_id=%s not in decommission catalog",
                    path_id,
                )
                return None
            with self._lock:
                self._counter += 1
                record = DecommissionActivationRecord(
                    record_id=self._counter,
                    path_id=path_id,
                    caller=caller,
                    reason=reason,
                    status=entry.status,
                )
                self._ring.append(record)
            self._logger.warning(
                "DECOMMISSION ACTIVATION | path_id=%s status=%s caller=%s",
                path_id,
                entry.status.value,
                caller,
            )
            return record
        except Exception as exc:  # pragma: no cover
            self._logger.debug("record_activation error: %s", exc)
            return None

    def assert_path_not_active(
        self,
        path_id: str,
        caller: str = "",
    ) -> None:
        """Assert that a RETIRED path is not being actively used.

        Logs a warning (non-blocking) when a RETIRED path is invoked.
        This is the primary non-regression guard.

        Parameters
        ----------
        path_id:
            Dotted path identifier.
        caller:
            Invoking module (for debugging).
        """
        try:
            entry = _CATALOG_INDEX.get(path_id)
            if entry is None:
                return
            if entry.status == DecommissionStatus.RETIRED:
                self.record_activation(
                    path_id=path_id,
                    caller=caller,
                    reason="RETIRED path activated — non-regression violation",
                )
                self._logger.error(
                    "NON-REGRESSION VIOLATION: RETIRED path activated | "
                    "path_id=%s caller=%s canonical=%s",
                    path_id,
                    caller,
                    entry.canonical_replacement,
                )
        except Exception as exc:  # pragma: no cover
            self._logger.debug("assert_path_not_active error: %s", exc)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_activation_records(self) -> List[DecommissionActivationRecord]:
        """Return all activation records from the ring buffer."""
        with self._lock:
            return list(self._ring)

    def snapshot(self) -> DecommissionSnapshot:
        """Return a point-in-time snapshot of the decommission runtime state."""
        catalog = _DECOMMISSION_CATALOG
        retired = sum(1 for e in catalog if e.status == DecommissionStatus.RETIRED)
        gated = sum(1 for e in catalog if e.status == DecommissionStatus.GATED)
        residual = sum(1 for e in catalog if e.status == DecommissionStatus.RESIDUAL)
        with self._lock:
            records = list(self._ring)
        return DecommissionSnapshot(
            authority=LEGACY_SYSTEM_DECOMMISSION_AUTHORITY,
            layer_position=LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION,
            total_retired=retired,
            total_gated=gated,
            total_residual=residual,
            total_activation_records=len(records),
            recent_activations=[r.to_dict() for r in records[-10:]],
            conflicts_closed=list(_CONFLICTS_CLOSED),
            decommission_catalog=[e.to_dict() for e in catalog],
        )


# ===========================================================================
# Singleton management
# ===========================================================================

_runtime_instance: Optional[LegacySystemDecommissionRuntime] = None
_runtime_lock = threading.Lock()


def get_legacy_system_decommission_runtime() -> LegacySystemDecommissionRuntime:
    """Return the process-global :class:`LegacySystemDecommissionRuntime` singleton."""
    global _runtime_instance
    if _runtime_instance is None:
        with _runtime_lock:
            if _runtime_instance is None:
                _runtime_instance = LegacySystemDecommissionRuntime()
    return _runtime_instance


def reset_legacy_system_decommission_runtime() -> None:
    """Reset the singleton (for testing only)."""
    global _runtime_instance
    with _runtime_lock:
        _runtime_instance = None


# ===========================================================================
# Module-level helpers
# ===========================================================================


def record_decommission_activation(
    path_id: str,
    caller: str = "",
    reason: str = "",
) -> None:
    """Record an activation of a decommissioned path (non-blocking).

    Convenience wrapper around
    :meth:`LegacySystemDecommissionRuntime.record_activation`.
    """
    try:
        get_legacy_system_decommission_runtime().record_activation(
            path_id=path_id,
            caller=caller,
            reason=reason,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("record_decommission_activation error: %s", exc)


def assert_path_not_active(
    path_id: str,
    caller: str = "",
) -> None:
    """Assert that a RETIRED path is not being activated (non-blocking guard).

    Convenience wrapper around
    :meth:`LegacySystemDecommissionRuntime.assert_path_not_active`.
    """
    try:
        get_legacy_system_decommission_runtime().assert_path_not_active(
            path_id=path_id,
            caller=caller,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("assert_path_not_active error: %s", exc)


def get_decommission_catalog() -> List[DecommissionEntry]:
    """Return the full static decommission catalog."""
    return list(_DECOMMISSION_CATALOG)


def snapshot_decommission() -> DecommissionSnapshot:
    """Return a snapshot of the decommission runtime state.

    Convenience wrapper around
    :meth:`LegacySystemDecommissionRuntime.snapshot`.
    """
    return get_legacy_system_decommission_runtime().snapshot()
