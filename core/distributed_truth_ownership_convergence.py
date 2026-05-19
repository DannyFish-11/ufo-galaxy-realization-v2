#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/distributed_truth_ownership_convergence.py
=================================================
PR-9V2: Distributed Truth / Ownership Semantic Convergence.

Purpose
-------
This module is the **single authoritative boundary declaration** for the
ownership semantics and truth-domain authority of the distributed runtime
in the Galaxy/OpenClawd system.

It builds directly on:

* PR-7 ``core.truth_projection_boundary`` — canonical truth owner vs
  projection/read-model classification.
* PR-8 ``core.distributed_runtime_boundary`` — distributed runtime main
  chain and transport/prototype/projection taxonomy.
* PR-9 ``core.runtime_truth_output_chain`` — Stage 1 → Stage 2 → Stage 3
  truth output chain.
* PR-5V2 ``core.flow_level_truth_ownership`` — flow-level V2-canonical vs
  Android-execution ownership model.
* ``core.v2_android_truth_ssot`` — single V2-side build path for Android
  device truth.

Problem addressed
-----------------
After PRs #6–#8, the distributed runtime main chain is clearly declared and
projection surfaces are separated from authority surfaces.  However the
system still lacks a **single declaration** that answers:

1. Which truth domains are *authority truth*?
   (Who is running / who has authority / who decides terminal state.)
2. Which truth domains are *acceptance / closure / readiness truth*?
   (Evidence that a lifecycle gate has been met, but not an orchestration
   decision.)
3. Which truth domains are *outward projection / operator-visible truth*?
   (Read-only surfaces: operator snapshot, desktop status board, diagnostics
   dashboard — they consume authority truth but must not redefine it.)
4. Which truth domains are *diagnostics snapshot / audit artifact*?
   (Forensic records; they record decisions but do not make them.)

Without this explicit four-domain classification the following risks remain:

* Projection surfaces silently consume authority truth *and* then re-inject
  aggregated snapshots into upstream state — blurring the unidirectional
  Stage 1 → 2 → 3 chain established by PR-9.
* Ownership / session / handoff truth modules use vocabulary that implies
  completed distributed control-plane authority (``coordinator``, ``authority``,
  ``convergence``) without a single boundary document that clarifies what
  is an authority decision vs what is a prototype or evidence record.
* Android uplink signals (execution result, device posture, session
  continuation, takeover response) are described as entering ``generic
  forward`` or ``UI-only`` paths rather than as first-class entries into
  the V2 canonical truth output chain.

This module resolves that ambiguity by:

1. Declaring four *truth domain kinds* with explicit ownership semantics.
2. Classifying every surface that touches ownership, session, device, or
   handoff truth into one of those four domains.
3. Providing policy sentinels that prevent projection from claiming
   authority truth.
4. Declaring the canonical Android uplink entry into the V2 truth chain.
5. Providing a snapshot builder for operator / CI visibility.

This module does NOT introduce new runtime logic, new storage, or a new
distributed control plane.  It consolidates existing architectural
declarations so that the ownership / authority narrative is unambiguous.

Four truth domain kinds
-----------------------
AUTHORITY_TRUTH
    Runtime / device / session / ownership decisions that determine *who is
    running*, *who has authority*, *who may proceed*.  These are set by
    runtime lifecycle modules (DesktopPresenceRuntime, OpenClawd,
    CommandRouter, DeviceRouter, CanonicalSessionTruth,
    FlowLevelTruthOwnership).  They are the source of truth.

ACCEPTANCE_CLOSURE_READINESS_TRUTH
    Evidence that a lifecycle gate, session continuation requirement, or
    task closure criterion has been met.  These are produced by modules
    such as AttachedRuntimeSession, TakeoverTracking, DurableTruthAuthorityChain,
    and the acceptance/closure chain.  They inform authority decisions but
    do not substitute for them.

OUTWARD_PROJECTION_OPERATOR_TRUTH
    Read-only views of authority truth assembled for operator dashboards,
    desktop status board, operator console, and projected runtime snapshots.
    These surfaces MUST consume from compile_outward_truth() (Stage 2 of
    the runtime truth output chain) and MUST NOT redefine or reverse-inject
    into authority truth.

DIAGNOSTICS_AUDIT_ARTIFACT
    Forensic records, gate scaffolds, and audit stores that record decisions,
    events, and evidence for post-hoc analysis.  These surfaces are written
    by authority modules but are never read back as truth inputs.  Reading
    diagnostics snapshots is for operator / CI inspection only.

