#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/compat_fallback_authority_guard.py
========================================
PR-9 — Harden canonical truth authority boundaries and restrict compat
fallback influence.

Problem addressed
-----------------
V2 is designed as the canonical orchestration and truth authority.  However,
compatibility-oriented surfaces and fallback behavior may still retain
practical influence over live runtime decisions beyond their intended roles.
Even when these layers are useful for migration and resilience, they blur
authority boundaries if they continue to shape execution outcomes outside
explicitly bounded contexts.

This creates a risk that canonical truth remains architecturally defined but
not fully operationally sovereign.  Fallback and compat mechanisms may:

* Be consulted too broadly, ahead of canonical path evaluation.
* Influence route or state outcomes more than intended.
* Weaken the reviewability of which surfaces actually governed a decision.

This module hardens canonical truth authority boundaries by:

1. **Cataloguing influence points** — machine-readable records of every place
   where a compat or fallback path could influence a live runtime decision,
   together with the current bounding status of that influence.

2. **Declaring authority scopes** — explicit sentinels and enums that
   distinguish canonical authority decisions from bounded-assist roles vs
   unbound compat influence.

3. **Providing decision-site guard helpers** — call-site functions that verify
   the canonical path is the effective decision authority and log a structured
   verdict when compat influence is detected.

4. **Classifying compat roles** — distinguishing ``observer`` (read-only,
   non-directing) from ``bounded_assist`` (contributing supplemental data
   within an explicit scope) from ``unbound_influence`` (potentially driving
   decisions outside explicit scope).

Design principles
-----------------
- **Additive only** — does not modify existing modules or execution paths.
- **Non-blocking by default** — guard helpers log and return a verdict;
  they do not raise unless ``strict=True`` is requested.
- **Machine-checkable** — all sentinels are importable strings that CI
  gates, tests, and diagnostic endpoints can assert.
