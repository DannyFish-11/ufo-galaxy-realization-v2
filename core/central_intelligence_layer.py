#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/central_intelligence_layer.py
=====================================
PR-7: Central Intelligence Layer — semantic boundary declaration and
pseudo-center naming-layer convergence.

Purpose
-------
This module is the **single authoritative declaration** of the central
intelligence layer semantics for the Galaxy/OpenClawd runtime.  It resolves
semantic drift where ``orchestrator`` / ``coordinator`` / ``spine`` /
``planner`` / ``kernel`` / ``team`` names have created false impressions of
parallel top-level controllers alongside the real canonical chain.

This module does **not** introduce new runtime logic.  It consolidates and
locks the existing architectural declarations so that:

1. The **central-intelligence main layer** (``OpenClawd`` + runtime shell) is
   unambiguous.
2. **Expert capability sub-layers** (``AgentKernel``, ``ExecutionPlanner``,
   ``TeamManager`` / ``AgentTeam``) are clearly identified as *sub-layers*
   operating under OpenClawd's authority — not parallel top-level controllers.
3. **Sub-domain coordinators** (``UnifiedOrchestrationSpine``,
   ``DeviceOrchestrator``, ``SwarmCoordinator``) are clearly scoped to their
   specific orchestration domains rather than posturing as universal
   central authorities.
4. **Facade / compat / helper layers** (``e2e_orchestrator``,
   ``RepoCoordinator``, ``SystemOrchestrator``) are confirmed non-authorities
   on the canonical per-request path.
5. **Android first-class runtime host** status is preserved — Android devices
   participate as primary runtime hosts via the canonical
   ``DeviceRouter`` → gateway dispatch path; they are not relegated to
   passive forwarders.

Naming drift that this PR addresses
-------------------------------------
Prior to this module the following naming confusion existed:

* ``AgentKernel`` — the word "kernel" implies low-level central authority.
  Reality: ``AgentKernel`` is OpenClawd's **embedded cognition/planning
  sub-layer**.  It cannot act independently; it exists only inside
  OpenClawd.process() and returns advisory ``KernelResponse`` artifacts.

* ``ExecutionPlanner`` — the word "planner" and its ``execute()`` entrypoint
  could be mistaken for a second top-level executor.  Reality:
  ``ExecutionPlanner`` is called **by AgentKernel** to assemble and dispatch
  execution plans.  It is a planning helper, not an authority.

* ``TeamManager`` / ``AgentTeam`` — multi-agent team coordination sounds
  like a second orchestration control plane.  Reality: ``TeamManager`` is
  created and called **by ExecutionPlanner** as one of three strategy paths
  (single-agent, team, fractal).  It is an expert execution sub-layer.

* ``SystemOrchestrator`` — the word "Orchestrator" implies runtime control.
  Reality: ``SystemOrchestrator`` owns the **staged startup contract** only.
  It governs bring-up phases; it is not on the per-request hot path.

* ``UnifiedOrchestrationSpine`` — the word "Unified … Spine" sounds
  universal.  Reality: V4 governs **multi-step orchestration sessions**
  (parallel fan-out, delegated runtime, wake-routed, handoff/takeover,
  cross-device, hybrid) only.  Per-request simple execution (``LOCAL``,
  ``SINGLE_DEVICE_REMOTE``) never passes through V4.

* ``e2e_orchestrator`` — the word "orchestrator" in the module name implies
  it owns orchestration authority.  Reality: it is a **convenience facade**
  that delegates entirely to ``DesktopPresenceRuntime`` → ``OpenClawd`` →
  ``CommandRouter``.

* ``RepoCoordinator`` — the word "coordinator" suggests active coordination
  authority.  Reality: it is a **legacy/management facade** that no longer
  owns device state; device state truth has migrated to
  ``UnifiedDeviceManager`` (UDM).

