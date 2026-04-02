#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runtime_closure_audit.py
==============================
PR-512: System Closure Audit / Runtime Gap Sweep.

This module is the **closure audit layer** for the Galaxy canonical runtime
architecture.  It performs a focused system-wide gap sweep across the
production runtime stack assembled in PRs #506–#511, eliminates the
highest-value remaining disconnects, exposes parallel-truth-path detectors,
and produces a machine-readable residual gap map for follow-up PRs.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  PRODUCTION INGRESS / DISPATCH / ROUTING SURFACE                   │
    │  API ingress (routes/tasks.py)  ←  CommandRouter  ←  Scheduler    │
    │  GalaxyOrchestrator  ←  UnifiedOrchestrator  ←  AgentKernel       │
    └──────────────────────────────┬──────────────────────────────────────┘
                                   │  CLOSURE-VERIFIED BY THIS MODULE
                                   ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  CLOSURE AUDIT LAYER  (this module, Layer 12)                      │
    │                                                                     │
    │  Checks (non-blocking inspections — never writes, never routes):   │
    │    • Execution spine write closure  (PR-506)                       │
    │    • Canonical task ingress closure (PR-507)                       │
    │    • Task graph runtime realization (PR-508)                       │
    │    • Capability+network assimilation (PR-509)                      │
    │    • Operator surface API activation (PR-510)                      │
    │    • Projection surface bridge convergence (PR-511)               │
    │                                                                     │
    │  Gap detection:                                                     │
    │    • Parallel truth path detection                                  │
    │    • Authority conflict detection                                   │
    │    • Ingress / dispatch / readiness surface gaps                   │
    │                                                                     │
    │  Residual gap map:                                                  │
    │    • Machine-readable catalog of known remaining gaps              │
    │    • Each gap annotated with severity, layer, and follow-up PR     │
    └──────────────────────────────┬──────────────────────────────────────┘
                                   │  READS PROJECTIONS FROM
                                   ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  RUNTIME TRUTH LAYERS (Layers 6–11)                                │
    │  TaskGraphRuntime · CanonicalTaskRuntime · ReplayFoundation        │
    │  OperatorSurface · CapabilityAssimilation · NetworkTopologyRuntime │
    │  ProjectionSurfaceBridge                                           │
    └─────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Audit layer is read-only.**
    This module reads canonical runtime projections for inspection.  It
    MUST NOT write state, trigger dispatch, or alter execution paths.
    Governed by :data:`CLOSURE_AUDIT_READ_ONLY_POLICY`.

2.  **Closure verification is sentinel-driven.**
    Each PR-506–511 closure is verified by importing the corresponding
    integration sentinel.  If a sentinel is absent, the gap is flagged
    in the audit result rather than raising an exception.
    Governed by :data:`SENTINEL_DRIVEN_CLOSURE_POLICY`.

3.  **Parallel truth paths must be flagged, not masked.**
    When multiple layers can produce competing values for the same runtime
    fact, this module emits an explicit authority-conflict entry rather than
    silently picking one.  Governed by :data:`NO_SILENT_AUTHORITY_MASKING_POLICY`.

4.  **Residual gaps are annotated, not hidden.**
    Gaps that cannot be closed in this PR are recorded in the residual gap
    map with severity, owning layer, and suggested follow-up PR reference.
    Governed by :data:`RESIDUAL_GAP_ANNOTATION_POLICY`.

5.  **No new parallel truth source.**
    The audit snapshot is a derived view for inspection only.  It must not
    be used as a primary state source.  Governed by
    :data:`CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY`.

Public API
----------
Authority sentinels::

    RUNTIME_CLOSURE_AUDIT_AUTHORITY
    RUNTIME_CLOSURE_AUDIT_LAYER_POSITION
    CLOSURE_AUDIT_CONTRACT_VERSION

Policy sentinels::

    CLOSURE_AUDIT_READ_ONLY_POLICY
    SENTINEL_DRIVEN_CLOSURE_POLICY
    NO_SILENT_AUTHORITY_MASKING_POLICY
    RESIDUAL_GAP_ANNOTATION_POLICY
    CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY

Gap severity constants::

    GAP_SEVERITY_CRITICAL
    GAP_SEVERITY_HIGH
    GAP_SEVERITY_MEDIUM
    GAP_SEVERITY_LOW
    GAP_SEVERITY_RESIDUAL

Layer closure status constants::

    CLOSURE_STATUS_VERIFIED
    CLOSURE_STATUS_PARTIAL
    CLOSURE_STATUS_MISSING
    CLOSURE_STATUS_DEGRADED

Dataclasses::

    ClosureGapEntry
    AuthorityConflictEntry
    LayerClosureStatus
    ClosureAuditSnapshot

