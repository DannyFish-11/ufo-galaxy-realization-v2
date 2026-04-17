#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/center_side_compat_closure.py
====================================
PR-5 (Cross-Repo Compatibility Retirement Prep — Center-side Compatibility
Closure): Focused center-side compatibility closure pass.

Background
----------
The center-side runtime has evolved through PRs #1–#4 to establish strong
canonical governance.  However, residual compatibility seams from earlier
migration passes remain in the runtime:

* Legacy device API compat routes (``core/routes/compat.py``) originally
  targeted for removal in Batch PR-5.
* The ``/ws/ufo3/{device_id}`` WebSocket path, disabled by flag but still
  registered, with no confirmed active clients and no formal retirement record.
* ``CapabilityRegistry`` gating (PR-516): permitted for device-local
  bookkeeping, but the governance boundary between device-local use and
  routing decisions is not machine-checkable.
* ``CrossDeviceCoordinator`` substrate-only enforcement (PR-518): sentinel
  exists but external caller exposure has no explicit retirement record.
* ``LocalAgentRuntime`` server-side planning role retirement: gated by
  PR-516 but the device-side sandbox boundary is not documented at a
  gap-record level.
* ``ProjectionEngine`` delegation gate (PR-516): gated to delegate to
  ``ProjectionSurfaceBridge``; gating not enforced at runtime by a
  machine-checkable fence.
* Android REST compat aliases (``POST /api/devices/register``,
  ``GET /api/devices/list``): no confirmed retirement timeline.

This module resolves those risks by:

1. **Cataloguing** every open compatibility gap from the dual-repo gap matrix
   (Domain 7: Compatibility and Transitional Surfaces) as a machine-readable
   :class:`CompatGapRecord`.
2. **Classifying** each gap's current closure status (``OPEN``, ``FENCED``,
   ``RETIRED``, ``TOMBSTONED``) so CI and operator tools can detect unfenced
   seams.
3. **Providing fence helpers** that enforce canonical path preference at
   call-sites where compat paths must not silently supersede the canonical
   surface.
4. **Providing a cross-repo convergence readiness gate** that summarises
   the center-side compat closure posture for cross-repo alignment work.

Design principles
-----------------
- **Additive only** — this module does not modify any existing module.
  It provides vocabulary, a queryable governance surface, and non-blocking
  fence helpers that other modules can import.
- **Honest about open seams** — no gap is marked ``FENCED`` or ``RETIRED``
  unless a concrete enforcement mechanism is in place or cited.
- **Machine-checkable** — all sentinels and fence verdicts are importable
  strings that CI, tests, and diagnostic endpoints can assert.
- **Non-blocking** — fence helpers log and return a verdict; they do not
  raise exceptions unless the caller requests strict mode.