Canonical layer hierarchy (unchanged from prior PRs)
-----------------------------------------------------
::

    DesktopPresenceRuntime (runtime shell)           ← CENTRAL INTELLIGENCE: outer shell
        └─ OpenClawd (subject/execution core)        ← CENTRAL INTELLIGENCE: cognition core
              Stage 1: Ingest (PerceptionFrame, multimodal)
              Stage 2: Continuum / Liminal Cognition (ContinuumOrchestrator)
              Stage 3: Execution Branch (_determine_execution_path)
                ├─ local       → DecisionExecutor / WindowsExecutionArbiter
                ├─ cross_device → CommandRouter → DeviceRouter → gateway/Android
                ├─ hybrid      → both loops
                └─ none        → respond only
              Stage 4: Manifest
                └─ AgentKernel (embedded cognition sub-layer)
                      └─ ExecutionPlanner (planning helper)
                            ├─ single-agent path    → AgentFactory.create_agent()
                            ├─ team/swarm path      → TeamManager / AgentTeam
                            └─ fractal path         → FractalAgent

Role taxonomy
-------------
CENTRAL_INTELLIGENCE_MAIN_LAYER
    The canonical runtime cognition and execution authority.  Includes:
    - ``DesktopPresenceRuntime`` (outer runtime shell; owns lifecycle)
    - ``OpenClawd`` (inner cognition/execution core; owns execution branching)

EXPERT_CAPABILITY_SUB_LAYER
    Sub-layers that provide expert execution capabilities called from within
    OpenClawd.  They MUST NOT act as independent top-level controllers.
    - ``AgentKernel`` — embedded cognition/planning sub-layer under OpenClawd
    - ``ExecutionPlanner`` — execution planning helper called by AgentKernel
    - ``TeamManager`` / ``AgentTeam`` — multi-agent team coordination called
      by ExecutionPlanner

SUB_DOMAIN_COORDINATOR
    Scoped coordination surfaces that govern a specific execution domain.
    They are NOT universal per-request gates.
    - ``UnifiedOrchestrationSpine`` (V4) — multi-step orchestration sessions
    - ``DeviceOrchestrator`` — device-level orchestration (internal)
    - ``SwarmCoordinator`` — swarm execution coordination