Class::

    RuntimeClosureAudit

Module-level helpers::

    run_closure_audit() -> ClosureAuditSnapshot
    detect_parallel_truth_paths() -> List[AuthorityConflictEntry]
    get_residual_gap_map() -> List[ClosureGapEntry]
    get_runtime_closure_audit() -> RuntimeClosureAudit
    reset_runtime_closure_audit() -> None
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RuntimeClosureAudit")

# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority sentinels
    "RUNTIME_CLOSURE_AUDIT_AUTHORITY",
    "RUNTIME_CLOSURE_AUDIT_LAYER_POSITION",
    "CLOSURE_AUDIT_CONTRACT_VERSION",
    # Policy sentinels
    "CLOSURE_AUDIT_READ_ONLY_POLICY",
    "SENTINEL_DRIVEN_CLOSURE_POLICY",
    "NO_SILENT_AUTHORITY_MASKING_POLICY",
    "RESIDUAL_GAP_ANNOTATION_POLICY",
    "CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY",
    # Gap severity constants
    "GAP_SEVERITY_CRITICAL",
    "GAP_SEVERITY_HIGH",
    "GAP_SEVERITY_MEDIUM",
    "GAP_SEVERITY_LOW",
    "GAP_SEVERITY_RESIDUAL",
    # Layer closure status constants
    "CLOSURE_STATUS_VERIFIED",
    "CLOSURE_STATUS_PARTIAL",
    "CLOSURE_STATUS_MISSING",
    "CLOSURE_STATUS_DEGRADED",
    # Dataclasses
    "ClosureGapEntry",
    "AuthorityConflictEntry",
    "LayerClosureStatus",
    "ClosureAuditSnapshot",
    # Class
    "RuntimeClosureAudit",
    # Helpers
    "run_closure_audit",
    "detect_parallel_truth_paths",
    "get_residual_gap_map",
    "get_runtime_closure_audit",
    "reset_runtime_closure_audit",
]

# ===========================================================================
# Authority sentinels
# ===========================================================================

RUNTIME_CLOSURE_AUDIT_AUTHORITY: str = (
    "core.runtime_closure_audit.RuntimeClosureAudit"
)

RUNTIME_CLOSURE_AUDIT_LAYER_POSITION: int = 12

CLOSURE_AUDIT_CONTRACT_VERSION: str = "CLOSURE_AUDIT_CONTRACT_V1"

# ===========================================================================
# Policy sentinels
# ===========================================================================

CLOSURE_AUDIT_READ_ONLY_POLICY: str = (
    "CLOSURE_AUDIT_READ_ONLY_POLICY_V1: "
    "The closure audit layer MUST NOT write state, trigger dispatch, or alter "
    "execution paths.  It is a read-only inspection layer that reads canonical "
    "runtime projections and emits structured gap/conflict reports."
)

SENTINEL_DRIVEN_CLOSURE_POLICY: str = (
    "SENTINEL_DRIVEN_CLOSURE_POLICY_V1: "
    "Each PR-506–511 closure is verified by importing the corresponding "
    "integration sentinel.  Missing sentinels produce CLOSURE_STATUS_MISSING "
    "entries rather than raised exceptions, preserving graceful degradation."
)

NO_SILENT_AUTHORITY_MASKING_POLICY: str = (
    "NO_SILENT_AUTHORITY_MASKING_POLICY_V1: "
    "When multiple layers can produce competing values for the same runtime "
    "fact, the audit layer emits an explicit AuthorityConflictEntry instead "
    "of silently picking one.  Masking parallel truth paths is prohibited."
)

RESIDUAL_GAP_ANNOTATION_POLICY: str = (
    "RESIDUAL_GAP_ANNOTATION_POLICY_V1: "
    "Gaps that cannot be closed in PR-512 are recorded in the residual gap map "
    "with severity, owning layer, and suggested follow-up PR reference. "
    "Gaps must not be hidden by shallow projection or silent fallback."
)

CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY: str = (
    "CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY_V1: "
    "ClosureAuditSnapshot is a derived view for inspection only.  It must not "
    "be used as a primary state source for routing, dispatch, or projection."
)

# ===========================================================================
# Gap severity constants
# ===========================================================================

GAP_SEVERITY_CRITICAL: str = "CRITICAL"
GAP_SEVERITY_HIGH: str = "HIGH"
GAP_SEVERITY_MEDIUM: str = "MEDIUM"
GAP_SEVERITY_LOW: str = "LOW"
GAP_SEVERITY_RESIDUAL: str = "RESIDUAL"

# ===========================================================================
# Layer closure status constants
# ===========================================================================