Android ↔ V2 canonical truth uplink
-------------------------------------
Android-originated runtime signals enter the V2 canonical truth output chain
via the following declared path::

    Android runtime signals
        └─ galaxy_gateway.android.handlers.*         (ingress gateway)
              └─ core.android_participant_truth_ingress   (truth ingress)
                    └─ core.v2_android_truth_ssot         (SSOT block build)
                          └─ core.canonical_session_truth  (merge + record)
                                └─ Stage 1: compile_runtime_truth()
                                      └─ Stage 2: compile_outward_truth()
                                            └─ Stage 3: projection surfaces

Any Android uplink path that terminates *before* reaching
``core.v2_android_truth_ssot.build_v2_android_truth_block()`` is a
``generic_forward`` or ``UI-only`` path and MUST NOT be described as
entering the V2 canonical truth output chain.

Policy invariants
-----------------
1. Projection / operator-visible / summary truth MUST NOT redefine authority
   truth.  They read from Stage 2 (outward truth assembler); they do not
   write back to Stage 1 (runtime truth compiler) or to any authority truth
   module.

2. Android uplink signals enter the V2 canonical truth output chain via
   ``core.v2_android_truth_ssot.build_v2_android_truth_block()`` and then
   into ``core.canonical_session_truth``.  Any other path is supplementary.

3. Ownership / session / handoff prototype modules (TakeoverTracking,
   CanonicalHandoffPath) represent evidence surfaces, not completed
   distributed ownership-transfer control planes.  Their truth kind is
   ACCEPTANCE_CLOSURE_READINESS_TRUTH, not AUTHORITY_TRUTH.

4. No new parallel distributed truth fabric or ownership service is created
   by this PR.  This module consolidates and declares existing boundaries.

5. Diagnostics / audit surfaces (audit stores, gate scaffolds, trace rings)
   produce DIAGNOSTICS_AUDIT_ARTIFACT truth only.  They MUST NOT be read
   back as inputs to authority or acceptance truth decisions.

Public API
----------
Authority sentinels::

    DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY
    DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL

Policy sentinels::

    PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY
    ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY
    OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY
    NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY
    DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY

Enums::

    OwnershipTruthDomainKind

Data classes::

    OwnershipTruthSurface
    OwnershipTruthConvergenceSnapshot

Functions::

    get_ownership_truth_registry()
    classify_ownership_truth_domain(surface_id)
    get_surfaces_by_truth_domain(domain)
    build_ownership_truth_convergence_snapshot()
    get_android_uplink_canonical_chain_path()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

__all__ = [
    # Authority sentinels
    "DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY",
    "DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL",
    # Policy sentinels
    "PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY",
    "ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY",
    "OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY",
    "NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY",
    "DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY",
    # Enums
    "OwnershipTruthDomainKind",
    # Data classes
    "OwnershipTruthSurface",
    "OwnershipTruthConvergenceSnapshot",
    # Functions
    "get_ownership_truth_registry",
    "classify_ownership_truth_domain",
    "get_surfaces_by_truth_domain",
    "build_ownership_truth_convergence_snapshot",
    "get_android_uplink_canonical_chain_path",
]


# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY: str = (
    "DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY_V1: "
    "core.distributed_truth_ownership_convergence is the single authoritative "
    "boundary declaration for distributed truth domain kinds and ownership "
    "semantics.  It classifies every authority/acceptance/projection/diagnostics "
    "surface and locks the four-domain truth boundary for PR-9V2 and subsequent "
    "distributed runtime and handoff PRs."
)
"""Module-level authority sentinel for the distributed truth ownership
convergence boundary (PR-9V2)."""

DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL: str = (
    "distributed_truth_ownership_convergence_pr9v2_boundary_locked"
)
"""PR-9V2 sentinel value.  Tests and CI gates locking the PR-9V2 boundary
declaration must assert the presence of this sentinel."""


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY: str = (
    "PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY_V1: "
    "outward_projection_operator_truth surfaces read from compile_outward_truth() "
    "(Stage 2 of the runtime truth output chain) and MUST NOT write back to or "
    "redefine authority_truth surfaces; operator dashboards, desktop status board, "
    "and projected runtime snapshots are read-only consumers of Stage 2 output; "
    "they do not produce canonical runtime truth and must not reverse-inject "
    "aggregated snapshot fields into Stage 1 (compile_runtime_truth) or any "
    "authority truth module such as CanonicalSessionTruth or DeviceRouter"
)
"""Policy: projection/operator-visible surfaces are Stage 3 consumers only.
They must not redefine or reverse-inject authority truth."""

ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY: str = (
    "ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY_V1: "
    "Android-originated runtime signals (execution result, device posture, "
    "session continuation, takeover response) MUST enter the V2 canonical truth "
    "output chain via core.v2_android_truth_ssot.build_v2_android_truth_block() "
    "and then into core.canonical_session_truth; any Android uplink path that "
    "terminates before build_v2_android_truth_block() is a generic_forward or "
    "UI-only path and MUST NOT be described as entering the V2 canonical truth "
    "output chain; the canonical Android uplink chain is: "
    "galaxy_gateway.android.handlers → core.android_participant_truth_ingress "
    "→ core.v2_android_truth_ssot → core.canonical_session_truth "
    "→ Stage 1 compile_runtime_truth → Stage 2 compile_outward_truth"
)
"""Policy: Android uplink signals enter V2 canonical truth via the SSOT path."""

OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY: str = (
    "OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY_V1: "
    "ownership / session / handoff prototype modules — TakeoverTracking, "
    "CanonicalHandoffPath, AndroidHandoffV2ResponseIngress, "
    "AndroidDelegatedRuntimeLifecycleCoordinator — produce "
    "acceptance_closure_readiness_truth evidence; they record accept/reject "
    "decisions and sequence lifecycle events but do NOT constitute a completed "
    "distributed ownership-transfer control plane; their truth kind is "
    "ACCEPTANCE_CLOSURE_READINESS_TRUTH not AUTHORITY_TRUTH; authority truth "
    "for session and ownership remains with CanonicalSessionTruth, "
    "AttachedRuntimeSession, and FlowLevelTruthOwnership"
)
"""Policy: ownership/handoff prototypes produce evidence, not authority truth."""

NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY: str = (
    "NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY_V1: "
    "this PR consolidates and declares existing ownership boundaries; "
    "it does NOT introduce a new distributed truth fabric, a new ownership "
    "service, or a new canonical truth store; all authority truth surfaces "
    "referenced here are pre-existing modules; extensions to truth authority "
    "must integrate into the existing chain (v2_android_truth_ssot → "
    "canonical_session_truth → runtime_truth_output_chain), not alongside it"
)
"""Policy: no new parallel distributed truth fabric or ownership service."""

DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY: str = (
    "DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY_V1: "
    "diagnostics_audit_artifact surfaces — audit stores, gate scaffolds, "
    "trace ring-buffers, event replay logs — record decisions and evidence "
    "for post-hoc analysis and operator inspection; they MUST NOT be read "
    "back as inputs to authority_truth or acceptance_closure_readiness_truth "
    "decisions; reading a diagnostics snapshot is for operator / CI use only; "
    "canonical authority decisions are produced by authority_truth modules "
    "directly, not by re-reading their audit artefacts"
)
"""Policy: diagnostics/audit surfaces are not re-read as truth inputs."""


# ---------------------------------------------------------------------------
# Truth domain kind taxonomy
# ---------------------------------------------------------------------------


class OwnershipTruthDomainKind(str, Enum):
    """Four-domain taxonomy for distributed truth ownership semantics.

    Every surface that touches runtime, device, session, ownership, handoff,
    projection, or diagnostics truth is classified into exactly one of these
    four domains.
    """

    authority_truth = "authority_truth"
    """Runtime / device / session / ownership decisions that determine who is
    running, who has authority, and who may proceed.  These are the sources
    of canonical truth.  Examples: CanonicalSessionTruth, DeviceRouter,
    CommandRouter, FlowLevelTruthOwnership, AttachedRuntimeSession."""

    acceptance_closure_readiness_truth = "acceptance_closure_readiness_truth"
    """Evidence that a lifecycle gate or task closure criterion has been met.
    These modules produce evidence records that inform authority decisions but
    do not substitute for them.  Examples: TakeoverTracking,
    CanonicalHandoffPath, DurableTruthAuthorityChain, attached_runtime_reuse,
    pr3_session_continuity_authority."""

    outward_projection_operator_truth = "outward_projection_operator_truth"
    """Read-only views of authority truth assembled for operator dashboards,
    desktop status boards, and projection endpoints.  Must consume from
    Stage 2 (compile_outward_truth) only.  Must not redefine authority truth.
    Examples: core.routes.projection, outward_runtime_truth,
    desktop_status_board, operator_snapshot."""

    diagnostics_audit_artifact = "diagnostics_audit_artifact"
    """Forensic records, gate scaffolds, trace rings, and audit stores that
    record decisions and events for post-hoc analysis.  They MUST NOT be
    read back as inputs to authority or acceptance truth decisions.  Examples:
    android_delegated_runtime_audit, distributed_release_gate_skeleton,
    replay_audit_persistence, architecture_diagnostics."""