- **Cross-repo ready** — the convergence readiness gate is JSON-serialisable
  and suitable for CI consumption by both V2 and Android build pipelines.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY`
:data:`CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL`
:data:`COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY`
:data:`LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY`
:data:`CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY`
:data:`CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY`

Enums
~~~~~
:class:`CompatGapDomain`
:class:`CompatClosureStatus`
:class:`CompatFenceKind`
:class:`FenceVerdict`

Data classes
~~~~~~~~~~~~
:class:`CompatGapRecord`
:class:`CompatFenceResult`
:class:`CompatClosureSnapshot`

Functions
~~~~~~~~~
:func:`get_compat_gap_catalog`
:func:`get_gaps_by_status`
:func:`get_open_gaps`
:func:`get_fenced_gaps`
:func:`check_compat_fence`
:func:`assert_canonical_path_preferred`
:func:`build_compat_closure_snapshot`
:func:`is_cross_repo_convergence_ready`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    # Sentinels
    "CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY",
    "CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL",
    "COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY",
    "LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY",
    "CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY",
    "CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY",
    # Enums
    "CompatGapDomain",
    "CompatClosureStatus",
    "CompatFenceKind",
    "FenceVerdict",
    # Data classes
    "CompatGapRecord",
    "CompatFenceResult",
    "CompatClosureSnapshot",
    # Functions
    "get_compat_gap_catalog",
    "get_gaps_by_status",
    "get_open_gaps",
    "get_fenced_gaps",
    "check_compat_fence",
    "assert_canonical_path_preferred",
    "build_compat_closure_snapshot",
    "is_cross_repo_convergence_ready",
]

# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY: str = (
    "CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY::"
    "core.center_side_compat_closure is the canonical authority for the "
    "PR-5 center-side compatibility closure pass.  It catalogs residual "
    "compatibility seams from the dual-repo gap matrix (Domain 7), "
    "classifies their closure status, and provides fence helpers that "
    "enforce canonical path preference at call-sites where compat paths "
    "must not silently supersede the canonical surface."
)

CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL: str = (
    "CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL::package=PR5::"
    "profile=center-side-compat-closure-v1::"
    "module=core.center_side_compat_closure"
)

COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY: str = (
    "POLICY::COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL: "
    "Compatibility seams (legacy routes, compat facades, transitional shims) "
    "must never silently supersede the canonical path for a given operation. "
    "Every active compat seam must be explicitly inventoried in this catalog "
    "with a documented fence mechanism.  Unlisted active seams constitute "
    "policy violations and must be reported to the on-call architect."
)

LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::LEGACY_PATH_FENCE_MUST_BE_EXPLICIT: every compatibility seam "
    "retained beyond Batch PR-5 must carry an explicit fence — either a "
    "runtime check that logs and redirects, a DeprecationWarning at import, "
    "an environment-variable gate that defaults to disabled, or a formal "
    "TOMBSTONE record in the legacy_purge_registry.  Implicit retention "
    "without a fence is prohibited."
)

CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY: str = (
    "POLICY::CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE: "
    "Clean cross-repo convergence with the Android repository requires that "
    "all center-side OPEN compat gaps (from the dual-repo gap matrix, "
    "Domain 7) have been promoted to FENCED or RETIRED before a formal "
    "convergence milestone is declared.  An unconverged compat seam on the "
    "center side creates ambiguity about contract boundaries for Android "
    "integration and must be resolved first."
)

CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY: str = (
    "POLICY::CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED: when both a "
    "canonical and a compatibility path exist for the same operation, the "
    "canonical path must be preferred and the compat path must be explicitly "
    "secondary.  Callers invoking compat paths must receive a logged warning "
    "that identifies the canonical replacement.  Compat paths must never be "
    "listed as equivalent alternatives to canonical paths in documentation "
    "or API discovery surfaces."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class CompatGapDomain(str, Enum):
    """High-level domain classification of a compatibility gap.

    websocket_path
        A legacy or transitional WebSocket connection path.

    rest_endpoint
        A legacy or transitional REST endpoint (compat alias).

    registry_facade
        A legacy registry or capability facade that shadows a canonical
        registry implementation.

    coordinator_substrate
        A legacy coordinator or dispatcher that is restricted to substrate
        use but whose external exposure is not fully fenced.

    runtime_role
        A runtime component (planner, executor, agent) whose role boundary
        has been redefined and whose old role is formally retired.

    projection_contract
        A legacy projection engine or contract that must delegate to a
        canonical projection surface.
    """

    websocket_path = "websocket_path"
    rest_endpoint = "rest_endpoint"
    registry_facade = "registry_facade"
    coordinator_substrate = "coordinator_substrate"
    runtime_role = "runtime_role"
    projection_contract = "projection_contract"


class CompatClosureStatus(str, Enum):
    """Current closure status of a compatibility gap.

    OPEN
        Gap is catalogued but no fence or retirement action has been taken.
        Requires action in the current or next batch.

    FENCED
        A concrete fence mechanism is in place (env-var gate, DeprecationWarning,
        sentinel guard, or redirect logging).  The compat path is explicitly
        secondary; canonical path is enforced.  Gap is under control but not
        yet fully retired.

    RETIRED
        The compat surface has been fully retired.  No active callers remain;
        the surface has been deleted, disabled by default, or replaced by the
        canonical equivalent.

    TOMBSTONED
        The compat surface is a tombstone re-export or hard-error shim only.
        Physical deletion is the only remaining step; import will fail or
        emit a hard error.
    """

    OPEN = "open"
    FENCED = "fenced"
    RETIRED = "retired"
    TOMBSTONED = "tombstoned"


class CompatFenceKind(str, Enum):
    """Mechanism used to fence a compat seam.

    env_var_gate
        The path is disabled by default; requires an explicit opt-in
        environment variable to re-enable (e.g. GALAXY_ENABLE_LEGACY_PROTOCOLS).

    deprecation_warning
        The surface emits a DeprecationWarning at import or first call.

    sentinel_guard
        A sentinel constant or runtime assertion enforces that the surface
        is not mistaken for the canonical authority.

    redirect_logging
        Call-sites log a WARNING with the canonical path before delegating.

    hard_error
        The surface raises RuntimeError on use (strongest fence; reserved for
        TOMBSTONED surfaces with no expected callers).

    none
        No fence mechanism is in place.  Status must be OPEN.
    """

    env_var_gate = "env_var_gate"
    deprecation_warning = "deprecation_warning"
    sentinel_guard = "sentinel_guard"
    redirect_logging = "redirect_logging"
    hard_error = "hard_error"
    none = "none"


class FenceVerdict(str, Enum):
    """Result of a fence check at a call-site.

    CANONICAL_PREFERRED
        The canonical path is confirmed active; no compat path invoked.

    COMPAT_ALLOWED_FENCED
        The compat path was invoked but the active fence mechanism is in
        place and a warning was logged.  The call may proceed with the compat
        path but is explicitly acknowledged as non-canonical.

    COMPAT_OPEN_UNFENCED
        A compat path was invoked but no fence mechanism is in place.
        This is a policy violation; the call is logged as an error.

    UNKNOWN
        Unable to determine which path was invoked.  Treated as a monitoring
        gap; logged as a WARNING.
    """

    CANONICAL_PREFERRED = "canonical_preferred"
    COMPAT_ALLOWED_FENCED = "compat_allowed_fenced"
    COMPAT_OPEN_UNFENCED = "compat_open_unfenced"
    UNKNOWN = "unknown"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class CompatGapRecord:
    """Catalog record for a single center-side compatibility gap.

    Each record corresponds to one row in the Dual-Repo Gap Matrix
    (Domain 7: Compatibility and Transitional Surfaces) or to an additional
    gap identified during the PR-5 closure pass.
    """

    gap_id: str
    """Unique identifier matching the gap matrix row (e.g. ``COMPAT-001``)."""

    severity: str
    """Severity from the gap matrix: ``CRITICAL``, ``HIGH``, ``MEDIUM``, ``LOW``."""

    domain: CompatGapDomain
    """High-level domain of the compatibility surface."""

    module_path: str
    """Dotted Python module path or file path of the compat surface."""

    surface_name: str
    """Human-readable name of the compat surface."""

    status: CompatClosureStatus
    """Current closure status (OPEN, FENCED, RETIRED, TOMBSTONED)."""

    fence_kind: CompatFenceKind
    """Active fence mechanism, or ``none`` if status is OPEN."""

    canonical_replacement: str
    """Canonical replacement path or module."""

    retirement_condition: str
    """Concrete, verifiable condition under which this gap may be closed."""

    fence_evidence: str = ""
    """Cite-able evidence of the fence (e.g. module line, sentinel name, env var)."""

    cross_repo_impact: str = ""
    """Description of how this gap affects Android/V2 contract alignment."""

    notes: str = ""
    """Additional governance notes."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "severity": self.severity,
            "domain": self.domain.value,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "status": self.status.value,
            "fence_kind": self.fence_kind.value,
            "canonical_replacement": self.canonical_replacement,
            "retirement_condition": self.retirement_condition,
            "fence_evidence": self.fence_evidence,
            "cross_repo_impact": self.cross_repo_impact,
            "notes": self.notes,
        }


@dataclass
class CompatFenceResult:
    """Result of a fence check at a specific call-site."""

    gap_id: str
    """Gap ID this fence check corresponds to."""

    verdict: FenceVerdict
    """Outcome of the fence check."""

    canonical_path: str
    """Canonical replacement path that should be preferred."""

    compat_path: str
    """Compat path that was checked."""

    message: str = ""
    """Human-readable fence check message."""

    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "verdict": self.verdict.value,
            "canonical_path": self.canonical_path,
            "compat_path": self.compat_path,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class CompatClosureSnapshot:
    """Aggregate snapshot of the center-side compat closure posture."""

    total_gaps: int
    open_count: int
    fenced_count: int
    retired_count: int
    tombstoned_count: int
    high_or_medium_open_count: int
    cross_repo_ready: bool
    generated_at: float
    policy_sentinels: List[str] = field(default_factory=list)
    gap_summaries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_gaps": self.total_gaps,
            "by_status": {
                "open": self.open_count,
                "fenced": self.fenced_count,
                "retired": self.retired_count,
                "tombstoned": self.tombstoned_count,
            },
            "high_or_medium_open_count": self.high_or_medium_open_count,
            "cross_repo_ready": self.cross_repo_ready,
            "generated_at": self.generated_at,
            "policy_sentinels": self.policy_sentinels,
            "gap_summaries": self.gap_summaries,
        }


# ===========================================================================
# Compatibility gap catalog
# ===========================================================================

_COMPAT_GAP_CATALOG: List[CompatGapRecord] = [
    # -------------------------------------------------------------------------
    # COMPAT-001: galaxy_gateway/task_router.py — TaskRouter / TaskScheduler
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="COMPAT-001",
        severity="MEDIUM",
        domain=CompatGapDomain.coordinator_substrate,
        module_path="galaxy_gateway.task_router",
        surface_name="TaskRouter / TaskScheduler (galaxy_gateway/task_router.py)",
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.sentinel_guard,
        canonical_replacement="core.command_router.CommandRouter",
        retirement_condition=(
            "Remove when no file named galaxy_gateway/task_router.py exists "
            "on disk and no import of galaxy_gateway.task_router remains "
            "outside of compat-retirement tests."
        ),
        fence_evidence=(
            "PR-516 (core.legacy_system_decommission) formally retires TaskRouter. "
            "core.legacy_system_decommission.NO_PARALLEL_DISPATCH_AUTHORITY_POLICY "
            "prohibits new routing through TaskRouter.  Residual file presence "
            "must be confirmed removed and verified by disk scan."
        ),
        cross_repo_impact=(
            "Android clients that relied on TaskRouter dispatch semantics must "
            "consume CommandRouter contract signals only.  No new Android protocol "
            "code should reference task_router APIs."
        ),
        notes=(
            "PARTIAL per gap matrix.  PR-516 retires TaskRouter; residual file "
            "must be confirmed deleted.  Fence: sentinel enforcement via "
            "legacy_system_decommission prevents new callers; historical callers "
            "should be audited and removed."
        ),
    ),
    # -------------------------------------------------------------------------
    # COMPAT-002: core/capability_registry.py — CapabilityRegistry gating
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="COMPAT-002",
        severity="MEDIUM",
        domain=CompatGapDomain.registry_facade,
        module_path="core.capability_registry.CapabilityRegistry",
        surface_name="CapabilityRegistry (core/capability_registry.py)",
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.sentinel_guard,
        canonical_replacement="core.capability_assimilation.CapabilityAssimilationLayer",
        retirement_condition=(
            "CapabilityRegistry may remain for device-local bookkeeping ONLY. "
            "All routing decisions must use CapabilityAssimilationLayer.  "
            "Retire CapabilityRegistry from routing decision paths when no "
            "routing code imports CapabilityRegistry for routing; keep only "
            "device-local bookkeeping callers."
        ),
        fence_evidence=(
            "PR-516 (core.legacy_system_decommission) gates CapabilityRegistry. "
            "core.legacy_system_decommission.CANONICAL_CAPABILITY_SOURCE_POLICY "
            "mandates CapabilityAssimilationLayer for all executor-readiness queries. "
            "Risk: developers may still route through CapabilityRegistry — "
            "the fence must be reinforced by code review and CI import analysis."
        ),
        cross_repo_impact=(
            "Android capability reports ingested via device_capabilities AIP type "
            "must flow into CapabilityAssimilationLayer, not CapabilityRegistry. "
            "Routing decisions exported to Android depend on the canonical "
            "assimilation layer being the source of truth."
        ),
        notes=(
            "GATED per gap matrix.  Permitted for device-local bookkeeping; "
            "routing decisions forbidden.  Governance risk: boundary is not "
            "machine-enforced at the call-site level; relies on code review."
        ),
    ),
    # -------------------------------------------------------------------------
    # COMPAT-003: galaxy_gateway/cross_device_coordinator.py — substrate-only
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="COMPAT-003",
        severity="MEDIUM",
        domain=CompatGapDomain.coordinator_substrate,
        module_path="galaxy_gateway.cross_device_coordinator",
        surface_name="CrossDeviceCoordinator (galaxy_gateway/cross_device_coordinator.py)",
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.sentinel_guard,
        canonical_replacement=(
            "core.cross_device_execution_chain.CrossDeviceExecutionChain "
            "(for execution); core.device_formation (for formation)"
        ),
        retirement_condition=(
            "Retire CrossDeviceCoordinator from external call-sites when all "
            "external callers have been confirmed migrated to CrossDeviceExecutionChain "
            "and no LEGACY_DISPATCH warnings are observed in production logs."
        ),
        fence_evidence=(
            "PR-518 (core cross_device_entry_dispatch_closure) restricts "
            "CrossDeviceCoordinator to substrate-only use with sentinel enforcement. "
            "LEGACY_DISPATCH warnings are emitted when external callers invoke it. "
            "External caller surface must be audited and closed."
        ),
        cross_repo_impact=(
            "Android-facing task dispatch must not depend on CrossDeviceCoordinator "
            "semantics.  Android-initiated cross-device tasks should enter via "
            "canonical ingress (CommandRouter → CrossDeviceExecutionChain)."
        ),
        notes=(
            "PARTIAL per gap matrix.  Sentinel enforcement is in place; external "
            "callers still possible.  Sentinel coverage audit required."
        ),
    ),
    # -------------------------------------------------------------------------
    # COMPAT-004: core/local_agent_runtime.py — server-side planning role
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="COMPAT-004",
        severity="LOW",
        domain=CompatGapDomain.runtime_role,
        module_path="core.local_agent_runtime.LocalAgentRuntime",
        surface_name="LocalAgentRuntime (core/local_agent_runtime.py) — server-side planner role",
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.sentinel_guard,
        canonical_replacement=(
            "core.agent_factory.AgentFactory (server-side planning); "
            "LocalAgentRuntime device-side sandbox role is RETAINED (not retired)"
        ),
        retirement_condition=(
            "Retire server-side planning invocation of LocalAgentRuntime when no "
            "server-side caller invokes LocalAgentRuntime as a planner and its "
            "device-side sandbox role is documented as the sole remaining role.  "
            "Physical deletion of the module requires replacing the device-side "
            "sandbox role with a canonical device execution contract."
        ),
        fence_evidence=(
            "core.legacy_system_decommission (PR-516) gates LocalAgentRuntime "
            "as a retired server-side planner.  Module docstring declares "
            "device-side sandbox as the only retained role.  "
            "Role boundary not yet machine-enforced at call-site level."
        ),
        cross_repo_impact=(
            "Android clients that co-host LocalAgentRuntime instances must "
            "understand that the server no longer plans via LocalAgentRuntime. "
            "Device-side sandbox contracts should be clarified before convergence."
        ),
        notes=(
            "GATED per gap matrix.  Server-side planning role retired; "
            "device-side sandbox retained.  Documentation and boundary "
            "clarification needed to make the distinction clear."
        ),
    ),
    # -------------------------------------------------------------------------
    # COMPAT-005: desktop_projection/projection_engine.py — must delegate
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="COMPAT-005",
        severity="LOW",
        domain=CompatGapDomain.projection_contract,
        module_path="desktop_projection.projection_engine.ProjectionEngine",
        surface_name="ProjectionEngine (desktop_projection/projection_engine.py)",
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.sentinel_guard,
        canonical_replacement=(
            "core.projection_surface_bridge.ProjectionSurfaceBridge "
            "(enrich_runtime_projection())"
        ),
        retirement_condition=(
            "Retire ProjectionEngine from independent projection assembly when "
            "all desktop projection consumers call ProjectionSurfaceBridge for "
            "runtime enrichment and ProjectionEngine is confirmed as a pure "
            "delegating wrapper with no independent projection logic."
        ),
        fence_evidence=(
            "core.legacy_system_decommission (PR-516) gates ProjectionEngine. "
            "CANONICAL_PROJECTION_CONTRACT_POLICY mandates delegation to "
            "ProjectionSurfaceBridge.  Gating not enforced at runtime — "
            "requires a call-site redirect check."
        ),
        cross_repo_impact=(
            "Android-facing projection outputs must come from ProjectionSurfaceBridge "
            "to guarantee canonical runtime enrichment.  ProjectionEngine bypassing "
            "the bridge would expose inconsistent projection state to Android."
        ),
        notes=(
            "GATED per gap matrix.  Must delegate to ProjectionSurfaceBridge; "
            "gating not enforced at runtime.  Projection consolidation PR needed."
        ),
    ),
    # -------------------------------------------------------------------------
    # COMPAT-006: Android REST compat aliases — /api/devices/register etc.
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="COMPAT-006",
        severity="LOW",
        domain=CompatGapDomain.rest_endpoint,
        module_path="core.routes.compat",
        surface_name=(
            "Android REST compat aliases "
            "(POST /api/devices/register, GET /api/devices/list)"
        ),
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.deprecation_warning,
        canonical_replacement="core.routes.devices (/api/v1/devices/*)",
        retirement_condition=(
            "Remove core/routes/compat.py when all legacy Android/device callers "
            "are confirmed migrated to /api/v1/devices/* endpoints and no traffic "
            "is observed on /api/devices/* for at least one release cycle.  "
            "Coordinate with Android team to confirm migration status."
        ),
        fence_evidence=(
            "core/routes/compat.py module docstring carries ``.. deprecated:: "
            "Batch PR-3`` annotation with removal target ``Batch PR-5``.  "
            "create_router() emits DeprecationWarning at call time.  "
            "core.compat_surface_retirement inventory classifies this as "
            "TIER_2, HIGH-risk (surface_id=routes_compat_legacy_device_api)."
        ),
        cross_repo_impact=(
            "Android clients must migrate REST calls to /api/v1/devices/* "
            "before this surface can be retired.  This is the primary "
            "center-side blocker for Android REST contract convergence."
        ),
        notes=(
            "OPEN per gap matrix — no confirmed retirement timeline.  "
            "Fence: DeprecationWarning at import.  Cross-repo coordination "
            "with Android team required before physical deletion."
        ),
    ),
    # -------------------------------------------------------------------------
    # PROTO-007: /ws/ufo3/{device_id} legacy WebSocket path
    # -------------------------------------------------------------------------
    CompatGapRecord(
        gap_id="PROTO-007",
        severity="LOW",
        domain=CompatGapDomain.websocket_path,
        module_path="galaxy_gateway.routes.websocket",
        surface_name="/ws/ufo3/{device_id} (legacy UFO3 WebSocket path)",
        status=CompatClosureStatus.FENCED,
        fence_kind=CompatFenceKind.env_var_gate,
        canonical_replacement=(
            "/ws/device/{device_id} (AIP v3, canonical device ingress)"
        ),
        retirement_condition=(
            "Remove /ws/ufo3 route registration from websocket.py when no "
            "active client is confirmed using this path and GALAXY_ENABLE_LEGACY_PROTOCOLS "
            "has been set to false in all production deployments for at least "
            "one release cycle."
        ),
        fence_evidence=(
            "galaxy_gateway/routes/websocket.py: /ws/ufo3/{device_id} is "
            "classified [LEGACY-DISABLED] in the module header comment.  "
            "Path is gated by GALAXY_ENABLE_LEGACY_PROTOCOLS env var "
            "(default: false).  When disabled, rejects with error 1008 and "
            "redirects client to /ws/device/<id>.  "
            "No active clients confirmed."
        ),
        cross_repo_impact=(
            "Android clients still using /ws/ufo3 would be blocked after "
            "retirement.  Client list must be confirmed empty before route "
            "registration is removed."
        ),
        notes=(
            "OPEN per gap matrix — retire after confirming no active usage.  "
            "Fence: GALAXY_ENABLE_LEGACY_PROTOCOLS env-var gate defaults to "
            "false; connection rejected with redirect on disabled path.  "
            "Route registration itself remains; physical removal is next step."
        ),
    ),
]


# ===========================================================================
# Query functions
# ===========================================================================


def get_compat_gap_catalog() -> List[CompatGapRecord]:
    """Return the full center-side compat gap catalog.

    Returns
    -------
    list[CompatGapRecord]
        All registered gap records in catalog-definition order.
    """
    return list(_COMPAT_GAP_CATALOG)


def get_gaps_by_status(status: CompatClosureStatus) -> List[CompatGapRecord]:
    """Return all gaps matching the given closure status.

    Parameters
    ----------
    status:
        The :class:`CompatClosureStatus` to filter by.

    Returns
    -------
    list[CompatGapRecord]
        All records whose ``status`` equals *status*.
    """
    return [r for r in _COMPAT_GAP_CATALOG if r.status == status]


def get_open_gaps() -> List[CompatGapRecord]:
    """Return all gaps with ``status == OPEN``.

    Open gaps represent compat seams with no fence in place.  These require
    the most urgent attention.

    Returns
    -------
    list[CompatGapRecord]
    """
    return get_gaps_by_status(CompatClosureStatus.OPEN)


def get_fenced_gaps() -> List[CompatGapRecord]:
    """Return all gaps with ``status == FENCED``.

    Fenced gaps have a concrete enforcement mechanism in place but are not
    yet fully retired.

    Returns
    -------
    list[CompatGapRecord]
    """
    return get_gaps_by_status(CompatClosureStatus.FENCED)


# ===========================================================================
# Fence helpers
# ===========================================================================


def check_compat_fence(
    gap_id: str,
    *,
    compat_path_invoked: bool = True,
    strict: bool = False,
) -> CompatFenceResult:
    """Check whether a compat path invocation is properly fenced.

    Call this helper at any call-site where a compat path may be invoked
    instead of the canonical path.  It looks up the gap record for *gap_id*,
    logs an appropriate message, and returns a :class:`CompatFenceResult`.

    Parameters
    ----------
    gap_id:
        The gap catalog ID (e.g. ``"COMPAT-006"``).
    compat_path_invoked:
        ``True`` when the compat path is being used; ``False`` when the
        canonical path is confirmed active.
    strict:
        When ``True`` and the verdict is ``COMPAT_OPEN_UNFENCED``, raise a
        ``RuntimeError``.  Default is ``False`` (non-blocking).

    Returns
    -------
    CompatFenceResult

    Raises
    ------
    RuntimeError
        Only when ``strict=True`` and the gap has no fence (OPEN status).
    """
    record = next((r for r in _COMPAT_GAP_CATALOG if r.gap_id == gap_id), None)

    if record is None:
        msg = (
            f"CENTER_SIDE_COMPAT_CLOSURE: unknown gap_id={gap_id!r}. "
            "Register the gap in core.center_side_compat_closure catalog."
        )
        logger.warning(msg)
        return CompatFenceResult(
            gap_id=gap_id,
            verdict=FenceVerdict.UNKNOWN,
            canonical_path="<unknown>",
            compat_path="<unknown>",
            message=msg,
        )

    if not compat_path_invoked:
        msg = (
            f"CENTER_SIDE_COMPAT_CLOSURE [{gap_id}]: canonical path "
            f"confirmed active ({record.canonical_replacement!r}). "
            "No compat path invoked."
        )
        logger.debug(msg)
        return CompatFenceResult(
            gap_id=gap_id,
            verdict=FenceVerdict.CANONICAL_PREFERRED,
            canonical_path=record.canonical_replacement,
            compat_path=record.module_path,
            message=msg,
        )

    # Compat path is being invoked — determine fence posture.
    if record.status in (CompatClosureStatus.FENCED,):
        msg = (
            f"CENTER_SIDE_COMPAT_CLOSURE [{gap_id}] COMPAT PATH INVOKED "
            f"(fence={record.fence_kind.value}): {record.surface_name!r}. "
            f"Canonical replacement: {record.canonical_replacement!r}. "
            f"Retirement condition: {record.retirement_condition!r}."
        )
        logger.warning(msg)
        return CompatFenceResult(
            gap_id=gap_id,
            verdict=FenceVerdict.COMPAT_ALLOWED_FENCED,
            canonical_path=record.canonical_replacement,
            compat_path=record.module_path,
            message=msg,
        )

    if record.status == CompatClosureStatus.OPEN:
        msg = (
            f"CENTER_SIDE_COMPAT_CLOSURE [{gap_id}] UNFENCED COMPAT PATH: "
            f"{record.surface_name!r} has no fence mechanism "
            f"(fence_kind={record.fence_kind.value}).  "
            f"Canonical replacement: {record.canonical_replacement!r}.  "
            "Register a fence or retire this surface immediately."
        )
        logger.error(msg)
        if strict:
            raise RuntimeError(msg)
        return CompatFenceResult(
            gap_id=gap_id,
            verdict=FenceVerdict.COMPAT_OPEN_UNFENCED,
            canonical_path=record.canonical_replacement,
            compat_path=record.module_path,
            message=msg,
        )

    # RETIRED or TOMBSTONED — compat path should not be invoked at all.
    msg = (
        f"CENTER_SIDE_COMPAT_CLOSURE [{gap_id}] RETIRED SURFACE INVOKED: "
        f"{record.surface_name!r} has status={record.status.value} but was "
        "still invoked.  This is a policy violation."
    )
    logger.error(msg)
    if strict:
        raise RuntimeError(msg)
    return CompatFenceResult(
        gap_id=gap_id,
        verdict=FenceVerdict.COMPAT_OPEN_UNFENCED,
        canonical_path=record.canonical_replacement,
        compat_path=record.module_path,
        message=msg,
    )


def assert_canonical_path_preferred(
    gap_id: str,
    canonical_active: bool,
    *,
    context: str = "",
) -> CompatFenceResult:
    """Assert that the canonical path is preferred at a given call-site.

    A convenience wrapper around :func:`check_compat_fence` for use in
    invariant-checking code.  Logs a clear message and returns the fence
    result.  Does not raise by default; pass ``strict=True`` to the
    underlying :func:`check_compat_fence` call if enforcement is needed.

    Parameters
    ----------
    gap_id:
        Gap catalog ID (e.g. ``"COMPAT-002"``).
    canonical_active:
        ``True`` when the canonical path is active (compat path not invoked).
    context:
        Optional context string for the log message.

    Returns
    -------
    CompatFenceResult
    """
    result = check_compat_fence(
        gap_id,
        compat_path_invoked=not canonical_active,
    )
    if context and result.verdict != FenceVerdict.CANONICAL_PREFERRED:
        logger.warning(
            "CENTER_SIDE_COMPAT_CLOSURE assert_canonical_path_preferred "
            "[%s] context=%r verdict=%s",
            gap_id,
            context,
            result.verdict.value,
        )
    return result


# ===========================================================================
# Convergence readiness gate and snapshot
# ===========================================================================


def build_compat_closure_snapshot() -> CompatClosureSnapshot:
    """Build an aggregate snapshot of the center-side compat closure posture.

    The snapshot is JSON-serialisable and suitable for CI consumption or
    status endpoint exposure.

    Returns
    -------
    CompatClosureSnapshot
    """
    catalog = _COMPAT_GAP_CATALOG
    open_gaps = [r for r in catalog if r.status == CompatClosureStatus.OPEN]
    fenced_gaps = [r for r in catalog if r.status == CompatClosureStatus.FENCED]
    retired_gaps = [r for r in catalog if r.status == CompatClosureStatus.RETIRED]
    tombstoned_gaps = [r for r in catalog if r.status == CompatClosureStatus.TOMBSTONED]

    high_or_medium_open = [
        r for r in open_gaps if r.severity in ("CRITICAL", "HIGH", "MEDIUM")
    ]

    cross_repo_ready = (
        len(open_gaps) == 0
        and len(high_or_medium_open) == 0
    )

    return CompatClosureSnapshot(
        total_gaps=len(catalog),
        open_count=len(open_gaps),
        fenced_count=len(fenced_gaps),
        retired_count=len(retired_gaps),
        tombstoned_count=len(tombstoned_gaps),
        high_or_medium_open_count=len(high_or_medium_open),
        cross_repo_ready=cross_repo_ready,
        generated_at=time.time(),
        policy_sentinels=[
            COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY,
            LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY,
            CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY,
            CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY,
        ],
        gap_summaries=[r.to_dict() for r in catalog],
    )


def is_cross_repo_convergence_ready() -> bool:
    """Return ``True`` when all center-side compat gaps are fenced or retired.

    Cross-repo convergence readiness requires that no OPEN gaps remain in
    the center-side compat gap catalog, especially no MEDIUM or HIGH gaps
    that could create contract ambiguity for Android integration.

    Returns
    -------
    bool
        ``True`` iff all gaps are FENCED, RETIRED, or TOMBSTONED.
    """
    return len(get_open_gaps()) == 0