CLOSURE_STATUS_VERIFIED: str = "VERIFIED"
CLOSURE_STATUS_PARTIAL: str = "PARTIAL"
CLOSURE_STATUS_MISSING: str = "MISSING"
CLOSURE_STATUS_DEGRADED: str = "DEGRADED"

# ===========================================================================
# Known gap catalog — static residual gaps left for follow-up PRs
# ===========================================================================
#
# Each entry documents:
#   gap_id      — stable identifier (never reused)
#   severity    — one of GAP_SEVERITY_* constants
#   layer       — owning layer or module
#   description — concise description of what is not yet closed
#   follow_up   — suggested PR reference for resolution
#   is_residual — True when closure is deferred beyond PR-512

_KNOWN_RESIDUAL_GAPS: List[Dict[str, Any]] = [
    {
        "gap_id": "GAP-512-001",
        "severity": GAP_SEVERITY_HIGH,
        "layer": "core/routes/tasks.py",
        "description": (
            "API task ingress (POST /api/v1/tasks) front-loads CanonicalTask "
            "but does not write a TaskExecutionRecord to ReplayFoundation. "
            "The task_id flows into the canonical runtime but audit lineage "
            "is not recorded for API-ingressed tasks."
        ),
        "follow_up": "PR-513",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-002",
        "severity": GAP_SEVERITY_HIGH,
        "layer": "core/scheduler.py",
        "description": (
            "Scheduler's relay and mesh paths stamp CANONICAL_TASK_FRONT_LOADED "
            "sentinel but the resulting CanonicalTask is not registered in "
            "TaskGraphRuntime before dispatch, creating a gap between task-graph "
            "realization (PR-508) and the scheduler's mesh/relay codepaths."
        ),
        "follow_up": "PR-513",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-003",
        "severity": GAP_SEVERITY_MEDIUM,
        "layer": "core/projection_surface_bridge.py",
        "description": (
            "ProjectionSurfaceBridge.enrich_runtime_projection() enriches "
            "projection dicts from OperatorSurface, but the status board "
            "surfaces (desktop_projection, status_board_v2) do not yet call "
            "enrich_runtime_projection() in their assembly paths. "
            "Bridge is wired but not yet consumed by all projection endpoints."
        ),
        "follow_up": "PR-514",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-004",
        "severity": GAP_SEVERITY_MEDIUM,
        "layer": "core/capability_network_runtime_policy.py",
        "description": (
            "query_routable_executors() and query_network_path() are available "
            "for router/policy consumption, but the CommandRouter does not yet "
            "call these helpers before selecting dispatch targets. "
            "Routing decisions may bypass canonical capability/network truth."
        ),
        "follow_up": "PR-513",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-005",
        "severity": GAP_SEVERITY_MEDIUM,
        "layer": "core/operator_surface.py / core/routes/operator.py",
        "description": (
            "OperatorSurface.operator_snapshot() is exposed via the REST API "
            "(GET /api/v1/operator/snapshot) but the status board / desktop "
            "projection surface does not consume the operator snapshot. "
            "The status board still assembles its own runtime view without "
            "reading from the canonical operator surface."
        ),
        "follow_up": "PR-514",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-006",
        "severity": GAP_SEVERITY_LOW,
        "layer": "galaxy_gateway/orchestrator/task_orchestrator.py",
        "description": (
            "TaskOrchestrator front-loads CanonicalTask (PR-507) but does not "
            "register an audit event via AuditEventSemantics after successful "
            "orchestration handoff, leaving the audit trail incomplete for "
            "gateway-orchestrated tasks."
        ),
        "follow_up": "PR-513",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-007",
        "severity": GAP_SEVERITY_LOW,
        "layer": "core/agent/kernel.py",
        "description": (
            "AgentKernel front-loads CanonicalTask (PR-507) but does not emit "
            "a TASK_ADMITTED audit event, creating a gap between task admission "
            "and the canonical audit vocabulary defined in PR-506."
        ),
        "follow_up": "PR-513",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-008",
        "severity": GAP_SEVERITY_RESIDUAL,
        "layer": "desktop_projection / status_board_v2",
        "description": (
            "Desktop projection surfaces (ContinuumState, DesktopStatusProjection) "
            "still maintain their own topology/route representations independently "
            "of NetworkTopologyRuntime. Final presentation authority clarification "
            "is out of scope for PR-512 and PR-513."
        ),
        "follow_up": "PR-514",
        "is_residual": True,
    },
    {
        "gap_id": "GAP-512-009",
        "severity": GAP_SEVERITY_RESIDUAL,
        "layer": "core/continuum / desktop_projection",
        "description": (
            "Multi-model intelligent routing supply (model topology / provider "
            "routing) remains expressed through the ContinuumState/TopologyRoutePlan "
            "projection path only, without a canonical runtime authority equivalent "
            "to NetworkTopologyRuntime for the device/network domain. "
            "This is a known accepted gap deferred to a dedicated model-topology PR."
        ),
        "follow_up": "PR-515",
        "is_residual": True,
    },
]

# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class ClosureGapEntry:
    """A single documented closure gap.

    Attributes
    ----------
    gap_id:
        Stable identifier for this gap (never reused across PRs).
    severity:
        One of :data:`GAP_SEVERITY_CRITICAL` / ``HIGH`` / ``MEDIUM`` /
        ``LOW`` / ``RESIDUAL``.
    layer:
        The module or subsystem layer that owns the gap.
    description:
        Concise description of the runtime disconnect.
    follow_up:
        Suggested PR reference where this gap should be closed.
    is_residual:
        ``True`` when closure is deferred beyond the current PR.
    detected_at:
        UNIX timestamp when this entry was produced.
    """

    gap_id: str
    severity: str
    layer: str
    description: str
    follow_up: str
    is_residual: bool
    detected_at: float = field(default_factory=time.time)

    def is_critical_or_high(self) -> bool:
        """Return ``True`` if severity is CRITICAL or HIGH."""
        return self.severity in (GAP_SEVERITY_CRITICAL, GAP_SEVERITY_HIGH)


@dataclass
class AuthorityConflictEntry:
    """A detected parallel-truth-path / authority conflict.

    Attributes
    ----------
    conflict_id:
        Stable identifier for this conflict.
    runtime_fact:
        The runtime fact that has competing sources of truth (e.g.,
        ``"task_status"``, ``"executor_readiness"``).
    layer_a:
        First competing authority.
    layer_b:
        Second competing authority.
    description:
        Description of the conflict and why it exists.
    is_resolved:
        ``True`` when this conflict was resolved in PR-512 or an earlier PR.
    resolution_note:
        Description of how the conflict was resolved (if ``is_resolved``).
    detected_at:
        UNIX timestamp when this entry was produced.
    """

    conflict_id: str
    runtime_fact: str
    layer_a: str
    layer_b: str
    description: str
    is_resolved: bool = False
    resolution_note: str = ""
    detected_at: float = field(default_factory=time.time)


@dataclass
class LayerClosureStatus:
    """Closure status for a single PR-506–511 layer.

    Attributes
    ----------
    pr_ref:
        The PR that introduced this layer (e.g., ``"PR-506"``).
    layer_name:
        Human-readable name for the layer.
    sentinel_name:
        The integration sentinel expected to be present.
    sentinel_module:
        The module that should export the sentinel.
    status:
        One of :data:`CLOSURE_STATUS_VERIFIED` / ``PARTIAL`` /
        ``MISSING`` / ``DEGRADED``.
    sentinel_value:
        The resolved sentinel value (empty string if absent).
    notes:
        Additional notes about the closure status.
    """

    pr_ref: str
    layer_name: str
    sentinel_name: str
    sentinel_module: str
    status: str
    sentinel_value: str = ""
    notes: str = ""

    def is_verified(self) -> bool:
        """Return ``True`` if this layer's closure is fully verified."""
        return self.status == CLOSURE_STATUS_VERIFIED


@dataclass
class ClosureAuditSnapshot:
    """Complete closure audit snapshot.

    This snapshot is **informational only** — see
    :data:`CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY`.

    Attributes
    ----------
    audit_authority:
        Always :data:`RUNTIME_CLOSURE_AUDIT_AUTHORITY`.
    contract_version:
        Always :data:`CLOSURE_AUDIT_CONTRACT_VERSION`.
    layer_statuses:
        Closure status for each PR-506–511 layer.
    gaps:
        All closure gaps detected (both active and residual).
    conflicts:
        All authority conflicts detected.
    verified_count:
        Number of layers with CLOSURE_STATUS_VERIFIED.
    missing_count:
        Number of layers with CLOSURE_STATUS_MISSING.
    critical_high_gap_count:
        Number of gaps with CRITICAL or HIGH severity.
    all_layers_closed:
        ``True`` when every layer is CLOSURE_STATUS_VERIFIED.
    snapshot_ts:
        UNIX timestamp of snapshot.
    """

    audit_authority: str = field(default=RUNTIME_CLOSURE_AUDIT_AUTHORITY)
    contract_version: str = field(default=CLOSURE_AUDIT_CONTRACT_VERSION)
    layer_statuses: List[LayerClosureStatus] = field(default_factory=list)
    gaps: List[ClosureGapEntry] = field(default_factory=list)
    conflicts: List[AuthorityConflictEntry] = field(default_factory=list)
    verified_count: int = 0
    missing_count: int = 0
    critical_high_gap_count: int = 0
    all_layers_closed: bool = False
    snapshot_ts: float = field(default_factory=time.time)

    def summary(self) -> Dict[str, Any]:
        """Return a compact summary dict suitable for JSON serialisation."""
        return {
            "audit_authority": self.audit_authority,
            "contract_version": self.contract_version,
            "all_layers_closed": self.all_layers_closed,
            "verified_count": self.verified_count,
            "missing_count": self.missing_count,
            "total_layers": len(self.layer_statuses),
            "total_gaps": len(self.gaps),
            "critical_high_gap_count": self.critical_high_gap_count,
            "total_conflicts": len(self.conflicts),
            "unresolved_conflicts": sum(
                1 for c in self.conflicts if not c.is_resolved
            ),
            "residual_gaps": sum(1 for g in self.gaps if g.is_residual),
            "snapshot_ts": self.snapshot_ts,
        }