FACADE_COMPAT_HELPER
    Convenience facades, legacy shims, or startup helpers that do NOT hold
    canonical runtime authority on the per-request hot path.
    - ``e2e_orchestrator`` — convenience facade over the canonical chain
    - ``RepoCoordinator`` — legacy/management facade (device state → UDM)
    - ``SystemOrchestrator`` — startup contract (bring-up phases only)

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CENTRAL_INTELLIGENCE_LAYER_AUTHORITY`
:data:`CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL`
:data:`OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY`
:data:`KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY`
:data:`PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY`
:data:`TEAM_IS_NOT_SECOND_AUTHORITY_POLICY`
:data:`ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY`
:data:`ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY`

Enums
~~~~~
:class:`CILayerRole`

Data classes
~~~~~~~~~~~~
:class:`CILayerSurface`
:class:`CILayerBoundaryReport`

Registry
~~~~~~~~
:data:`CI_LAYER_SURFACE_REGISTRY`

Functions
~~~~~~~~~
:func:`get_ci_layer_registry`
:func:`classify_ci_surface`
:func:`get_surfaces_by_ci_role`
:func:`build_ci_layer_boundary_report`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

__all__ = [
    # Sentinels
    "CENTRAL_INTELLIGENCE_LAYER_AUTHORITY",
    "CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL",
    "OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY",
    "KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY",
    "PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY",
    "TEAM_IS_NOT_SECOND_AUTHORITY_POLICY",
    "ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY",
    "ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY",
    # Enums
    "CILayerRole",
    # Data classes
    "CILayerSurface",
    "CILayerBoundaryReport",
    # Registry
    "CI_LAYER_SURFACE_REGISTRY",
    # Functions
    "get_ci_layer_registry",
    "classify_ci_surface",
    "get_surfaces_by_ci_role",
    "build_ci_layer_boundary_report",
]


# ---------------------------------------------------------------------------
# Module authority and policy sentinels
# ---------------------------------------------------------------------------

CENTRAL_INTELLIGENCE_LAYER_AUTHORITY: str = (
    "CENTRAL_INTELLIGENCE_LAYER_AUTHORITY::"
    "core.central_intelligence_layer is the canonical authority for declaring "
    "the central-intelligence semantic boundary in the Galaxy/OpenClawd runtime.  "
    "It classifies OpenClawd + DesktopPresenceRuntime as the central-intelligence "
    "main layer, AgentKernel / ExecutionPlanner / TeamManager as expert capability "
    "sub-layers, UnifiedOrchestrationSpine / DeviceOrchestrator / SwarmCoordinator "
    "as scoped sub-domain coordinators, and e2e_orchestrator / RepoCoordinator / "
    "SystemOrchestrator as facade/compat/helper layers."
)

CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL: str = (
    "CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL::"
    "PR7::central-intelligence-semantic-boundary-v1::"
    "core.central_intelligence_layer is the PR-7 central-intelligence semantic "
    "boundary module.  All surfaces that name themselves as orchestrator / "
    "coordinator / spine / kernel / planner / team are classified by their "
    "true architectural role.  Pseudo-center naming layers are explicitly marked "
    "as sub-layers, facades, or scoped coordinators so they cannot continue to "
    "create false impressions of a second total control center."
)

#: OpenClawd (plus its outer runtime shell, DesktopPresenceRuntime) is the
#: canonical central intelligence — the runtime cognition and execution core.
#: No other module may claim to be an equivalent or parallel central authority
#: for per-request cognitive processing.
OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY: str = (
    "OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY_V1: "
    "OpenClawd (core.openclawd.OpenClawd) is the single central intelligence "
    "core for per-request runtime cognition.  DesktopPresenceRuntime is the "
    "canonical outer runtime shell that drives OpenClawd's tri-state lifecycle.  "
    "Together they form the central-intelligence main layer.  No other module — "
    "including AgentKernel, ExecutionPlanner, TeamManager, SystemOrchestrator, "
    "UnifiedOrchestrationSpine, or e2e_orchestrator — may claim to be a peer "
    "or replacement central intelligence for the per-request hot path."
)

#: AgentKernel is OpenClawd's embedded cognition/planning sub-layer.  It MUST
#: NOT act as an independent top-level controller or claim authority over
#: execution decisions that belong to OpenClawd.
KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY: str = (
    "KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY_V1: "
    "AgentKernel (core.agent.kernel.AgentKernel) is OpenClawd's embedded "
    "cognition/planning sub-layer.  AgentKernel operates inside "
    "OpenClawd.process() and returns advisory KernelResponse artifacts.  "
    "AgentKernel MUST NOT be invoked as an independent top-level controller, "
    "MUST NOT claim dispatch authority, and MUST NOT bypass OpenClawd's "
    "execution-path branching.  KernelResponse.routing_authority is fixed at "
    "'advisory_to_openclawd' to express this constraint.  Any route or external "
    "caller that invokes AgentKernel directly (bypassing OpenClawd) violates "
    "this policy."
)

#: ExecutionPlanner is a planning helper called by AgentKernel.  It selects
#: execution strategies and invokes AgentFactory / TeamManager, but does NOT
#: hold independent dispatch authority.
PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY: str = (
    "PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY_V1: "
    "ExecutionPlanner (core.agent.execution_planner.ExecutionPlanner) is an "
    "execution planning helper called by AgentKernel._process() in the "
    "task_execute/hybrid path.  ExecutionPlanner selects execution strategy "
    "(single-agent / team / swarm / fractal) and dispatches via AgentFactory or "
    "TeamManager.  ExecutionPlanner MUST NOT be treated as a second top-level "
    "execution authority, MUST NOT receive direct per-request calls from route "
    "surfaces, and MUST NOT claim governance or dispatch authority independent "
    "of the AgentKernel → OpenClawd → CommandRouter chain."
)

#: TeamManager / AgentTeam is an expert execution sub-layer invoked by
#: ExecutionPlanner for multi-agent team strategies.  It is NOT a second
#: orchestration control plane.
TEAM_IS_NOT_SECOND_AUTHORITY_POLICY: str = (
    "TEAM_IS_NOT_SECOND_AUTHORITY_POLICY_V1: "
    "TeamManager (core.agent_team.TeamManager) and AgentTeam "
    "(core.agent_team.AgentTeam) are expert execution sub-layers that implement "
    "PARALLEL, SPECIALIZED, and SWARM multi-agent strategies.  They are "
    "instantiated and called by ExecutionPlanner._run_team() as one of three "
    "dispatch paths.  TeamManager/AgentTeam MUST NOT be treated as an "
    "independent orchestration control plane, MUST NOT hold persistent session "
    "authority, and MUST NOT claim governance or routing authority.  Calling "
    "TeamManager directly from a route or lifecycle surface (bypassing the "
    "AgentKernel → ExecutionPlanner call chain) violates this policy."
)

#: Orchestrators, coordinators, and spines are scoped to specific domains.
#: They must not claim to be universal per-request central authorities.
ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY: str = (
    "ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY_V1: "
    "Modules named 'orchestrator', 'coordinator', or 'spine' in the Galaxy "
    "runtime are scoped to specific domains and MUST NOT posture as universal "
    "central authorities: "
    "UnifiedOrchestrationSpine (V4) governs multi-step orchestration sessions "
    "(parallel fan-out, delegated runtime, wake-routed, handoff/takeover, "
    "cross-device, hybrid) — it is NOT a per-request synchronous gate; "
    "SystemOrchestrator governs staged startup bring-up phases only — it is "
    "NOT a per-request runtime controller; "
    "e2e_orchestrator is a convenience facade over the canonical chain — it "
    "MUST NOT hold independent dispatch authority; "
    "RepoCoordinator is a legacy/management facade — device state truth has "
    "migrated to UnifiedDeviceManager (UDM); "
    "DeviceOrchestrator and SwarmCoordinator are internal domain coordinators "
    "called from within the canonical chain, not parallel top-level authorities."
)

#: Android devices participate as first-class runtime hosts.  The
#: central-intelligence narrative must not degrade Android to a passive
#: forwarder or secondary device class.
ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY: str = (
    "ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY_V1: "
    "Android devices are first-class runtime hosts in the Galaxy system.  "
    "They participate in the canonical chain as execution targets via "
    "DeviceRouter → galaxy_gateway → Android runtime.  The central-intelligence "
    "layer (OpenClawd + DesktopPresenceRuntime) routes cross-device execution "
    "to Android via CommandRouter.route_envelope() → DeviceRouter, treating "
    "Android as a full execution domain — not a generic packet forwarder.  "
    "The central-intelligence semantic convergence (PR-7) must preserve "
    "Android's first-class status: Android-side readiness, governance posture, "
    "and capability assertions must be consumed as first-class inputs by the "
    "canonical dispatch and governance chain."
)


# ---------------------------------------------------------------------------
# CILayerRole enum
# ---------------------------------------------------------------------------


class CILayerRole(str, Enum):
    """The central-intelligence layer role of a surface in Galaxy/OpenClawd.

    central_intelligence_main_layer
        The canonical runtime cognition and execution authority.  Includes
        the outer runtime shell (DesktopPresenceRuntime) and the inner
        cognition/execution core (OpenClawd).  These are the ONLY surfaces
        that constitute the central intelligence for per-request processing.

    expert_capability_sub_layer
        Sub-layers providing expert execution capabilities, called from
        within the central-intelligence core.  They execute under OpenClawd's
        authority and MUST NOT claim independent top-level authority.
        Examples: AgentKernel, ExecutionPlanner, TeamManager/AgentTeam.

    sub_domain_coordinator
        Scoped coordination surfaces that govern a specific execution domain
        (not the universal per-request path).  Examples:
        UnifiedOrchestrationSpine (multi-step sessions only),
        DeviceOrchestrator (device-level), SwarmCoordinator (swarm execution).

    facade_compat_helper
        Convenience facades, legacy management shims, or startup helpers
        that delegate to the canonical chain and MUST NOT hold independent
        per-request dispatch authority.  Examples: e2e_orchestrator,
        RepoCoordinator, SystemOrchestrator (startup only).
    """

    central_intelligence_main_layer = "central_intelligence_main_layer"
    expert_capability_sub_layer = "expert_capability_sub_layer"
    sub_domain_coordinator = "sub_domain_coordinator"
    facade_compat_helper = "facade_compat_helper"


# ---------------------------------------------------------------------------
# CILayerSurface dataclass
# ---------------------------------------------------------------------------


@dataclass
class CILayerSurface:
    """Classification of a surface in the central-intelligence layer model.

    Attributes
    ----------
    surface_id:
        Short stable identifier for the surface (used for lookup).
    module_path:
        Canonical Python module path for the surface.
    surface_name:
        Human-readable surface name.
    ci_role:
        The CI layer role of this surface.
    is_central_intelligence:
        ``True`` only when ``ci_role`` is
        ``CILayerRole.central_intelligence_main_layer``.  All other
        surfaces are ``False``.
    may_not_claim_independent_authority:
        ``True`` for surfaces that have naming patterns (orchestrator /
        coordinator / spine / kernel / planner / team) that could create
        false impressions of central authority.  These surfaces carry an
        explicit "NOT a second authority" constraint.
    notes:
        Governance notes explaining the surface's true role and any
        naming-drift risk that this classification resolves.
    """

    surface_id: str
    module_path: str
    surface_name: str
    ci_role: CILayerRole
    is_central_intelligence: bool
    may_not_claim_independent_authority: bool
    notes: str

    def to_dict(self) -> Dict:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "ci_role": self.ci_role.value,
            "is_central_intelligence": self.is_central_intelligence,
            "may_not_claim_independent_authority": self.may_not_claim_independent_authority,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# CILayerBoundaryReport dataclass
# ---------------------------------------------------------------------------


@dataclass
class CILayerBoundaryReport:
    """Compact summary of the central-intelligence layer boundary model.

    Attributes
    ----------
    total_surfaces:
        Total number of classified surfaces.
    central_intelligence_count:
        Number of surfaces classified as central_intelligence_main_layer.
    expert_sub_layer_count:
        Number of surfaces classified as expert_capability_sub_layer.
    sub_domain_coordinator_count:
        Number of surfaces classified as sub_domain_coordinator.
    facade_compat_helper_count:
        Number of surfaces classified as facade_compat_helper.
    constrained_surfaces:
        Surface IDs that carry the
        ``may_not_claim_independent_authority`` constraint.
    generated_at:
        Unix timestamp when this report was generated.
    """

    total_surfaces: int
    central_intelligence_count: int
    expert_sub_layer_count: int
    sub_domain_coordinator_count: int
    facade_compat_helper_count: int
    constrained_surfaces: List[str]
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "total_surfaces": self.total_surfaces,
            "central_intelligence_count": self.central_intelligence_count,
            "expert_sub_layer_count": self.expert_sub_layer_count,
            "sub_domain_coordinator_count": self.sub_domain_coordinator_count,
            "facade_compat_helper_count": self.facade_compat_helper_count,
            "constrained_surfaces": self.constrained_surfaces,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# CI layer surface registry
# ---------------------------------------------------------------------------

CI_LAYER_SURFACE_REGISTRY: List[CILayerSurface] = [
    # =========================================================================
    # Central intelligence main layer
    # =========================================================================

    CILayerSurface(
        surface_id="desktop_presence_runtime",
        module_path="core.desktop_presence_runtime.DesktopPresenceRuntime",
        surface_name="DesktopPresenceRuntime (runtime shell)",
        ci_role=CILayerRole.central_intelligence_main_layer,
        is_central_intelligence=True,
        may_not_claim_independent_authority=False,
        notes=(
            "Outer runtime shell.  Owns the canonical tri-state lifecycle "
            "(silent / liminal / manifest), native multimodal ingress, and the "
            "runtime_session_id.  Invokes OpenClawd.process() during the LIMINAL "
            "phase.  First-class node in the central-intelligence main layer."
        ),
    ),
    CILayerSurface(
        surface_id="openclawd",
        module_path="core.openclawd.OpenClawd",
        surface_name="OpenClawd (cognition/execution core)",
        ci_role=CILayerRole.central_intelligence_main_layer,
        is_central_intelligence=True,
        may_not_claim_independent_authority=False,
        notes=(
            "Inner cognition and execution core.  Owns intent resolution, "
            "execution-path branching (local / cross_device / hybrid / none), "
            "and the liminal lifecycle.  Delegates device-bound command dispatch "
            "to CommandRouter.route_envelope().  "
            "Subject core of the unified-subject architecture."
        ),
    ),

    # =========================================================================
    # Expert capability sub-layers
    # =========================================================================

    CILayerSurface(
        surface_id="agent_kernel",
        module_path="core.agent.kernel.AgentKernel",
        surface_name="AgentKernel (embedded cognition sub-layer)",
        ci_role=CILayerRole.expert_capability_sub_layer,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "OpenClawd's embedded cognition/planning sub-layer.  Called by "
            "OpenClawd.process() inside the LIMINAL phase.  Performs intent "
            "routing (IntentRouter), policy injection (SOUL / AGENTS / USER), "
            "and delegates execution to ExecutionPlanner.  Returns advisory "
            "KernelResponse artifacts to OpenClawd — it does NOT hold "
            "independent dispatch authority.  KernelResponse.routing_authority "
            "is fixed at 'advisory_to_openclawd'.  "
            "Naming risk: 'kernel' implies low-level central authority; this "
            "classification makes explicit that AgentKernel is a sub-layer, "
            "not a second top-level controller."
        ),
    ),
    CILayerSurface(
        surface_id="execution_planner",
        module_path="core.agent.execution_planner.ExecutionPlanner",
        surface_name="ExecutionPlanner (execution planning helper)",
        ci_role=CILayerRole.expert_capability_sub_layer,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Execution planning helper called by AgentKernel._process() in the "
            "task_execute/hybrid path.  Selects execution strategy (single-agent, "
            "team/swarm, fractal) and assembles the ExecutionPlan.  Calls "
            "AgentFactory for single-agent execution or TeamManager for team "
            "strategies.  Does NOT hold independent dispatch, governance, or "
            "orchestration authority.  "
            "Naming risk: 'planner' with an execute() entry-point could be "
            "mistaken for a second top-level executor; this classification "
            "makes explicit that it is a planning helper in the sub-layer."
        ),
    ),
    CILayerSurface(
        surface_id="team_manager",
        module_path="core.agent_team.TeamManager",
        surface_name="TeamManager (multi-agent team coordinator sub-layer)",
        ci_role=CILayerRole.expert_capability_sub_layer,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Multi-agent team coordination sub-layer called by "
            "ExecutionPlanner._run_team() for PARALLEL, SPECIALIZED, and SWARM "
            "strategies.  Creates and executes AgentTeam instances.  Does NOT "
            "hold independent orchestration, dispatch, or governance authority.  "
            "Naming risk: 'TeamManager' in a multi-agent context could evoke a "
            "second coordination control plane; this classification confirms it "
            "is an expert execution sub-layer only."
        ),
    ),
    CILayerSurface(
        surface_id="agent_team",
        module_path="core.agent_team.AgentTeam",
        surface_name="AgentTeam (multi-agent team instance)",
        ci_role=CILayerRole.expert_capability_sub_layer,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "A single multi-agent team instance created by TeamManager.  "
            "Executes a task using PARALLEL, SPECIALIZED, or SWARM strategy "
            "across multiple TaskAgent members.  Lifecycle is ephemeral — "
            "created per-task by TeamManager, not a persistent session authority.  "
            "Does NOT hold independent governance or dispatch authority."
        ),
    ),

    # =========================================================================
    # Sub-domain coordinators
    # =========================================================================

    CILayerSurface(
        surface_id="unified_orchestration_spine",
        module_path="core.unified_orchestration_spine",
        surface_name="UnifiedOrchestrationSpine (V4, multi-step session governor)",
        ci_role=CILayerRole.sub_domain_coordinator,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "V4 multi-step orchestration session governor.  Governs complex "
            "execution sessions: parallel fan-out, delegated runtime, wake-routed, "
            "handoff/takeover, cross-device, hybrid.  "
            "V4 is NOT the universal synchronous per-request gate — simple "
            "per-request execution (LOCAL, SINGLE_DEVICE_REMOTE) continues on "
            "the per-request hot path (OpenClawd → CommandRouter).  "
            "Naming risk: 'Unified … Spine' sounds universal; this classification "
            "locks its scope to multi-step orchestration sessions only."
        ),
    ),
    CILayerSurface(
        surface_id="device_orchestrator",
        module_path="core.device_orchestrator",
        surface_name="DeviceOrchestrator (device-level internal coordinator)",
        ci_role=CILayerRole.sub_domain_coordinator,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Internal device-level orchestration surface.  Coordinates "
            "device-scoped execution concerns within the canonical chain.  "
            "It is NOT a parallel top-level orchestration authority."
        ),
    ),
    CILayerSurface(
        surface_id="swarm_coordinator",
        module_path="core.swarm_coordinator",
        surface_name="SwarmCoordinator (swarm execution coordinator)",
        ci_role=CILayerRole.sub_domain_coordinator,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Swarm execution coordination surface.  Manages swarm-strategy "
            "multi-agent task lifecycle within the expert sub-layer.  It is NOT "
            "an independent orchestration authority alongside OpenClawd."
        ),
    ),

    # =========================================================================
    # Facade / compat / helper layers
    # =========================================================================

    CILayerSurface(
        surface_id="e2e_orchestrator",
        module_path="core.e2e_orchestrator",
        surface_name="e2e_orchestrator (convenience facade)",
        ci_role=CILayerRole.facade_compat_helper,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Convenience facade over the canonical execution chain.  "
            "Provides process_user_input() as a delegating entry point that "
            "routes entirely through DesktopPresenceRuntime → OpenClawd → "
            "CommandRouter.  Does NOT hold independent dispatch authority.  "
            "E2E_ORCHESTRATOR_ROLE sentinel: 'convenience_facade'.  "
            "Naming risk: 'orchestrator' in the module name implies independent "
            "authority; this classification confirms it is a facade only."
        ),
    ),
    CILayerSurface(
        surface_id="repo_coordinator",
        module_path="core.repo_coordinator.RepoCoordinator",
        surface_name="RepoCoordinator (legacy/management facade)",
        ci_role=CILayerRole.facade_compat_helper,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Legacy/management facade.  No longer owns device state — canonical "
            "device-state truth has migrated to UnifiedDeviceManager (UDM).  "
            "self.android_devices is a legacy compat cache (read-only for "
            "legacy callers); all writes must go through UDM.  "
            "Naming risk: 'coordinator' implies active coordination authority; "
            "this classification confirms it is a legacy facade only."
        ),
    ),
    CILayerSurface(
        surface_id="system_orchestrator",
        module_path="core.system_orchestrator",
        surface_name="SystemOrchestrator (staged startup contract)",
        ci_role=CILayerRole.facade_compat_helper,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes=(
            "Staged bring-up contract for Galaxy-Nexus.  Governs startup phases "
            "(LOAD_CONFIG → RESOLVE_MODE → ENV_CHECKS → BACKGROUND_SUBSYSTEMS → "
            "RUNTIME_SUBJECT → DESKTOP_SURFACE → READINESS_SUMMARY).  "
            "SystemOrchestrator is NOT on the per-request hot path — it is "
            "invoked only at process startup by main.py.  "
            "Naming risk: 'Orchestrator' implies runtime control; this "
            "classification confirms it is a startup-phase helper only."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------


def get_ci_layer_registry() -> List[CILayerSurface]:
    """Return all surfaces in the central-intelligence layer registry."""
    return list(CI_LAYER_SURFACE_REGISTRY)


def classify_ci_surface(surface_id: str) -> Optional[CILayerSurface]:
    """Return the :class:`CILayerSurface` for *surface_id*, or ``None``."""
    for surface in CI_LAYER_SURFACE_REGISTRY:
        if surface.surface_id == surface_id:
            return surface
    return None


def get_surfaces_by_ci_role(role: CILayerRole) -> List[CILayerSurface]:
    """Return all surfaces classified with *role*."""
    return [s for s in CI_LAYER_SURFACE_REGISTRY if s.ci_role == role]


def build_ci_layer_boundary_report() -> CILayerBoundaryReport:
    """Build and return a :class:`CILayerBoundaryReport` from the current registry."""
    total = len(CI_LAYER_SURFACE_REGISTRY)
    ci_count = sum(
        1 for s in CI_LAYER_SURFACE_REGISTRY
        if s.ci_role == CILayerRole.central_intelligence_main_layer
    )
    expert_count = sum(
        1 for s in CI_LAYER_SURFACE_REGISTRY
        if s.ci_role == CILayerRole.expert_capability_sub_layer
    )
    coordinator_count = sum(
        1 for s in CI_LAYER_SURFACE_REGISTRY
        if s.ci_role == CILayerRole.sub_domain_coordinator
    )
    facade_count = sum(
        1 for s in CI_LAYER_SURFACE_REGISTRY
        if s.ci_role == CILayerRole.facade_compat_helper
    )
    constrained = [
        s.surface_id
        for s in CI_LAYER_SURFACE_REGISTRY
        if s.may_not_claim_independent_authority
    ]
    return CILayerBoundaryReport(
        total_surfaces=total,
        central_intelligence_count=ci_count,
        expert_sub_layer_count=expert_count,
        sub_domain_coordinator_count=coordinator_count,
        facade_compat_helper_count=facade_count,
        constrained_surfaces=constrained,
        generated_at=time.time(),
    )