# ---------------------------------------------------------------------------
# Surface data class
# ---------------------------------------------------------------------------


@dataclass
class OwnershipTruthSurface:
    """Single surface entry in the ownership truth convergence registry.

    Parameters
    ----------
    surface_id:
        Short stable identifier (e.g. ``"canonical_session_truth_authority"``).
    module_path:
        Fully-qualified Python module path.
    surface_name:
        Human-readable surface name with brief role summary.
    truth_domain:
        :class:`OwnershipTruthDomainKind` classification.
    may_not_redefine_authority_truth:
        ``True`` for all non-authority-truth surfaces — they MUST NOT claim
        or redefine canonical runtime/ownership/session authority.
    android_uplink_canonical_entry:
        ``True`` if this surface is the declared canonical Android uplink
        entry point into the V2 canonical truth output chain.
    notes:
        Human-readable explanation of the surface's actual role, governance
        constraints, and any naming risks.
    """

    surface_id: str
    module_path: str
    surface_name: str
    truth_domain: OwnershipTruthDomainKind
    may_not_redefine_authority_truth: bool = True
    android_uplink_canonical_entry: bool = False
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "truth_domain": self.truth_domain.value,
            "may_not_redefine_authority_truth": (
                self.may_not_redefine_authority_truth
            ),
            "android_uplink_canonical_entry": self.android_uplink_canonical_entry,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Convergence snapshot data class
# ---------------------------------------------------------------------------