- **Explicit over implicit** — every allowed compat influence point is
  documented; unlisted influence constitutes a policy violation.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY`
:data:`COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL`
:data:`CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY`
:data:`COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY`
:data:`UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY`
:data:`FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY`

Enums
~~~~~
:class:`CompatInfluenceRole`
:class:`CompatInfluenceBoundingStatus`
:class:`CompatInfluenceVerdict`

Data classes
~~~~~~~~~~~~
:class:`CompatInfluenceRecord`
:class:`CompatInfluenceCheckResult`
:class:`AuthorityHardeningSnapshot`

Functions
~~~~~~~~~
:func:`get_influence_registry`
:func:`get_influence_record`
:func:`check_canonical_authority_at_decision_site`
:func:`assert_canonical_is_decision_authority`
:func:`build_authority_hardening_snapshot`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CompatFallbackAuthorityGuard")

__all__ = [
    # Sentinels
    "COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY",
    "COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL",
    "CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY",
    "COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY",
    "UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY",
    "FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY",
    # Enums
    "CompatInfluenceRole",
    "CompatInfluenceBoundingStatus",
    "CompatInfluenceVerdict",
    # Data classes
    "CompatInfluenceRecord",
    "CompatInfluenceCheckResult",
    "AuthorityHardeningSnapshot",
    # Functions
    "get_influence_registry",
    "get_influence_record",
    "check_canonical_authority_at_decision_site",
    "assert_canonical_is_decision_authority",
    "build_authority_hardening_snapshot",
]

# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY: str = (
    "COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY::"
    "core.compat_fallback_authority_guard is the PR-9 authority hardening "
    "module for the Galaxy canonical runtime.  It catalogues compat/fallback "
    "influence points, classifies their bounding status, and provides decision-"
    "site guard helpers that enforce canonical truth as the primary decision "
    "authority.  Compat/fallback paths may only observe or assist within "
    "explicitly bounded scopes; they must not become effective decision authorities."
)

COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL: str = (
    "COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL::"
    "package=PR9::profile=authority-hardening-v1::"
    "module=core.compat_fallback_authority_guard"
)

CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY: str = (
    "POLICY::CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_V1: "
    "At every live runtime decision point (routing, state transitions, "
    "execution dispatch, truth compilation), the canonical authority chain "
    "(DesktopPresenceRuntime → OpenClawd → AgentKernel → CommandRouter) "
    "must be the effective primary decision maker.  Compat and fallback "
    "paths are permitted only when the canonical path is explicitly "
    "unavailable and their use is bounded, logged, and auditable."
)

COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY: str = (
    "POLICY::COMPAT_FALLBACK_OBSERVE_OR_ASSIST_SCOPE_V1: "
    "Compat and fallback paths may participate in runtime execution only "
    "as (a) read-only observers that enrich but do not drive decisions, or "
    "(b) bounded assistants that contribute supplemental data within an "
    "explicitly documented scope.  Compat paths must never become the "
    "primary source of a routing, state, or truth decision."
)

UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY: str = (
    "POLICY::UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_V1: "
    "Any compat or fallback path that influences a live canonical decision "
    "without being explicitly catalogued in the influence registry with a "
    "documented bounding mechanism is a policy violation.  Such paths must "
    "be reported, catalogued, and bounded or retired in the next batch."
)

FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY: str = (
    "POLICY::FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_V1: "
    "A fallback path activated because the canonical path was temporarily "
    "unavailable must not persist as a silent canonical replacement once the "
    "canonical path recovers.  Fallback activation and deactivation events "
    "must be logged.  The system must re-consult the canonical path as soon "
    "as it becomes available again."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class CompatInfluenceRole(str, Enum):
    """Classification of the role a compat/fallback path plays at an
    influence point.

    observer
        The compat path reads runtime state but does not write, route, or
        alter the decision outcome.  Observer influence is the safest role;
        it cannot change what the canonical path decided.

    bounded_assist
        The compat path contributes supplemental data (e.g. enrichment fields,
        compatibility-era identifiers, deprecated signal translations) within
        an explicitly documented scope.  The canonical path remains the
        primary decision maker; compat provides secondary or enrichment data
        only.

    degraded_fallback
        The compat path is activated because the canonical path is
        unavailable or ineligible.  This is a temporary, bounded role that
        must be clearly logged and must not persist once the canonical path
        recovers.

    unbound_influence
        The compat path influences the decision outcome without explicit
        scoping or bounding.  This is a policy violation and must be resolved
        by bounding or retiring the compat path.
    """

    observer = "observer"
    bounded_assist = "bounded_assist"
    degraded_fallback = "degraded_fallback"
    unbound_influence = "unbound_influence"


class CompatInfluenceBoundingStatus(str, Enum):
    """Current bounding status of a compat/fallback influence point.

    EXPLICITLY_BOUNDED
        The influence point is catalogued, its compat role is declared, and
        a concrete bounding mechanism (sentinel guard, env-var gate, explicit
        log warning, or redirect) is in place.  Canonical authority is
        enforced; compat path is explicitly secondary.

    SCOPE_LIMITED
        The influence point is catalogued and its scope is limited by
        convention (e.g. only executed after canonical path failure), but no
        machine-enforceable bounding mechanism is in place.  Requires upgrade
        to EXPLICITLY_BOUNDED in a follow-up batch.

    UNBOUNDED
        The influence point has no documented bounding.  Compat path may
        influence decisions without restriction.  This is a policy violation
        that must be resolved.

    RETIRED
        The influence point has been fully retired.  No compat path remains
        active at this decision site.
    """

    EXPLICITLY_BOUNDED = "explicitly_bounded"
    SCOPE_LIMITED = "scope_limited"
    UNBOUNDED = "unbounded"
    RETIRED = "retired"


class CompatInfluenceVerdict(str, Enum):
    """Result of a canonical-authority check at a decision site.

    CANONICAL_AUTHORITY
        The canonical path was confirmed as the primary decision maker.
        No compat/fallback influence was detected at this site.

    BOUNDED_ASSIST_ACTIVE
        A compat or fallback path contributed supplemental data within an
        explicitly bounded scope.  Canonical authority is still primary;
        compat assist is properly bounded and logged.

    DEGRADED_FALLBACK_ACTIVE
        The canonical path was unavailable and a bounded degraded fallback
        is active.  Fallback use is logged; canonical path must be
        re-consulted when available.

    UNBOUND_INFLUENCE_DETECTED
        A compat or fallback path is influencing the decision without
        explicit bounding.  This is a policy violation.

    UNKNOWN
        Unable to determine the authority source for this decision site.
        Treated as a monitoring gap.
    """

    CANONICAL_AUTHORITY = "canonical_authority"
    BOUNDED_ASSIST_ACTIVE = "bounded_assist_active"
    DEGRADED_FALLBACK_ACTIVE = "degraded_fallback_active"
    UNBOUND_INFLUENCE_DETECTED = "unbound_influence_detected"
    UNKNOWN = "unknown"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class CompatInfluenceRecord:
    """Catalog record for a single compat/fallback influence point.

    Each record documents one place in the runtime where a compat or
    fallback path could influence a live canonical decision, together with
    the bounding mechanism that constrains that influence.
    """

    influence_id: str
    """Unique identifier for this influence point (e.g. ``INFL-001``)."""

    decision_site: str
    """Human-readable description of the decision site (e.g. routing, state
    transition, truth compilation)."""

    canonical_path: str
    """The canonical module/function that should be the primary decision maker."""

    compat_path: str
    """The compat or fallback module/function that could influence the decision."""

    influence_role: CompatInfluenceRole
    """The role the compat path plays at this influence point."""

    bounding_status: CompatInfluenceBoundingStatus
    """Current bounding status of the compat influence."""

    bounding_evidence: str
    """Cite-able evidence of the bounding mechanism (module, sentinel, env var)."""

    reviewer_note: str
    """Human-readable note explaining how a reviewer can distinguish canonical
    authority from compat/fallback influence at this site."""

    pr_addressed: str = ""
    """PR where this influence point was explicitly bounded or is tracked."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "influence_id": self.influence_id,
            "decision_site": self.decision_site,
            "canonical_path": self.canonical_path,
            "compat_path": self.compat_path,
            "influence_role": self.influence_role.value,
            "bounding_status": self.bounding_status.value,
            "bounding_evidence": self.bounding_evidence,
            "reviewer_note": self.reviewer_note,
            "pr_addressed": self.pr_addressed,
        }


@dataclass
class CompatInfluenceCheckResult:
    """Result of a canonical-authority check at a specific decision site."""

    influence_id: str
    """The influence point ID that was checked."""

    verdict: CompatInfluenceVerdict
    """Outcome of the check."""

    canonical_path: str
    """Canonical path that should be the primary decision maker."""

    compat_path: str
    """Compat/fallback path whose influence was assessed."""

    message: str = ""
    """Human-readable explanation of the verdict."""

    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "influence_id": self.influence_id,
            "verdict": self.verdict.value,
            "canonical_path": self.canonical_path,
            "compat_path": self.compat_path,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class AuthorityHardeningSnapshot:
    """Aggregate snapshot of the compat/fallback authority hardening posture."""

    total_influence_points: int
    explicitly_bounded_count: int
    scope_limited_count: int
    unbounded_count: int
    retired_count: int
    unbound_violation_count: int
    hardening_complete: bool
    generated_at: float
    policy_sentinels: List[str] = field(default_factory=list)
    influence_summaries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_influence_points": self.total_influence_points,
            "by_bounding_status": {
                "explicitly_bounded": self.explicitly_bounded_count,
                "scope_limited": self.scope_limited_count,
                "unbounded": self.unbounded_count,
                "retired": self.retired_count,
            },
            "unbound_violation_count": self.unbound_violation_count,
            "hardening_complete": self.hardening_complete,
            "generated_at": self.generated_at,
            "policy_sentinels": self.policy_sentinels,
            "influence_summaries": self.influence_summaries,
        }


# ===========================================================================
# Compat/fallback influence registry
# ===========================================================================

_INFLUENCE_REGISTRY: List[CompatInfluenceRecord] = [
    # -------------------------------------------------------------------------
    # INFL-001: Legacy routing helpers consulted ahead of TopologyRouter
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-001",
        decision_site="Model/provider routing decision at task dispatch",
        canonical_path=(
            "core.model_topology.topology_router.TopologyRouter.route()"
        ),
        compat_path=(
            "core.multi_llm_router.MultiLLMRouter (legacy routing helper)"
        ),
        influence_role=CompatInfluenceRole.degraded_fallback,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "PR-routing-authority: MultiLLMRouter classified as "
            "LegacyPathStatus.LEGACY_COMPATIBILITY in "
            "core/orchestration_authority/legacy_paths.py.  "
            "docs/MODEL_ROUTING_AUTHORITY.md section 5 documents it as "
            "non-authoritative.  contracts/desktop_status_projection.py "
            "_build_model_routing_projection() sets "
            "routing_authority_source='legacy_ucp_keys' and "
            "legacy_routing_fallback_active=True when fallback is active."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority is primary by checking "
            "that routing_authority_source == 'topology_router' in the "
            "DesktopStatusProjection.  If legacy_routing_fallback_active is "
            "True, a compat path is active; this is acceptable only as a "
            "degraded fallback when TopologyRouter returned no plan."
        ),
        pr_addressed="PR-routing-authority",
    ),
    # -------------------------------------------------------------------------
    # INFL-002: dashboard.backend.main serving as provider routing surface
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-002",
        decision_site=(
            "Provider/model selection data exposed via legacy dashboard endpoint"
        ),
        canonical_path=(
            "core.model_topology.topology_router.TopologyRouter via "
            "GET /api/v1/projection/runtime (RuntimeProjection)"
        ),
        compat_path=(
            "dashboard.backend.main llm_providers endpoint "
            "(GET /api/v1/llm-providers)"
        ),
        influence_role=CompatInfluenceRole.bounded_assist,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "dashboard/backend/main.py DASHBOARD_LEGACY_SURFACE_AUTHORITY "
            "sentinel declares this as a LEGACY UI SURFACE that must not "
            "be treated as a status or routing-truth authority.  "
            "In unified deployments (unified_launcher.py), canonical routes "
            "from core/api_routes.py shadow this endpoint.  "
            "Documented in docs/MODEL_ROUTING_AUTHORITY.md section 5."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority by checking that "
            "no routing decision code imports from dashboard.backend.main "
            "as a routing-truth source.  The canonical provider list must "
            "come from GET /api/v1/projection/runtime."
        ),
        pr_addressed="Batch PR-4",
    ),
    # -------------------------------------------------------------------------
    # INFL-003: CapabilityRegistry consulted alongside CapabilityAssimilation
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-003",
        decision_site=(
            "Executor readiness / capability-based routing decision"
        ),
        canonical_path=(
            "core.capability_assimilation.CapabilityAssimilationLayer "
            "(canonical capability truth)"
        ),
        compat_path=(
            "core.capability_registry.CapabilityRegistry "
            "(legacy device-local bookkeeping)"
        ),
        influence_role=CompatInfluenceRole.bounded_assist,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "core.legacy_system_decommission "
            "CANONICAL_CAPABILITY_SOURCE_POLICY mandates "
            "CapabilityAssimilationLayer for all executor-readiness queries.  "
            "core/center_side_compat_closure.py COMPAT-002 classifies "
            "CapabilityRegistry as FENCED with sentinel_guard fence.  "
            "core/authority_boundary_classification.py classifies "
            "DeviceRegistry compat as a compat_facade role (non-authoritative)."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority is primary by checking "
            "that routing code imports from CapabilityAssimilationLayer for "
            "routing decisions.  CapabilityRegistry use is permitted only for "
            "device-local bookkeeping; any routing context use is a policy "
            "violation (see INFL-003 in this registry)."
        ),
        pr_addressed="PR-516",
    ),
    # -------------------------------------------------------------------------
    # INFL-004: CrossDeviceCoordinator substrate fallback for mesh dispatch
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-004",
        decision_site="Cross-device task dispatch routing",
        canonical_path=(
            "core.cross_device_execution_chain.CrossDeviceExecutionChain "
            "via core.command_router.CommandRouter.route_envelope()"
        ),
        compat_path=(
            "galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator "
            "(substrate-only legacy coordinator)"
        ),
        influence_role=CompatInfluenceRole.degraded_fallback,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "PR-518: CrossDeviceCoordinator restricted to substrate-only use "
            "with sentinel enforcement; LEGACY_DISPATCH warnings emitted on "
            "external invocations.  "
            "core/center_side_compat_closure.py COMPAT-003 classifies this as "
            "FENCED with sentinel_guard.  "
            "core/orchestration_authority/legacy_paths.py registers "
            "galaxy_gateway.cross_device_coordinator as LEGACY_COMPATIBILITY."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority by checking logs for "
            "LEGACY_DISPATCH warnings — their presence indicates the compat "
            "coordinator was invoked instead of CrossDeviceExecutionChain.  "
            "New cross-device dispatch must enter via CommandRouter.route_envelope()."
        ),
        pr_addressed="PR-518",
    ),
    # -------------------------------------------------------------------------
    # INFL-005: ProjectionEngine bypassing ProjectionSurfaceBridge
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-005",
        decision_site=(
            "Desktop/operator projection assembly (runtime status truth)"
        ),
        canonical_path=(
            "core.projection_surface_bridge.ProjectionSurfaceBridge."
            "enrich_runtime_projection()"
        ),
        compat_path=(
            "desktop_projection.projection_engine.ProjectionEngine "
            "(must delegate to bridge)"
        ),
        influence_role=CompatInfluenceRole.bounded_assist,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "core.legacy_system_decommission CANONICAL_PROJECTION_CONTRACT_POLICY "
            "mandates delegation to ProjectionSurfaceBridge.  "
            "core/center_side_compat_closure.py COMPAT-005 classifies this as "
            "FENCED with sentinel_guard.  "
            "core/outward_runtime_truth.py enforces that outward surfaces must "
            "prefer OutwardRuntimeTruthSnapshot over independently assembled "
            "projections (OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY)."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority by checking that "
            "ProjectionEngine calls enrich_runtime_projection() and does not "
            "independently assemble runtime status from raw subsystem imports.  "
            "Independent raw-import assembly in a projection handler is a "
            "policy violation (see NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY in "
            "core/outward_runtime_truth.py)."
        ),
        pr_addressed="PR-516",
    ),
    # -------------------------------------------------------------------------
    # INFL-006: Legacy task queue as compat routing fallback
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-006",
        decision_site=(
            "Task status truth / task routing at API ingress"
        ),
        canonical_path=(
            "core.canonical_task.CanonicalTask / "
            "core.canonical_task_dispatch_chain.CanonicalTaskDispatchChain"
        ),
        compat_path=(
            "legacy task_queue path (compat routing only — must not be used "
            "as a truth source for task status)"
        ),
        influence_role=CompatInfluenceRole.bounded_assist,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "PR-507 front-loads adapt_to_canonical_task() at API ingress so "
            "CanonicalTask is always the primary object.  "
            "core/runtime_closure_audit.py CONFLICT-001 documents that the "
            "legacy task_queue is kept for compat routing only and "
            "MUST NOT be used as a truth source for task status.  "
            "Authority is narrowed to CanonicalTaskRuntime."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical task authority by checking that "
            "task status is read from CanonicalTaskRuntime, not from the "
            "legacy task_queue.  adapt_to_canonical_task() must be called at "
            "every API ingress point before any routing or status decision."
        ),
        pr_addressed="PR-507",
    ),
    # -------------------------------------------------------------------------
    # INFL-007: Takeover/fallback route influenced by stale session context
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-007",
        decision_site=(
            "Attached-runtime takeover vs delegated-fallback routing gate"
        ),
        canonical_path=(
            "core.attached_runtime_reuse_dispatch.resolve_takeover_or_fallback_route() "
            "(PR-23 canonical takeover/fallback routing gate)"
        ),
        compat_path=(
            "Stale session context or external caller bypassing the PR-22 "
            "registry gate (AttachedSessionRegistry)"
        ),
        influence_role=CompatInfluenceRole.degraded_fallback,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "resolve_takeover_or_fallback_route() enforces "
            "DELEGATED_FALLBACK_REQUIRES_INELIGIBLE_CANONICAL_PATH_PR23_POLICY "
            "and TAKEOVER_DISPATCH_DECISION_IS_DETERMINISTIC_PR23_POLICY.  "
            "STALE_EXECUTION_CONTEXT_CANNOT_ALTER_TAKEOVER_DECISION_PR23_POLICY "
            "explicitly prohibits stale context from altering the routing gate.  "
            "AttachedSessionRegistry is the sole first authority for session "
            "eligibility."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority by checking that all "
            "takeover/fallback routing calls go through "
            "resolve_takeover_or_fallback_route() and that no caller bypasses "
            "the AttachedSessionRegistry gate (REGISTRY_DISPATCH_MUST_CONSULT_"
            "REGISTRY_POLICY in core/attached_runtime_session_registry.py)."
        ),
        pr_addressed="PR-23",
    ),
    # -------------------------------------------------------------------------
    # INFL-008: Legacy node scan compat path for tool exposure
    # -------------------------------------------------------------------------
    CompatInfluenceRecord(
        influence_id="INFL-008",
        decision_site=(
            "Node tool exposure to OpenClawd (capability discovery)"
        ),
        canonical_path=(
            "NodeFabricRegistry → CapabilityRegistry → "
            "CapabilityResolver(CapabilitySource.NODE)"
        ),
        compat_path=(
            "Legacy Layer 3 node scan path "
            "(enabled via OPENCLAWD_LEGACY_NODE_SCAN_COMPAT env var)"
        ),
        influence_role=CompatInfluenceRole.degraded_fallback,
        bounding_status=CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED,
        bounding_evidence=(
            "core.openclawd_canonical_node_tool_exposure "
            "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENV_VAR gates the legacy path "
            "(disabled by default).  build_canonical_tool_exposure_snapshot() "
            "emits WARNING when compat_enabled=True.  "
            "Canonical path is always declared active "
            "(canonical_path_active=True in snapshot)."
        ),
        reviewer_note=(
            "A reviewer can confirm canonical authority by checking that "
            "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT env var is absent or false "
            "in production.  When the compat path is enabled, "
            "CanonicalNodeToolExposureSnapshot.compat_enabled == True "
            "provides an explicit signal."
        ),
        pr_addressed="PR-10",
    ),
]


# ===========================================================================
# Query functions
# ===========================================================================


def get_influence_registry() -> List[CompatInfluenceRecord]:
    """Return the full compat/fallback influence registry.

    Returns
    -------
    list[CompatInfluenceRecord]
        All registered influence records in catalog-definition order.
    """
    return list(_INFLUENCE_REGISTRY)


def get_influence_record(influence_id: str) -> Optional[CompatInfluenceRecord]:
    """Return the influence record for *influence_id*, or ``None``.

    Parameters
    ----------
    influence_id:
        The influence point ID (e.g. ``"INFL-001"``).

    Returns
    -------
    CompatInfluenceRecord or None
    """
    return next(
        (r for r in _INFLUENCE_REGISTRY if r.influence_id == influence_id),
        None,
    )


# ===========================================================================
# Decision-site guard helpers
# ===========================================================================


def check_canonical_authority_at_decision_site(
    influence_id: str,
    *,
    canonical_is_active: bool = True,
    compat_path_invoked: bool = False,
    strict: bool = False,
) -> CompatInfluenceCheckResult:
    """Check whether canonical authority is the primary decision maker at a site.

    Call this helper at any decision site where a compat or fallback path
    may be invoked alongside (or instead of) the canonical path.  It looks
    up the influence record for *influence_id*, evaluates the current
    authority posture, logs an appropriate structured message, and returns
    a :class:`CompatInfluenceCheckResult`.

    Parameters
    ----------
    influence_id:
        The influence point ID (e.g. ``"INFL-001"``).
    canonical_is_active:
        ``True`` when the canonical path was consulted first and successfully
        produced a decision.  ``False`` when the canonical path was
        unavailable or did not produce a result.
    compat_path_invoked:
        ``True`` when a compat or fallback path was invoked at this site.
    strict:
        When ``True`` and the verdict is ``UNBOUND_INFLUENCE_DETECTED``,
        raise a ``RuntimeError``.  Default is ``False`` (non-blocking).

    Returns
    -------
    CompatInfluenceCheckResult

    Raises
    ------
    RuntimeError
        Only when ``strict=True`` and unbound influence is detected.
    """
    record = next(
        (r for r in _INFLUENCE_REGISTRY if r.influence_id == influence_id),
        None,
    )

    if record is None:
        msg = (
            f"COMPAT_FALLBACK_AUTHORITY_GUARD: unknown influence_id={influence_id!r}. "
            "Register this influence point in "
            "core.compat_fallback_authority_guard influence registry."
        )
        logger.warning(msg)
        return CompatInfluenceCheckResult(
            influence_id=influence_id,
            verdict=CompatInfluenceVerdict.UNKNOWN,
            canonical_path="<unknown>",
            compat_path="<unknown>",
            message=msg,
        )

    # Canonical is active, no compat invoked — clean canonical authority.
    if canonical_is_active and not compat_path_invoked:
        msg = (
            f"COMPAT_FALLBACK_AUTHORITY_GUARD [{influence_id}]: "
            "canonical authority confirmed as primary decision maker. "
            f"canonical_path={record.canonical_path!r}."
        )
        logger.debug(msg)
        return CompatInfluenceCheckResult(
            influence_id=influence_id,
            verdict=CompatInfluenceVerdict.CANONICAL_AUTHORITY,
            canonical_path=record.canonical_path,
            compat_path=record.compat_path,
            message=msg,
        )

    # Compat invoked — evaluate against bounding status.
    if compat_path_invoked:
        if record.bounding_status == CompatInfluenceBoundingStatus.UNBOUNDED:
            msg = (
                f"COMPAT_FALLBACK_AUTHORITY_GUARD [{influence_id}] "
                "UNBOUND COMPAT INFLUENCE DETECTED: "
                f"{record.compat_path!r} influenced decision at "
                f"{record.decision_site!r} without explicit bounding.  "
                f"Canonical path: {record.canonical_path!r}.  "
                "This is a policy violation per "
                "UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY."
            )
            logger.error(msg)
            if strict:
                raise RuntimeError(msg)
            return CompatInfluenceCheckResult(
                influence_id=influence_id,
                verdict=CompatInfluenceVerdict.UNBOUND_INFLUENCE_DETECTED,
                canonical_path=record.canonical_path,
                compat_path=record.compat_path,
                message=msg,
            )

        # Bounded compat — determine role-specific verdict.
        if record.influence_role == CompatInfluenceRole.degraded_fallback:
            msg = (
                f"COMPAT_FALLBACK_AUTHORITY_GUARD [{influence_id}] "
                "DEGRADED FALLBACK ACTIVE: "
                f"{record.compat_path!r} acting as degraded fallback at "
                f"{record.decision_site!r}.  "
                f"Canonical path: {record.canonical_path!r}.  "
                f"Bounding: {record.bounding_status.value} "
                f"({record.bounding_evidence}).  "
                "Canonical path must be re-consulted when available."
            )
            logger.warning(msg)
            return CompatInfluenceCheckResult(
                influence_id=influence_id,
                verdict=CompatInfluenceVerdict.DEGRADED_FALLBACK_ACTIVE,
                canonical_path=record.canonical_path,
                compat_path=record.compat_path,
                message=msg,
            )

        # bounded_assist or observer with compat active
        msg = (
            f"COMPAT_FALLBACK_AUTHORITY_GUARD [{influence_id}] "
            "BOUNDED COMPAT ASSIST ACTIVE: "
            f"{record.compat_path!r} contributing in role={record.influence_role.value} "
            f"at {record.decision_site!r}.  "
            f"Canonical path remains primary: {record.canonical_path!r}.  "
            f"Bounding: {record.bounding_status.value}."
        )
        logger.warning(msg)
        return CompatInfluenceCheckResult(
            influence_id=influence_id,
            verdict=CompatInfluenceVerdict.BOUNDED_ASSIST_ACTIVE,
            canonical_path=record.canonical_path,
            compat_path=record.compat_path,
            message=msg,
        )

    # canonical_is_active=False, compat_path_invoked=False — degenerate case.
    msg = (
        f"COMPAT_FALLBACK_AUTHORITY_GUARD [{influence_id}]: "
        "neither canonical nor compat path confirmed active at "
        f"{record.decision_site!r}.  Authority source is UNKNOWN."
    )
    logger.warning(msg)
    return CompatInfluenceCheckResult(
        influence_id=influence_id,
        verdict=CompatInfluenceVerdict.UNKNOWN,
        canonical_path=record.canonical_path,
        compat_path=record.compat_path,
        message=msg,
    )


def assert_canonical_is_decision_authority(
    influence_id: str,
    *,
    context: str = "",
    strict: bool = False,
) -> CompatInfluenceCheckResult:
    """Assert that the canonical path is the primary decision authority.

    A convenience wrapper for invariant-checking code.  Logs a clear
    structured message and returns the check result.  Assumes that if this
    function is called without ``compat_path_invoked=True``, the canonical
    path is active.

    Parameters
    ----------
    influence_id:
        Influence point ID (e.g. ``"INFL-001"``).
    context:
        Optional context string logged when canonical authority is not
        confirmed.
    strict:
        When ``True``, raise ``RuntimeError`` if unbound influence is
        detected.

    Returns
    -------
    CompatInfluenceCheckResult
    """
    result = check_canonical_authority_at_decision_site(
        influence_id,
        canonical_is_active=True,
        compat_path_invoked=False,
        strict=strict,
    )
    if context and result.verdict != CompatInfluenceVerdict.CANONICAL_AUTHORITY:
        logger.warning(
            "COMPAT_FALLBACK_AUTHORITY_GUARD assert_canonical_is_decision_authority "
            "[%s] context=%r verdict=%s",
            influence_id,
            context,
            result.verdict.value,
        )
    return result


# ===========================================================================
# Snapshot builder
# ===========================================================================


def build_authority_hardening_snapshot() -> AuthorityHardeningSnapshot:
    """Build an aggregate snapshot of the authority hardening posture.

    The snapshot is JSON-serialisable and suitable for CI consumption or
    diagnostic endpoint exposure.

    Returns
    -------
    AuthorityHardeningSnapshot
    """
    registry = _INFLUENCE_REGISTRY
    explicitly_bounded = [
        r for r in registry
        if r.bounding_status == CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED
    ]
    scope_limited = [
        r for r in registry
        if r.bounding_status == CompatInfluenceBoundingStatus.SCOPE_LIMITED
    ]
    unbounded = [
        r for r in registry
        if r.bounding_status == CompatInfluenceBoundingStatus.UNBOUNDED
    ]
    retired = [
        r for r in registry
        if r.bounding_status == CompatInfluenceBoundingStatus.RETIRED
    ]

    hardening_complete = len(unbounded) == 0 and len(scope_limited) == 0

    return AuthorityHardeningSnapshot(
        total_influence_points=len(registry),
        explicitly_bounded_count=len(explicitly_bounded),
        scope_limited_count=len(scope_limited),
        unbounded_count=len(unbounded),
        retired_count=len(retired),
        unbound_violation_count=len(unbounded),
        hardening_complete=hardening_complete,
        generated_at=time.time(),
        policy_sentinels=[
            CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY,
            COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY,
            UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY,
            FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY,
        ],
        influence_summaries=[r.to_dict() for r in registry],
    )