# ===========================================================================
# RuntimeClosureAudit class
# ===========================================================================

class RuntimeClosureAudit:
    """
    Closure audit engine for the Galaxy canonical runtime architecture.

    This class performs non-blocking, read-only inspection of each runtime
    layer established in PRs #506–#511, detects parallel truth paths and
    authority conflicts, and emits a structured :class:`ClosureAuditSnapshot`.

    It is a singleton accessed via :func:`get_runtime_closure_audit`.

    Invariants
    ----------
    * Read-only — this class MUST NOT write state, trigger dispatch, or
      alter execution paths.  See :data:`CLOSURE_AUDIT_READ_ONLY_POLICY`.
    * Sentinel-driven — each layer closure is verified by importing the
      corresponding integration sentinel.  Missing sentinels produce
      CLOSURE_STATUS_MISSING entries.  See
      :data:`SENTINEL_DRIVEN_CLOSURE_POLICY`.
    * Non-blocking — all import attempts are wrapped in try/except so that
      absent optional dependencies never abort the audit.
    """

    # -----------------------------------------------------------------------
    # Layer closure sentinel specs
    # Each tuple: (pr_ref, layer_name, sentinel_name, sentinel_module)
    # -----------------------------------------------------------------------
    _LAYER_SPECS: List[tuple] = [
        (
            "PR-506",
            "Execution Spine Write Integration",
            "EXECUTION_SPINE_WRITE_INTEGRATED",
            "core.command_router",
        ),
        (
            "PR-507",
            "Canonical Task Front-Loading (API ingress)",
            "CANONICAL_TASK_API_INGRESS_FRONT_LOADED",
            "core.routes.tasks",
        ),
        (
            "PR-507",
            "Canonical Task Front-Loading (TaskOrchestrator)",
            "CANONICAL_TASK_TASK_ORCHESTRATOR_FRONT_LOADED",
            "galaxy_gateway.orchestrator.task_orchestrator",
        ),
        (
            "PR-507",
            "Canonical Task Front-Loading (Scheduler)",
            "CANONICAL_TASK_SCHEDULER_FRONT_LOADED",
            "core.scheduler",
        ),
        (
            "PR-507",
            "Canonical Task Front-Loading (AgentKernel)",
            "CANONICAL_TASK_AGENT_KERNEL_FRONT_LOADED",
            "core.agent.kernel",
        ),
        (
            "PR-508",
            "Task Graph Runtime Realization (GalaxyOrchestrator)",
            "GALAXY_ORCHESTRATOR_GRAPH_CONTRIBUTOR",
            "galaxy_gateway.orchestrator.galaxy_orchestrator",
        ),
        (
            "PR-508",
            "Task Graph Runtime Realization (UnifiedOrchestrator)",
            "UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR",
            "fusion.unified_orchestrator",
        ),
        (
            "PR-509",
            "Capability+Network Assimilation (NatsBus)",
            "CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED",
            "core.nats_bus",
        ),
        (
            "PR-509",
            "Capability+Network Assimilation (CapabilityAssimilation)",
            "CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED",
            "core.capability_assimilation",
        ),
        (
            "PR-510",
            "Operator API Activation (routes/operator)",
            "OPERATOR_ROUTES_V1",
            "core.routes.operator",
        ),
        (
            "PR-511",
            "Projection Surface Bridge Convergence (routes/projection)",
            "PROJECTION_SURFACE_BRIDGE_INTEGRATED",
            "core.routes.projection",
        ),
        (
            "PR-513",
            "Failure/Degraded/Recovery Policy Layer",
            "FAILURE_DEGRADED_RECOVERY_AUTHORITY",
            "core.failure_degraded_recovery_policy",
        ),
        (
            "PR-513",
            "API Task Ingress ReplayFoundation Write (GAP-512-001)",
            "TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED",
            "core.routes.tasks",
        ),
        (
            "PR-513",
            "Scheduler Relay/Mesh TaskGraphRuntime Integration (GAP-512-002)",
            "SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED",
            "core.scheduler",
        ),
        (
            "PR-513",
            "CommandRouter Capability/Network Canonical Query (GAP-512-004)",
            "CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED",
            "core.command_router",
        ),
        (
            "PR-513",
            "TaskOrchestrator Audit Dispatch Integration (GAP-512-006)",
            "TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED",
            "galaxy_gateway.orchestrator.task_orchestrator",
        ),
        (
            "PR-513",
            "AgentKernel Audit Admitted Integration (GAP-512-007)",
            "AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED",
            "core.agent.kernel",
        ),
    ]

    def __init__(self) -> None:
        self._logger = logging.getLogger("Galaxy.RuntimeClosureAudit")

    # -----------------------------------------------------------------------
    # Layer closure verification
    # -----------------------------------------------------------------------

    def _verify_layer(
        self,
        pr_ref: str,
        layer_name: str,
        sentinel_name: str,
        sentinel_module: str,
    ) -> LayerClosureStatus:
        """Attempt to import a layer sentinel and return a :class:`LayerClosureStatus`."""
        try:
            import importlib
            mod = importlib.import_module(sentinel_module)
            value = getattr(mod, sentinel_name, None)
            if value is None:
                return LayerClosureStatus(
                    pr_ref=pr_ref,
                    layer_name=layer_name,
                    sentinel_name=sentinel_name,
                    sentinel_module=sentinel_module,
                    status=CLOSURE_STATUS_MISSING,
                    sentinel_value="",
                    notes=f"Sentinel '{sentinel_name}' not found on module '{sentinel_module}'.",
                )
            if not isinstance(value, str) or not value:
                return LayerClosureStatus(
                    pr_ref=pr_ref,
                    layer_name=layer_name,
                    sentinel_name=sentinel_name,
                    sentinel_module=sentinel_module,
                    status=CLOSURE_STATUS_DEGRADED,
                    sentinel_value=str(value),
                    notes=f"Sentinel '{sentinel_name}' has unexpected type/value: {value!r}.",
                )
            return LayerClosureStatus(
                pr_ref=pr_ref,
                layer_name=layer_name,
                sentinel_name=sentinel_name,
                sentinel_module=sentinel_module,
                status=CLOSURE_STATUS_VERIFIED,
                sentinel_value=value,
            )
        except ImportError as exc:
            return LayerClosureStatus(
                pr_ref=pr_ref,
                layer_name=layer_name,
                sentinel_name=sentinel_name,
                sentinel_module=sentinel_module,
                status=CLOSURE_STATUS_MISSING,
                sentinel_value="",
                notes=f"ImportError importing '{sentinel_module}': {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return LayerClosureStatus(
                pr_ref=pr_ref,
                layer_name=layer_name,
                sentinel_name=sentinel_name,
                sentinel_module=sentinel_module,
                status=CLOSURE_STATUS_DEGRADED,
                sentinel_value="",
                notes=f"Unexpected error: {exc}",
            )

    def verify_all_layers(self) -> List[LayerClosureStatus]:
        """Verify closure for all PR-506–511 layers.

        Returns
        -------
        List[LayerClosureStatus]
            One entry per layer spec.  Import errors produce
            CLOSURE_STATUS_MISSING; unexpected errors produce
            CLOSURE_STATUS_DEGRADED.
        """
        return [
            self._verify_layer(pr_ref, layer_name, sentinel_name, sentinel_module)
            for pr_ref, layer_name, sentinel_name, sentinel_module in self._LAYER_SPECS
        ]

    # -----------------------------------------------------------------------
    # Parallel truth path / authority conflict detection
    # -----------------------------------------------------------------------

    def detect_parallel_truth_paths(self) -> List[AuthorityConflictEntry]:
        """Detect known parallel-truth-path and authority conflict patterns.

        Returns
        -------
        List[AuthorityConflictEntry]
            All detected conflicts.  Each entry includes ``is_resolved``
            and ``resolution_note`` so consumers can distinguish resolved
            vs. still-open conflicts.
        """
        conflicts: List[AuthorityConflictEntry] = []

        # CONFLICT-001: Task status truth — CanonicalTaskRuntime vs legacy task queue
        # RESOLVED in PR-507: adapt_to_canonical_task() front-loads every ingress point.
        conflicts.append(AuthorityConflictEntry(
            conflict_id="CONFLICT-001",
            runtime_fact="task_status / task_identity",
            layer_a="core.canonical_task.CanonicalTaskRuntime",
            layer_b="core.routes._shared.task_queue (legacy dict store)",
            description=(
                "Two parallel stores exist for task identity: CanonicalTaskRuntime "
                "(ring buffer of CanonicalTask) and the legacy task_queue dict in "
                "core/routes/_shared.py.  Both are written at API ingress."
            ),
            is_resolved=True,
            resolution_note=(
                "PR-507 front-loads adapt_to_canonical_task() at API ingress so "
                "CanonicalTask is always the primary object.  The legacy task_queue "
                "is kept for compat routing only and MUST NOT be used as a truth "
                "source for task status.  Authority is narrowed to CanonicalTaskRuntime."
            ),
        ))

        # CONFLICT-002: Network topology truth — NetworkTopologyRuntime vs projection TopologyRoutePlan
        # PARTIALLY RESOLVED in PR-511: bridge enriches projection from runtime.
        conflicts.append(AuthorityConflictEntry(
            conflict_id="CONFLICT-002",
            runtime_fact="network topology / device reachability",
            layer_a="core.network_topology_runtime.NetworkTopologyRuntime",
            layer_b="ContinuumState / TopologyRoutePlan (projection stack)",
            description=(
                "NetworkTopologyRuntime (Layer 8) holds canonical device/network "
                "reachability truth, but ContinuumState and TopologyRoutePlan in "
                "the projection stack maintain their own topology representations "
                "without reading from NetworkTopologyRuntime.  Status board surfaces "
                "may display stale or projection-only topology."
            ),
            is_resolved=False,
            resolution_note=(
                "PR-511 ProjectionSurfaceBridge enriches projection dicts from "
                "OperatorSurface (which reads NetworkTopologyRuntime), but the "
                "status board assembly paths do not yet call enrich_runtime_projection(). "
                "Full resolution deferred to PR-514 (GAP-512-003)."
            ),
        ))

        # CONFLICT-003: Executor readiness — CapabilityAssimilationLayer vs legacy registry
        # PARTIALLY RESOLVED in PR-509.
        conflicts.append(AuthorityConflictEntry(
            conflict_id="CONFLICT-003",
            runtime_fact="executor readiness / capability set",
            layer_a="core.capability_assimilation.CapabilityAssimilationLayer",
            layer_b="galaxy_gateway.capability_registry.CapabilityRegistry (legacy)",
            description=(
                "CapabilityAssimilationLayer (PR-507/509) is the canonical authority "
                "for executor presence and capability sets.  The legacy gateway "
                "CapabilityRegistry may still be used by some routing paths, "
                "creating a competing truth source for executor readiness."
            ),
            is_resolved=False,
            resolution_note=(
                "PR-509 adds query_routable_executors() and query_network_path() "
                "helpers that read from canonical layers.  PR-513 wires "
                "CommandRouter.route_envelope() to call these helpers before "
                "dispatch selection (GAP-512-004) via the "
                "CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED sentinel.  "
                "Legacy CapabilityRegistry may still be used by some paths; "
                "full decommission deferred to a future PR."
            ),
        ))

        # CONFLICT-004: Operator inspection truth — OperatorSurface vs raw runtime reads
        # RESOLVED in PR-510: routes/operator.py reads only OperatorSurface.
        conflicts.append(AuthorityConflictEntry(
            conflict_id="CONFLICT-004",
            runtime_fact="operator inspection / runtime snapshot",
            layer_a="core.operator_surface.OperatorSurface",
            layer_b="direct reads of CanonicalTaskRuntime / ReplayFoundation / etc.",
            description=(
                "Operator console and status board surfaces might read raw runtime "
                "subsystems directly instead of routing through OperatorSurface.  "
                "This creates competing inspection paths."
            ),
            is_resolved=True,
            resolution_note=(
                "PR-510 core/routes/operator.py enforces that all operator "
                "inspection endpoints read exclusively from OperatorSurface. "
                "Direct raw subsystem reads in operator routes are prohibited "
                "by the TestI_ProjectionOnlyDiscipline test group."
            ),
        ))

        # CONFLICT-005: Replay/audit truth — ReplayFoundation vs AuditEventSemantics
        # RESOLVED in PR-506: both layers are written by command_router.route_envelope().
        conflicts.append(AuthorityConflictEntry(
            conflict_id="CONFLICT-005",
            runtime_fact="task execution record / audit event",
            layer_a="core.replay_foundation.ReplayFoundation",
            layer_b="core.audit_event_semantics.AuditEventSemantics",
            description=(
                "ReplayFoundation records immutable execution records while "
                "AuditEventSemantics records semantic audit events.  If they "
                "are written by different code paths, their records may diverge "
                "for the same task execution."
            ),
            is_resolved=True,
            resolution_note=(
                "PR-506 routes both writes through CommandRouter.route_envelope() "
                "as the single production write path, ensuring ReplayFoundation "
                "and AuditEventSemantics are always written together for the same "
                "task execution event."
            ),
        ))

        return conflicts

    # -----------------------------------------------------------------------
    # Residual gap map
    # -----------------------------------------------------------------------

    def get_residual_gap_map(self) -> List[ClosureGapEntry]:
        """Return the complete residual gap map.

        Returns
        -------
        List[ClosureGapEntry]
            All documented closure gaps from the static catalog.
            Gaps with ``is_residual=True`` are deferred to follow-up PRs.
        """
        return [
            ClosureGapEntry(
                gap_id=entry["gap_id"],
                severity=entry["severity"],
                layer=entry["layer"],
                description=entry["description"],
                follow_up=entry["follow_up"],
                is_residual=entry["is_residual"],
            )
            for entry in _KNOWN_RESIDUAL_GAPS
        ]

    # -----------------------------------------------------------------------
    # Full audit snapshot
    # -----------------------------------------------------------------------

    def run_audit(self) -> ClosureAuditSnapshot:
        """Run the full closure audit and return a snapshot.

        This method:
        1. Verifies layer closure for each PR-506–511 sentinel.
        2. Detects parallel truth paths and authority conflicts.
        3. Collects the residual gap map.
        4. Aggregates counts and the ``all_layers_closed`` flag.

        Returns
        -------
        ClosureAuditSnapshot
            Complete audit snapshot.  See
            :data:`CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY` — this snapshot
            is for inspection only.
        """
        self._logger.debug("RuntimeClosureAudit: running closure audit")

        layer_statuses = self.verify_all_layers()
        conflicts = self.detect_parallel_truth_paths()
        gaps = self.get_residual_gap_map()

        verified_count = sum(
            1 for s in layer_statuses if s.status == CLOSURE_STATUS_VERIFIED
        )
        missing_count = sum(
            1 for s in layer_statuses if s.status == CLOSURE_STATUS_MISSING
        )
        critical_high_gap_count = sum(
            1 for g in gaps if g.is_critical_or_high()
        )
        all_layers_closed = (
            len(layer_statuses) > 0
            and missing_count == 0
            and all(s.status == CLOSURE_STATUS_VERIFIED for s in layer_statuses)
        )

        snapshot = ClosureAuditSnapshot(
            layer_statuses=layer_statuses,
            gaps=gaps,
            conflicts=conflicts,
            verified_count=verified_count,
            missing_count=missing_count,
            critical_high_gap_count=critical_high_gap_count,
            all_layers_closed=all_layers_closed,
        )

        self._logger.debug(
            "RuntimeClosureAudit: audit complete — verified=%d missing=%d "
            "gaps=%d conflicts=%d all_closed=%s",
            verified_count,
            missing_count,
            len(gaps),
            len(conflicts),
            all_layers_closed,
        )

        return snapshot