@dataclass
class OwnershipTruthConvergenceSnapshot:
    """Aggregate convergence snapshot produced by
    :func:`build_ownership_truth_convergence_snapshot`.
    """

    authority: str = ""
    sentinel: str = ""
    policies: Tuple[str, ...] = field(default_factory=tuple)
    total_surfaces: int = 0
    authority_truth_count: int = 0
    acceptance_closure_count: int = 0
    outward_projection_count: int = 0
    diagnostics_audit_count: int = 0
    android_uplink_canonical_entries: List[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "authority": self.authority,
            "sentinel": self.sentinel,
            "policies": list(self.policies),
            "total_surfaces": self.total_surfaces,
            "authority_truth_count": self.authority_truth_count,
            "acceptance_closure_count": self.acceptance_closure_count,
            "outward_projection_count": self.outward_projection_count,
            "diagnostics_audit_count": self.diagnostics_audit_count,
            "android_uplink_canonical_entries": (
                self.android_uplink_canonical_entries
            ),
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Ownership truth surface registry
# ---------------------------------------------------------------------------

#: All surfaces classified within the distributed truth ownership boundary.
OWNERSHIP_TRUTH_SURFACE_REGISTRY: List[OwnershipTruthSurface] = [

    # =========================================================================
    # AUTHORITY_TRUTH — runtime / device / session / ownership authority
    # =========================================================================

    OwnershipTruthSurface(
        surface_id="canonical_session_truth_authority",
        module_path="core.canonical_session_truth.CanonicalSessionTruthRuntime",
        surface_name=(
            "CanonicalSessionTruthRuntime "
            "(canonical session truth authority — PR-4)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=False,
        notes=(
            "Canonical authority for runtime session truth and result merge "
            "across local, remote/takeover, and multi-device execution paths.  "
            "Session truth is written here by record_session_truth(); "
            "merge_session_truth() reconciles Android result uplinks with "
            "the V2 canonical session record.  "
            "Authority sentinel: CANONICAL_SESSION_TRUTH_AUTHORITY (PR-4)."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="attached_runtime_session_authority",
        module_path="core.attached_runtime_session.AttachedRuntimeSession",
        surface_name=(
            "AttachedRuntimeSession "
            "(canonical session lifecycle authority — PR-4/8)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=False,
        notes=(
            "Owns session lifecycle state transitions: attach/detach/reconnect.  "
            "Stale session context MUST NOT assert canonical session state "
            "or alter session truth independently of AttachedRuntimeSession.  "
            "Authority boundary established by PR-4 and hardened by PR-8 INV-003."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="flow_level_truth_ownership_authority",
        module_path="core.flow_level_truth_ownership.FlowTruthOwnerKind",
        surface_name=(
            "FlowLevelTruthOwnership "
            "(flow-level V2-canonical vs Android-execution authority — PR-5V2)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=False,
        notes=(
            "Declares which Android truth is authoritative upward "
            "(must update V2 canonical), advisory (noted but does not alter "
            "canonical state), or execution evidence (recorded for audit only).  "
            "V2 holds canonical authority for terminal state decisions; "
            "Android holds canonical authority for local execution facts "
            "during active execution.  "
            "FlowTruthOwnerKind: v2_canonical / android_execution / joint."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="device_router_dispatch_authority",
        module_path="galaxy_gateway.device_router.DeviceRouter",
        surface_name=(
            "DeviceRouter "
            "(device dispatch authority, transport session manager — PR-8)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=False,
        notes=(
            "Canonical device dispatch authority.  Owns WebSocket/transport "
            "session handles and all device-level routing.  "
            "Device participation authority at the transport level.  "
            "One of the five nodes in the distributed runtime main chain."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="command_router_orchestration_authority",
        module_path="core.command_router.CommandRouter",
        surface_name=(
            "CommandRouter "
            "(cross-device orchestration authority, ACL / HITL gate — PR-8)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=False,
        notes=(
            "Cross-device execution loop entry.  Owns ACL enforcement, HITL "
            "gate, lifecycle state transitions, retry / circuit-breaker, and "
            "TaskEnvelope plumbing.  Orchestration authority on the V2 side.  "
            "One of the five nodes in the distributed runtime main chain."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="v2_android_truth_ssot_canonical_build",
        module_path=(
            "core.v2_android_truth_ssot.build_v2_android_truth_block"
        ),
        surface_name=(
            "V2AndroidTruthSSOT.build_v2_android_truth_block "
            "(canonical Android truth block builder — V2 SSOT)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=True,
        notes=(
            "The canonical V2-side Android truth block builder.  "
            "build_v2_android_truth_block(device_id) is the single V2-side "
            "build path for Android device truth (participation tier, device "
            "mode, readiness, posture).  "
            "Android uplink signals enter the V2 canonical truth output chain "
            "here — this is the declared Android uplink canonical entry point.  "
            "All routing / readiness / closure / panel / board consumers MUST "
            "use this function rather than independently re-assembling Android "
            "truth from sub-modules."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="android_participant_truth_ingress_authority",
        module_path="core.android_participant_truth_ingress",
        surface_name=(
            "android_participant_truth_ingress "
            "(Android truth ingress gateway — V2 authority surface)"
        ),
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=True,
        notes=(
            "Canonical V2-side ingress for Android-originated truth signals: "
            "execution results, task phase signals, failure/cancel signals, "
            "and participant posture updates.  "
            "Feeds into build_v2_android_truth_block (SSOT) and then "
            "canonical_session_truth (merge + record).  "
            "This is the second node of the Android uplink canonical chain: "
            "galaxy_gateway.android.handlers → android_participant_truth_ingress "
            "→ v2_android_truth_ssot → canonical_session_truth."
        ),
    ),

    # =========================================================================
    # ACCEPTANCE_CLOSURE_READINESS_TRUTH — evidence / gate / prototype modules
    # =========================================================================

    OwnershipTruthSurface(
        surface_id="takeover_tracking_evidence",
        module_path="core.takeover_tracking",
        surface_name=(
            "takeover_tracking "
            "(accept/reject tracking evidence store — handoff prototype)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Records TakeoverTrackingRecord entries from Android "
            "TAKEOVER_RESPONSE messages.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it records "
            "accept/reject decisions as evidence but does NOT constitute a "
            "completed distributed ownership-transfer control plane.  "
            "Authority truth for session ownership remains with "
            "CanonicalSessionTruth and AttachedRuntimeSession."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="canonical_handoff_path_evidence",
        module_path="core.canonical_handoff_path",
        surface_name=(
            "canonical_handoff_path "
            "(handoff path anchor and closure evidence — PR-3)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Documents and asserts the single authoritative execution chain "
            "for cross-device handoff on the V2 side.  "
            "Source-to-target dispatch is operational; full bidirectional "
            "ownership transfer (target re-initiates back to source) is not "
            "implemented.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it is the "
            "canonical anchor for the handoff path contract, not a completed "
            "bidirectional mesh authority."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="pr3_session_continuity_authority_evidence",
        module_path="core.pr3_session_continuity_authority",
        surface_name=(
            "pr3_session_continuity_authority "
            "(session reconnect / continuity evidence — PR-3)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Classifies session reconnect and takeover governance decisions: "
            "confirmed_strong, degraded_partial, etc.  "
            "Also provides TakeoverGovernanceDecision: proceed / "
            "revalidate_ownership / block_takeover.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it produces "
            "governance evidence records; actual session lifecycle authority "
            "remains with AttachedRuntimeSession."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="durable_truth_authority_chain_convergence",
        module_path="core.durable_truth_authority_chain.DurableTruthAuthorityChain",
        surface_name=(
            "DurableTruthAuthorityChain "
            "(durable session/task/result convergence evidence — PR-2)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Wires session truth, task lifecycle, and result continuity "
            "into a unified durable authority chain.  Convergence check "
            "verifies all three legs are healthy.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it provides "
            "convergence evidence; the ring buffer is a read-cache of the "
            "durable path, not a competing truth source."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="attached_runtime_reuse_binding_evidence",
        module_path="core.attached_runtime_reuse_binding",
        surface_name=(
            "attached_runtime_reuse_binding "
            "(session reuse binding evidence)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Provides session reuse binding evidence: whether an existing "
            "attached runtime session can be reused for a new dispatch.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it advises "
            "the dispatch path; session lifecycle authority remains with "
            "AttachedRuntimeSession."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="android_handoff_v2_response_ingress_evidence",
        module_path="core.android_handoff_v2_response_ingress",
        surface_name=(
            "android_handoff_v2_response_ingress "
            "(handoff v2 response ingress — prototype evidence)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Processes HandoffEnvelopeV2 responses from Android (accept / "
            "reject) and feeds the result into the V2 handoff state machine.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it produces "
            "handoff acceptance evidence; it is part of the handoff/takeover "
            "prototype and does not constitute completed bidirectional mesh "
            "ownership-transfer authority."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="android_delegated_lifecycle_coordinator_evidence",
        module_path="core.android_delegated_runtime_lifecycle_coordinator",
        surface_name=(
            "AndroidDelegatedRuntimeLifecycleCoordinator "
            "(delegated lifecycle event facade — prototype evidence)"
        ),
        truth_domain=OwnershipTruthDomainKind.acceptance_closure_readiness_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Sequences per-event ingress → state-update → audit for Android "
            "delegated runtime lifecycle events.  "
            "Truth domain: ACCEPTANCE_CLOSURE_READINESS_TRUTH — it produces "
            "event-sequencing evidence records; it is a delegated-lifecycle "
            "event facade, not a completed distributed lifecycle authority.  "
            "Naming risk: 'coordinator' implies global lifecycle authority; "
            "it is a per-event facade only."
        ),
    ),

    # =========================================================================
    # OUTWARD_PROJECTION_OPERATOR_TRUTH — read-only projection surfaces
    # =========================================================================

    OwnershipTruthSurface(
        surface_id="runtime_truth_projection_route",
        module_path="core.routes.projection",
        surface_name=(
            "core.routes.projection "
            "(runtime-truth projection endpoint — Stage 3)"
        ),
        truth_domain=OwnershipTruthDomainKind.outward_projection_operator_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Stage 3 projection surface in the runtime truth output chain.  "
            "GET /api/v1/projection/runtime-truth reads from "
            "compile_outward_truth() (Stage 2).  "
            "MUST NOT call compile_runtime_truth() (Stage 1) directly when "
            "Stage 2 is available.  "
            "MUST NOT reverse-inject snapshot fields into authority truth modules."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="outward_runtime_truth_assembler",
        module_path="core.outward_runtime_truth.compile_outward_truth",
        surface_name=(
            "outward_runtime_truth.compile_outward_truth "
            "(outward truth assembler — Stage 2)"
        ),
        truth_domain=OwnershipTruthDomainKind.outward_projection_operator_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Stage 2 outward truth assembler.  Calls Stage 1 ONCE and adds "
            "operator/bridge/ACE context enrichment.  "
            "Is the single outward compilation point for all projection "
            "surfaces.  Stage 3 MUST use this function; Stage 3 MUST NOT "
            "call Stage 1 (compile_runtime_truth) directly."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="truth_projection_boundary_classifier",
        module_path="core.truth_projection_boundary",
        surface_name=(
            "truth_projection_boundary "
            "(truth vs projection boundary classifier — PR-7)"
        ),
        truth_domain=OwnershipTruthDomainKind.outward_projection_operator_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Classifies participant/device/session/capability/execution "
            "surfaces into truth-owner, projection/read-model, "
            "synchronization-mapping, and compatibility-only roles (PR-7).  "
            "Is a read-only classification surface; it does not produce "
            "or modify authority truth."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="runtime_truth_output_chain_catalog",
        module_path="core.runtime_truth_output_chain",
        surface_name=(
            "runtime_truth_output_chain "
            "(Stage 1/2/3 chain catalog and governance — PR-9)"
        ),
        truth_domain=OwnershipTruthDomainKind.outward_projection_operator_truth,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Documents and governs the Stage 1 → 2 → 3 runtime truth output "
            "chain (PR-9).  Is a governance / catalog module — it does not "
            "produce authority truth; it classifies and constrains the output "
            "chain stages."
        ),
    ),

    # =========================================================================
    # DIAGNOSTICS_AUDIT_ARTIFACT — forensic records and gate scaffolds
    # =========================================================================

    OwnershipTruthSurface(
        surface_id="android_delegated_runtime_audit_diagnostics",
        module_path="core.android_delegated_runtime_audit",
        surface_name=(
            "android_delegated_runtime_audit "
            "(delegated runtime diagnostics surface)"
        ),
        truth_domain=OwnershipTruthDomainKind.diagnostics_audit_artifact,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Read-only diagnostics surface for Android delegated runtime "
            "lifecycle events.  Records and surfaces audit events for operator "
            "inspection.  MUST NOT be read back as an input to authority truth "
            "or acceptance truth decisions."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="distributed_release_gate_scaffold_diagnostics",
        module_path="core.distributed_release_gate_skeleton",
        surface_name=(
            "distributed_release_gate_skeleton "
            "(diagnostic gate scaffold)"
        ),
        truth_domain=OwnershipTruthDomainKind.diagnostics_audit_artifact,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Diagnostic gate scaffold that records readiness evidence for "
            "release criteria.  Not a runtime execution gate.  "
            "Naming risk: 'distributed' in the module name could imply a "
            "distributed control-plane gate.  Reality: it is a diagnostic "
            "scaffold for surfacing readiness evidence to CI/operators."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="architecture_diagnostics_snapshot",
        module_path="core.architecture_diagnostics",
        surface_name=(
            "architecture_diagnostics "
            "(architecture health diagnostics snapshot)"
        ),
        truth_domain=OwnershipTruthDomainKind.diagnostics_audit_artifact,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Provides architecture-health diagnostic snapshots for CI and "
            "operator inspection.  Records invariant check results.  "
            "MUST NOT be read back as authority truth input."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="center_distributed_review_audit",
        module_path="core.center_distributed_agent_system_review",
        surface_name=(
            "center_distributed_agent_system_review "
            "(agent system classification audit surface)"
        ),
        truth_domain=OwnershipTruthDomainKind.diagnostics_audit_artifact,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Operator review / audit surface that classifies agent system "
            "components.  Not a runtime execution component.  "
            "Naming risk: 'distributed' could imply runtime boundary "
            "authority; it is an audit/operator surface."
        ),
    ),
    OwnershipTruthSurface(
        surface_id="distributed_runtime_boundary_declaration",
        module_path="core.distributed_runtime_boundary",
        surface_name=(
            "distributed_runtime_boundary "
            "(distributed runtime boundary declaration — PR-8)"
        ),
        truth_domain=OwnershipTruthDomainKind.diagnostics_audit_artifact,
        may_not_redefine_authority_truth=True,
        android_uplink_canonical_entry=False,
        notes=(
            "Authoritative declaration of the distributed runtime boundary "
            "(PR-8).  Classifies all distributed runtime surfaces.  "
            "Is a governance declaration module — it does not produce "
            "authority truth; it documents the boundary."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Android uplink canonical chain path declaration
# ---------------------------------------------------------------------------

#: Ordered sequence of module paths forming the canonical Android uplink
#: entry into the V2 truth output chain.
ANDROID_UPLINK_CANONICAL_CHAIN_PATH: Tuple[str, ...] = (
    "galaxy_gateway.android.handlers",
    "core.android_participant_truth_ingress",
    "core.v2_android_truth_ssot.build_v2_android_truth_block",
    "core.canonical_session_truth.merge_session_truth",
    "core.projection.runtime_truth_compiler.compile_runtime_truth",
    "core.outward_runtime_truth.compile_outward_truth",
)
"""Canonical ordered sequence of module paths for the Android uplink entry
into the V2 canonical truth output chain.

Any Android uplink path that terminates before reaching
``core.v2_android_truth_ssot.build_v2_android_truth_block`` is a
``generic_forward`` or ``UI-only`` path and MUST NOT be described as
entering the V2 canonical truth output chain.
"""


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_ownership_truth_registry() -> List[OwnershipTruthSurface]:
    """Return the full ownership truth surface registry.

    Returns
    -------
    List[OwnershipTruthSurface]
        All surfaces classified within the distributed truth ownership boundary.
    """
    return list(OWNERSHIP_TRUTH_SURFACE_REGISTRY)


def classify_ownership_truth_domain(surface_id: str) -> str:
    """Classify *surface_id* into its ownership truth domain value.

    Parameters
    ----------
    surface_id:
        Short stable surface identifier or module path to look up.

    Returns
    -------
    str
        The :attr:`OwnershipTruthDomainKind.value` of the matching domain, or
        ``"unknown"`` if no match is found.
    """
    normalised = (surface_id or "").strip()
    if not normalised:
        return "unknown"
    for surface in OWNERSHIP_TRUTH_SURFACE_REGISTRY:
        if normalised == surface.surface_id or normalised == surface.module_path:
            return surface.truth_domain.value
    return "unknown"


def get_surfaces_by_truth_domain(
    domain: OwnershipTruthDomainKind,
) -> List[OwnershipTruthSurface]:
    """Return all surfaces with the given *domain* classification.

    Parameters
    ----------
    domain:
        The :class:`OwnershipTruthDomainKind` to filter by.

    Returns
    -------
    List[OwnershipTruthSurface]
        Surfaces matching the requested domain.
    """
    return [s for s in OWNERSHIP_TRUTH_SURFACE_REGISTRY if s.truth_domain is domain]


def get_android_uplink_canonical_chain_path() -> Tuple[str, ...]:
    """Return the ordered canonical Android uplink chain path.

    Returns
    -------
    Tuple[str, ...]
        Ordered module path sequence from Android gateway handlers through to
        the V2 outward truth assembler.
    """
    return ANDROID_UPLINK_CANONICAL_CHAIN_PATH


def build_ownership_truth_convergence_snapshot() -> OwnershipTruthConvergenceSnapshot:
    """Build a full diagnostic snapshot of the ownership truth convergence.

    Returns
    -------
    OwnershipTruthConvergenceSnapshot
        Contains authority/sentinel/policies, domain counts, and the Android
        uplink canonical entries list.
    """
    registry = OWNERSHIP_TRUTH_SURFACE_REGISTRY
    authority_entries = [
        s.surface_id
        for s in registry
        if s.android_uplink_canonical_entry
    ]
    return OwnershipTruthConvergenceSnapshot(
        authority=DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY,
        sentinel=DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL,
        policies=(
            PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY,
            ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY,
            OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY,
            NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY,
            DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY,
        ),
        total_surfaces=len(registry),
        authority_truth_count=sum(
            1 for s in registry
            if s.truth_domain is OwnershipTruthDomainKind.authority_truth
        ),
        acceptance_closure_count=sum(
            1 for s in registry
            if s.truth_domain is OwnershipTruthDomainKind.acceptance_closure_readiness_truth
        ),
        outward_projection_count=sum(
            1 for s in registry
            if s.truth_domain is OwnershipTruthDomainKind.outward_projection_operator_truth
        ),
        diagnostics_audit_count=sum(
            1 for s in registry
            if s.truth_domain is OwnershipTruthDomainKind.diagnostics_audit_artifact
        ),
        android_uplink_canonical_entries=authority_entries,
    )