# ===========================================================================
# Singleton management
# ===========================================================================

_SINGLETON: Optional[RuntimeClosureAudit] = None


def get_runtime_closure_audit() -> RuntimeClosureAudit:
    """Return the global :class:`RuntimeClosureAudit` singleton."""
    global _SINGLETON  # noqa: PLW0603
    if _SINGLETON is None:
        _SINGLETON = RuntimeClosureAudit()
    return _SINGLETON


def reset_runtime_closure_audit() -> None:
    """Reset the singleton (for testing only)."""
    global _SINGLETON  # noqa: PLW0603
    _SINGLETON = None


# ===========================================================================
# Module-level convenience helpers
# ===========================================================================

def run_closure_audit() -> ClosureAuditSnapshot:
    """Run the full closure audit and return a snapshot.

    Convenience wrapper around
    :meth:`RuntimeClosureAudit.run_audit`.
    """
    return get_runtime_closure_audit().run_audit()


def detect_parallel_truth_paths() -> List[AuthorityConflictEntry]:
    """Detect parallel truth paths and authority conflicts.

    Convenience wrapper around
    :meth:`RuntimeClosureAudit.detect_parallel_truth_paths`.
    """
    return get_runtime_closure_audit().detect_parallel_truth_paths()


def get_residual_gap_map() -> List[ClosureGapEntry]:
    """Return the residual gap map.

    Convenience wrapper around
    :meth:`RuntimeClosureAudit.get_residual_gap_map`.
    """
    return get_runtime_closure_audit().get_residual_gap_map()
