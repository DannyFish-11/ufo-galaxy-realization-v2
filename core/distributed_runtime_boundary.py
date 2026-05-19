#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/distributed_runtime_boundary.py
======================================
PR-8: Distributed Runtime Boundary Convergence — authoritative boundary
declaration for the distributed runtime, cross-device execution, handoff /
takeover prototypes, and Android participation semantics.

Purpose
-------
This module is the **single authoritative declaration** of the distributed
runtime boundary for the Galaxy/OpenClawd system.  It resolves semantic drift
where ``distributed``, ``handoff``, ``takeover``, ``ownership``, and
``relay/forwarding`` concepts have accumulated ambiguous naming that blurs
the line between:

1. The **real distributed runtime main chain** — the actual execution path
   when ``execution_path = "cross_device"`` is resolved.
2. The **transport / relay / dispatch / forwarding layer** — infrastructure
   wiring that moves tasks and results between nodes.
3. The **handoff / takeover prototypes** — real but incomplete scaffolding
   for bidirectional execution transfer; not full mesh control plane.
4. The **projection / diagnostics / operator-visible layer** — read-only
   surfaces that surface runtime truth outward.
5. **Android participation semantics** — Android as a first-class runtime
   host node, not a passive relay.

This module does **not** introduce new runtime logic.  It consolidates and
locks the existing architectural declarations so that:

* The distributed runtime main chain is unambiguous and not over-stated.
* Transport / relay / forwarding layers are not mis-labelled as distributed
  control plane.
* Handoff / takeover prototypes are acknowledged as prototypes — they express
  bidirectional transfer intent but are not a completed bidirectional mesh.
* Projection / diagnostics / operator surfaces cannot be mistaken for
  canonical distributed runtime authorities.
* Android's first-class runtime node status is formally declared and preserved
  through every subsequent refactor.

Naming drift that this PR addresses
-------------------------------------
Prior to this module the following semantic confusions existed:

* ``galaxy_gateway.agent_bridge`` — the word "bridge" with a
  :meth:`~galaxy_gateway.agent_bridge.AgentBridge.handoff` method could be
  read as a complete bidirectional handoff bus.  Reality: it is a
  **transport relay adapter** that dispatches to a remote ``/handoff``
  endpoint and falls back to the local cross-device coordinator.  The
  bidirectional takeover path on the Android side is a separate system.

* ``core.takeover_tracking`` — the word "tracking" with ownership-convergence
  adjudication could be read as a completed ownership-transfer control plane.
  Reality: it is a **prototype tracking ring-buffer** that records
  accept/reject decisions so the V2 orchestration layer can correlate them.
  It does NOT constitute a completed bidirectional takeover control plane.

* ``core.android_delegated_runtime_lifecycle_coordinator`` — the word
  "coordinator" could imply that this module governs distributed runtime
  lifecycle globally.  Reality: it is a **delegated-lifecycle event facade**
  that sequences per-event ingress → state-update → audit on the V2 side for
  Android-originated lifecycle signals.

* ``core.distributed_release_gate_skeleton`` — the word "distributed" in
  a module named ``release_gate_skeleton`` could be mistaken for a
  distributed control-plane gate.  Reality: it is a **diagnostic / gate
  scaffold** that records readiness evidence for release criteria; not a
  runtime execution gate.

* ``core.center_distributed_agent_system_review`` — the word "distributed"
  could imply this is the runtime boundary authority.  Reality: it is an
  **operator review / audit surface** that classifies agent system
  components; not a runtime execution component.

* ``galaxy_gateway.cross_device_coordinator`` — "coordinator" could imply
  it owns cross-device orchestration authority globally.  Reality: it is an
  **internal cross-device substrate** called by ``DeviceRouter``, not a
  primary session entry.

Real distributed runtime main chain (unchanged from prior PRs)
--------------------------------------------------------------
::

    DesktopPresenceRuntime (runtime shell)           ← tri-state lifecycle owner
        └─ LIMINAL: OpenClawd (subject core)         ← execution-path authority
              Stage 3 branch → execution_path = "cross_device" | "hybrid"
              Stage 4 manifest
                └─ CommandRouter.route_envelope()    ← cross-device loop entry
                      └─ DeviceRouter.route_task()   ← device dispatch
                            └─ Android/device node   ← first-class runtime host

On the Android side:
    GalaxyWebSocketClient / GalaxyConnectionService
        └─ RuntimeController                         ← Android runtime node
              └─ AutonomousExecutionPipeline          ← Android execution

This is the **real** distributed runtime.  Everything else in this taxonomy
is infrastructure, prototype, or projection.

Distributed runtime layer roles
--------------------------------
DISTRIBUTED_RUNTIME_MAIN_CHAIN
    The real canonical execution path for cross-device requests.  Modules
    in this role are on the hot path and own runtime authority.

TRANSPORT_RELAY_DISPATCH_LAYER
    Infrastructure modules that move envelopes / results between nodes.
    They do NOT own orchestration authority; they are transport substrate.

HANDOFF_TAKEOVER_PROTOTYPE
    Modules that implement the bidirectional execution-transfer scaffolding.
    These are real, working prototypes — they are not dead code — but they
    do NOT constitute a completed bidirectional mesh or full takeover control
    plane.  The current state is: source-to-target dispatch works; full
    bidirectional ownership transfer (target can re-initiate back to source)
    is incomplete.

PROJECTION_DIAGNOSTICS_OPERATOR
    Read-only surfaces that project distributed runtime truth outward to
    operators, dashboards, audits, or CI gates.  They MUST NOT be treated
    as canonical runtime authorities or distributed control-plane components.

ANDROID_PARTICIPATION_RUNTIME_NODE
    Android-side modules that constitute Android's participation as a
    first-class runtime host node.  These modules establish, maintain, and
    signal Android's runtime participation — they are not passive relay.

Policy invariants
-----------------
1. The distributed runtime main chain is exactly the five-node sequence:
   DesktopPresenceRuntime → OpenClawd → CommandRouter → DeviceRouter →
   Android runtime node.  No other module is the distributed runtime main
   chain authority.

2. Transport / relay / dispatch / forwarding modules MUST NOT be treated as
   distributed control plane.  They carry envelopes; they do not own
   coordination authority.

3. Handoff / takeover prototypes represent a real but incomplete bidirectional
   transfer capability.  They MUST NOT be described as a completed mesh or
   bidirectional takeover system.  They also MUST NOT be demoted to generic
   relay — they express genuine ownership-transfer intent.

4. Projection / diagnostics / operator surfaces MUST NOT claim distributed
   runtime authority.  They surface truth outward; they do not produce truth.

5. Android devices participate as first-class runtime host nodes via the
   canonical DeviceRouter → gateway dispatch path.  Android MUST NOT be
   relegated to passive forwarder, relay, or result-uplink-only mode.

6. A new parallel distributed runtime framework MUST NOT be introduced.
   The existing chain is the canonical distributed runtime; extensions must
   integrate into it, not alongside it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

__all__ = [
    # Sentinels
    "DISTRIBUTED_RUNTIME_BOUNDARY_AUTHORITY",
    "DISTRIBUTED_RUNTIME_BOUNDARY_PR8_SENTINEL",
    "TRANSPORT_RELAY_IS_NOT_DISTRIBUTED_CONTROL_PLANE_POLICY",
    "HANDOFF_TAKEOVER_IS_PROTOTYPE_NOT_FULL_MESH_POLICY",
    "PROJECTION_DIAGNOSTICS_MUST_NOT_CLAIM_RUNTIME_AUTHORITY_POLICY",
    "ANDROID_IS_FIRST_CLASS_RUNTIME_HOST_NODE_POLICY",
    "NO_NEW_PARALLEL_DISTRIBUTED_RUNTIME_POLICY",
    # Enums
    "DistributedRuntimeLayerRole",
    # Data classes
    "DistributedRuntimeSurface",
    "DistributedRuntimeBoundaryReport",
    # Functions
    "get_distributed_runtime_registry",
    "classify_distributed_surface",
    "get_surfaces_by_distributed_role",
    "build_distributed_runtime_boundary_report",
]

# ---------------------------------------------------------------------------
# Module-level authority sentinels
# ---------------------------------------------------------------------------

DISTRIBUTED_RUNTIME_BOUNDARY_AUTHORITY: str = (
    "core.distributed_runtime_boundary"
)
"""Sentinel: identifies this module as the authoritative distributed runtime
boundary declaration for PR-8.  Import this symbol to assert that a call site
is operating within the declared distributed runtime boundary model."""

DISTRIBUTED_RUNTIME_BOUNDARY_PR8_SENTINEL: str = (
    "distributed_runtime_boundary_pr8_convergence"
)
"""PR-8 sentinel value.  All tests and CI gates that lock the PR-8
boundary declaration should assert the presence of this sentinel."""

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

TRANSPORT_RELAY_IS_NOT_DISTRIBUTED_CONTROL_PLANE_POLICY: str = (
    "transport_relay_dispatch_forwarding_layers_are_NOT_distributed_control_plane: "
    "modules that move envelopes or results between nodes are transport substrate; "
    "they do not own coordination authority and must not be treated as distributed "
    "control plane components"
)
"""Policy: transport / relay / dispatch / forwarding modules carry envelopes.
They are NOT distributed control plane authorities.
Affected modules: galaxy_gateway.agent_bridge, galaxy_gateway.cross_device_coordinator,
core.delegated_runtime_dispatch_intent, core.android_runtime_dispatch_binding,
core.android_delegated_signal_ingress."""

HANDOFF_TAKEOVER_IS_PROTOTYPE_NOT_FULL_MESH_POLICY: str = (
    "handoff_takeover_is_real_prototype_NOT_completed_bidirectional_mesh: "
    "source-to-target dispatch is operational; full bidirectional ownership "
    "transfer (target re-initiates back to source) is incomplete; "
    "modules in this category MUST NOT be described as a completed mesh "
    "or full takeover control plane, but MUST NOT be demoted to generic relay "
    "either — they express genuine ownership-transfer intent and partial "
    "execution; DeviceRouter and AgentBridge own the forward dispatch path; "
    "TakeoverTracking and AndroidDelegatedRuntimeLifecycleCoordinator own "
    "the response-side prototype"
)
"""Policy: handoff / takeover modules are prototypes.  They are real and
working in the forward direction but bidirectional mesh is not complete.
Affected modules: core.canonical_handoff_path, core.takeover_tracking,
core.android_handoff_v2_response_ingress,
core.android_delegated_runtime_lifecycle_coordinator,
contracts.handoff_envelope_v2."""

PROJECTION_DIAGNOSTICS_MUST_NOT_CLAIM_RUNTIME_AUTHORITY_POLICY: str = (
    "projection_diagnostics_operator_surfaces_MUST_NOT_claim_distributed_runtime_authority: "
    "these modules read and surface runtime truth outward to operators and dashboards; "
    "they do not produce runtime truth and must not act as runtime execution gates; "
    "core.distributed_release_gate_skeleton is a diagnostic gate scaffold only; "
    "core.center_distributed_agent_system_review is an audit surface only; "
    "core.android_delegated_runtime_audit is a diagnostics-read-only surface"
)
"""Policy: projection / diagnostics / operator surfaces are read-only.
They must not be treated as distributed control plane authorities.
Affected modules: core.android_delegated_runtime_audit,
core.distributed_release_gate_skeleton,
core.center_distributed_agent_system_review,
core.ownership_transfer_proof_quality,
core.flow_level_truth_ownership."""

ANDROID_IS_FIRST_CLASS_RUNTIME_HOST_NODE_POLICY: str = (
    "android_participates_as_first_class_runtime_host_node_NOT_passive_relay: "
    "Android devices join the distributed runtime via the canonical "
    "DeviceRouter → gateway dispatch path with source_runtime_posture=join_runtime; "
    "RuntimeController / GalaxyConnectionService / AutonomousExecutionPipeline "
    "constitute Android's runtime node execution; Android MUST NOT be "
    "relegated to passive forwarder, relay, or result-uplink-only mode; "
    "core.android_runtime_host provides the canonical role classification"
)
"""Policy: Android is a first-class runtime host node.
The canonical modules establishing this: core.android_runtime_host,
core.android_delegated_runtime_lifecycle_coordinator,
galaxy_gateway.android handlers."""

NO_NEW_PARALLEL_DISTRIBUTED_RUNTIME_POLICY: str = (
    "no_new_parallel_distributed_runtime_framework_allowed: "
    "the existing DesktopPresenceRuntime → OpenClawd → CommandRouter → "
    "DeviceRouter → Android runtime node chain is the canonical distributed "
    "runtime; extensions must integrate into this chain, not create a "
    "parallel distributed runtime framework alongside it; "
    "this constraint applies to future PRs and must not be bypassed"
)
"""Policy: no new parallel distributed runtime framework.
The existing four-module chain is canonical."""


# ---------------------------------------------------------------------------
# Distributed runtime layer role taxonomy
# ---------------------------------------------------------------------------

class DistributedRuntimeLayerRole(str, Enum):
    """Taxonomy of roles within the distributed runtime boundary.

    Used to classify every surface that touches distributed / cross-device
    execution so that CI gates and operator tools can assert correct
    architectural classification.
    """

    distributed_runtime_main_chain = "distributed_runtime_main_chain"
    """The real canonical execution path for cross-device requests.  Modules
    in this role are on the hot path and own runtime authority."""

    transport_relay_dispatch_layer = "transport_relay_dispatch_layer"
    """Infrastructure modules that move task envelopes and results between
    nodes.  They own transport substrate; they do NOT own coordination
    authority or distributed control-plane decisions."""

    handoff_takeover_prototype = "handoff_takeover_prototype"
    """Modules implementing bidirectional execution-transfer scaffolding.
    These are real working prototypes in the forward direction.  They are NOT
    a completed bidirectional mesh or full ownership-transfer control plane."""

    projection_diagnostics_operator = "projection_diagnostics_operator"
    """Read-only surfaces that project distributed runtime truth outward.
    They surface truth; they do not produce it.  They MUST NOT act as
    canonical runtime authorities."""

    android_participation_runtime_node = "android_participation_runtime_node"
    """Android-side / Android-integration modules that constitute Android's
    first-class runtime node participation.  Not passive relay — genuine
    runtime execution nodes."""


# ---------------------------------------------------------------------------
# Surface data class
# ---------------------------------------------------------------------------

@dataclass
class DistributedRuntimeSurface:
    """Single surface entry in the distributed runtime boundary registry.

    Parameters
    ----------
    surface_id:
        Short stable identifier (e.g. ``"device_router_dispatch"``).
    module_path:
        Fully-qualified Python module path (e.g. ``"galaxy_gateway.device_router"``).
    surface_name:
        Human-readable surface name with brief role summary.
    distributed_role:
        :class:`DistributedRuntimeLayerRole` classification.
    is_distributed_runtime_main_chain:
        ``True`` only for the four canonical main-chain modules.
    may_not_claim_distributed_control_plane:
        ``True`` for all non-main-chain modules — they MUST NOT claim to be
        a distributed control plane authority.
    notes:
        Human-readable explanation of the surface's actual role, any naming
        risk, and governance constraints.
    """

    surface_id: str
    module_path: str
    surface_name: str
    distributed_role: DistributedRuntimeLayerRole
    is_distributed_runtime_main_chain: bool = False
    may_not_claim_distributed_control_plane: bool = True
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "surface_name": self.surface_name,
            "distributed_role": self.distributed_role.value,
            "is_distributed_runtime_main_chain": self.is_distributed_runtime_main_chain,
            "may_not_claim_distributed_control_plane": (
                self.may_not_claim_distributed_control_plane
            ),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Boundary report data class
# ---------------------------------------------------------------------------

@dataclass
class DistributedRuntimeBoundaryReport:
    """Aggregate boundary report produced by
    :func:`build_distributed_runtime_boundary_report`.
    """

    total_surfaces: int = 0
    main_chain_count: int = 0
    transport_relay_count: int = 0
    handoff_takeover_prototype_count: int = 0
    projection_diagnostics_count: int = 0
    android_participation_count: int = 0
    constrained_surfaces: List[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "total_surfaces": self.total_surfaces,
            "main_chain_count": self.main_chain_count,
            "transport_relay_count": self.transport_relay_count,
            "handoff_takeover_prototype_count": (
                self.handoff_takeover_prototype_count
            ),
            "projection_diagnostics_count": self.projection_diagnostics_count,
            "android_participation_count": self.android_participation_count,
            "constrained_surfaces": self.constrained_surfaces,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Distributed runtime surface registry
# ---------------------------------------------------------------------------

#: All surfaces classified within the distributed runtime boundary.
DISTRIBUTED_RUNTIME_SURFACE_REGISTRY: List[DistributedRuntimeSurface] = [

    # =========================================================================
    # Distributed runtime main chain
    # =========================================================================

    DistributedRuntimeSurface(
        surface_id="desktop_presence_runtime_shell",
        module_path="core.desktop_presence_runtime.DesktopPresenceRuntime",
        surface_name="DesktopPresenceRuntime (runtime shell, tri-state lifecycle owner)",
        distributed_role=DistributedRuntimeLayerRole.distributed_runtime_main_chain,
        is_distributed_runtime_main_chain=True,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Canonical runtime shell.  Owns the tri-state lifecycle "
            "(silent/liminal/manifest) and the runtime_session_id.  "
            "Invokes OpenClawd inside the liminal phase.  "
            "Entry point for the distributed runtime main chain when "
            "execution_path resolves to cross_device or hybrid."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="openclawd_subject_core",
        module_path="core.openclawd.OpenClawd",
        surface_name="OpenClawd (subject/execution core, execution-path authority)",
        distributed_role=DistributedRuntimeLayerRole.distributed_runtime_main_chain,
        is_distributed_runtime_main_chain=True,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Subject/execution core.  Owns execution-path branching "
            "(local / cross_device / hybrid / none) in Stage 3.  "
            "When cross_device or hybrid is resolved, Stage 4 invokes "
            "CommandRouter.route_envelope() as the cross-device expansion loop.  "
            "OpenClawd is the single authority that decides whether a request "
            "enters the distributed runtime."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="command_router_cross_device_loop",
        module_path="core.command_router.CommandRouter",
        surface_name="CommandRouter (cross-device execution loop, orchestration authority)",
        distributed_role=DistributedRuntimeLayerRole.distributed_runtime_main_chain,
        is_distributed_runtime_main_chain=True,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Cross-device liminal domain expansion router.  Owns ACL "
            "enforcement, HITL gate, lifecycle state transitions, retry / "
            "circuit-breaker, trace propagation, and TaskEnvelope plumbing.  "
            "CommandRouter.route_envelope() is the canonical substrate "
            "entry-point for both command_only and agent_runtime dispatch paths."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="device_router_dispatch",
        module_path="galaxy_gateway.device_router.DeviceRouter",
        surface_name="DeviceRouter (device dispatch authority, transport session manager)",
        distributed_role=DistributedRuntimeLayerRole.distributed_runtime_main_chain,
        is_distributed_runtime_main_chain=True,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Canonical device dispatch authority.  Owns WebSocket/transport "
            "session handles and all device-level routing.  "
            "CommandRouter delegates transport to DeviceRouter; no other "
            "module should own live device connections.  "
            "DeviceRouter.route_task() is the dispatch entry to the "
            "Android/device runtime node."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_runtime_node",
        module_path="android.RuntimeController",
        surface_name="Android RuntimeController (first-class runtime host node)",
        distributed_role=DistributedRuntimeLayerRole.distributed_runtime_main_chain,
        is_distributed_runtime_main_chain=True,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Android-side runtime node.  RuntimeController (via "
            "GalaxyConnectionService / GalaxyWebSocketClient) receives the "
            "dispatched task envelope and drives AutonomousExecutionPipeline "
            "on the Android device.  This is the terminal node in the "
            "distributed runtime main chain — a first-class runtime host, "
            "not a passive relay."
        ),
    ),

    # =========================================================================
    # Transport / relay / dispatch / forwarding layer
    # =========================================================================

    DistributedRuntimeSurface(
        surface_id="agent_bridge_handoff_relay",
        module_path="galaxy_gateway.agent_bridge.AgentBridge",
        surface_name="AgentBridge (runtime handoff transport relay)",
        distributed_role=DistributedRuntimeLayerRole.transport_relay_dispatch_layer,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Transport relay adapter for handoff dispatch.  "
            "AgentBridge.handoff() dispatches to a remote /handoff endpoint "
            "and falls back to the local cross-device coordinator.  "
            "Naming risk: 'bridge' with a handoff() method could imply a "
            "completed bidirectional handoff bus.  Reality: it is a "
            "transport relay — it carries the handoff envelope to the remote "
            "node; it does not own bidirectional ownership-transfer authority.  "
            "Called by DeviceRouter as part of the cross-device dispatch path."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="cross_device_coordinator_substrate",
        module_path="galaxy_gateway.cross_device_coordinator",
        surface_name="cross_device_coordinator (internal cross-device substrate)",
        distributed_role=DistributedRuntimeLayerRole.transport_relay_dispatch_layer,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Internal cross-device execution substrate called by DeviceRouter.  "
            "Manages the cross-device coordination session beneath the dispatch "
            "layer.  Not a primary session authority or an orchestration entry.  "
            "Naming risk: 'coordinator' implies orchestration authority; it is "
            "an internal substrate."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="delegated_runtime_dispatch_intent",
        module_path="core.delegated_runtime_dispatch_intent",
        surface_name="delegated_runtime_dispatch_intent (dispatch intent helper)",
        distributed_role=DistributedRuntimeLayerRole.transport_relay_dispatch_layer,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Dispatch intent helper for delegated runtime execution.  "
            "Encodes the intent for delegating execution to a remote device "
            "runtime.  Not a runtime authority — it is a typed dispatch "
            "instruction passed to the transport layer."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_runtime_dispatch_binding",
        module_path="core.android_runtime_dispatch_binding",
        surface_name="android_runtime_dispatch_binding (Android dispatch binding helper)",
        distributed_role=DistributedRuntimeLayerRole.transport_relay_dispatch_layer,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Android runtime dispatch binding helper.  Wires Android device "
            "participation into the dispatch substrate.  Not an orchestration "
            "authority; it is an integration helper for the dispatch path.  "
            "Classified as android_runtime_binding_helper in SIDE_PATH_MODULE_REGISTRY."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_delegated_signal_ingress",
        module_path="core.android_delegated_signal_ingress",
        surface_name="android_delegated_signal_ingress (Android result/status uplink ingress)",
        distributed_role=DistributedRuntimeLayerRole.transport_relay_dispatch_layer,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Ingress adapter for Android-originated execution signals — "
            "result uplink, status uplink, and delegated execution events.  "
            "Feeds signals into the V2 lifecycle state machine.  "
            "This is the uplink side of the transport layer; it is not "
            "a runtime authority."
        ),
    ),

    # =========================================================================
    # Handoff / takeover prototypes
    # =========================================================================

    DistributedRuntimeSurface(
        surface_id="canonical_handoff_path",
        module_path="core.canonical_handoff_path",
        surface_name="canonical_handoff_path (handoff path anchor — PR-3)",
        distributed_role=DistributedRuntimeLayerRole.handoff_takeover_prototype,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Main-repo-side handoff / takeover path anchor (PR-3).  "
            "Documents and asserts the single authoritative execution chain "
            "for cross-device handoff on the main-repo side.  "
            "Current state: source-side dispatch to target is operational.  "
            "Full bidirectional ownership transfer (target re-initiates to "
            "source) is not implemented.  This module is the canonical "
            "anchor for the handoff path contract."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="takeover_tracking_prototype",
        module_path="core.takeover_tracking",
        surface_name="takeover_tracking (accept/reject tracking prototype)",
        distributed_role=DistributedRuntimeLayerRole.handoff_takeover_prototype,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Canonical takeover accept/reject tracking ring-buffer.  "
            "Records TakeoverTrackingRecord entries from Android "
            "TAKEOVER_RESPONSE messages so V2 can correlate ownership "
            "convergence.  "
            "Naming risk: 'ownership convergence adjudication' could imply "
            "a completed distributed ownership-transfer control plane.  "
            "Reality: this is a prototype tracking store — it records "
            "decisions but does not orchestrate the full bidirectional "
            "ownership-transfer lifecycle.  "
            "Real handoff/takeover proto: Android can accept/reject; "
            "full re-initiation from target back to source is incomplete."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_handoff_v2_response_ingress",
        module_path="core.android_handoff_v2_response_ingress",
        surface_name="android_handoff_v2_response_ingress (handoff v2 response ingress)",
        distributed_role=DistributedRuntimeLayerRole.handoff_takeover_prototype,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Ingress handler for HandoffEnvelopeV2 responses from Android.  "
            "Processes the Android-side handoff acceptance / rejection and "
            "feeds the result into the V2 handoff state machine.  "
            "Part of the handoff/takeover prototype chain — not a completed "
            "bidirectional mesh."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_delegated_runtime_lifecycle_coordinator",
        module_path="core.android_delegated_runtime_lifecycle_coordinator",
        surface_name=(
            "AndroidDelegatedRuntimeLifecycleCoordinator "
            "(delegated lifecycle event facade)"
        ),
        distributed_role=DistributedRuntimeLayerRole.handoff_takeover_prototype,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Singleton coordinator facade with one on_* method per "
            "Android delegated runtime lifecycle event: "
            "on_handoff_dispatched, on_takeover_response, "
            "on_reconciliation_signal, on_execution_signal, "
            "on_participant_truth_update.  "
            "Sequences ingress → state-update → audit for each event.  "
            "Naming risk: 'coordinator' in an Android lifecycle context "
            "could imply global distributed lifecycle authority.  "
            "Reality: this is a delegated-lifecycle event facade that "
            "sequences per-event handling on the V2 side.  "
            "Part of the handoff/takeover prototype: it processes the "
            "Android side of the handoff/takeover lifecycle but does not "
            "constitute a completed bidirectional control plane."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="handoff_envelope_v2_contract",
        module_path="contracts.handoff_envelope_v2",
        surface_name="HandoffEnvelopeV2 (handoff envelope contract — PR-31)",
        distributed_role=DistributedRuntimeLayerRole.handoff_takeover_prototype,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Wire contract for cross-device handoff dispatch (PR-31).  "
            "Carries source/target device IDs, runtime postures, agent "
            "dispatch metadata, handoff policy, and takeover permission flags.  "
            "The envelope is sent by the V2 source to the Android target.  "
            "This is the data contract for the handoff prototype — not a "
            "completed bidirectional mesh protocol."
        ),
    ),

    # =========================================================================
    # Projection / diagnostics / operator layer
    # =========================================================================

    DistributedRuntimeSurface(
        surface_id="android_delegated_runtime_audit",
        module_path="core.android_delegated_runtime_audit",
        surface_name="android_delegated_runtime_audit (delegated runtime diagnostics)",
        distributed_role=DistributedRuntimeLayerRole.projection_diagnostics_operator,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Read-only diagnostics surface for Android delegated runtime "
            "lifecycle events.  Records and surfaces audit events.  "
            "Does NOT produce runtime truth; surfaces it outward.  "
            "MUST NOT be treated as a distributed runtime authority."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="distributed_release_gate_skeleton",
        module_path="core.distributed_release_gate_skeleton",
        surface_name=(
            "distributed_release_gate_skeleton (diagnostic gate scaffold)"
        ),
        distributed_role=DistributedRuntimeLayerRole.projection_diagnostics_operator,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Diagnostic gate scaffold that records and surfaces distributed "
            "runtime readiness evidence for release criteria.  "
            "Naming risk: 'distributed' in the module name could imply it "
            "is a distributed control-plane gate.  Reality: it is a "
            "release-criteria evidence recorder and CI gate scaffold — "
            "not a runtime execution gate or distributed control plane."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="center_distributed_agent_system_review",
        module_path="core.center_distributed_agent_system_review",
        surface_name=(
            "center_distributed_agent_system_review (operator audit surface)"
        ),
        distributed_role=DistributedRuntimeLayerRole.projection_diagnostics_operator,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Operator review / audit surface that classifies agent system "
            "components relative to the center/distributed boundary.  "
            "Naming risk: 'distributed' in the module name could imply "
            "runtime boundary authority.  Reality: it is a read-only "
            "operator audit surface — it classifies and reviews; it does "
            "not execute distributed runtime logic."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="ownership_transfer_proof_quality",
        module_path="core.ownership_transfer_proof_quality",
        surface_name="ownership_transfer_proof_quality (ownership proof diagnostics)",
        distributed_role=DistributedRuntimeLayerRole.projection_diagnostics_operator,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Diagnostics surface that assesses the quality of ownership "
            "transfer proof evidence from Android takeover responses.  "
            "Provides quality metrics for the takeover prototype chain.  "
            "Does NOT own runtime authority or produce canonical ownership "
            "state — it grades evidence quality only."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="flow_level_truth_ownership",
        module_path="core.flow_level_truth_ownership",
        surface_name="flow_level_truth_ownership (flow-level ownership diagnostics)",
        distributed_role=DistributedRuntimeLayerRole.projection_diagnostics_operator,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=True,
        notes=(
            "Flow-level ownership truth diagnostics surface.  Surfaces "
            "ownership information at the execution-flow level for "
            "operator visibility.  Read-only — does not produce or transfer "
            "ownership.  MUST NOT be treated as a runtime authority."
        ),
    ),

    # =========================================================================
    # Android participation runtime node
    # =========================================================================

    DistributedRuntimeSurface(
        surface_id="android_runtime_host_classification",
        module_path="core.android_runtime_host",
        surface_name="android_runtime_host (Android first-class runtime host classifier)",
        distributed_role=DistributedRuntimeLayerRole.android_participation_runtime_node,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Canonical classification of Android as a first-class runtime "
            "host node (PR-5).  Provides AndroidRuntimeHostRole enum, "
            "AndroidRuntimeHostIdentity snapshot, and "
            "classify_android_runtime_host() helper.  "
            "Android devices that register with source_runtime_posture="
            "join_runtime are classified as FULL_RUNTIME_HOST.  "
            "This module establishes the formal contract that Android is a "
            "genuine distributed runtime node — not a peripheral or relay."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_gateway_handlers",
        module_path="galaxy_gateway.android",
        surface_name="galaxy_gateway.android (Android gateway ingress handlers)",
        distributed_role=DistributedRuntimeLayerRole.android_participation_runtime_node,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Android gateway ingress handler package.  Receives and "
            "processes all Android-originated protocol messages: "
            "registration, task dispatch, takeover response, reconciliation "
            "signal, execution signal, participant truth update.  "
            "These handlers are the V2-side entry points for Android's "
            "runtime participation — they translate wire messages into "
            "lifecycle coordinator calls and state-update events."
        ),
    ),
    DistributedRuntimeSurface(
        surface_id="android_originated_authority_boundary",
        module_path="core.android_originated_authority_boundary",
        surface_name=(
            "android_originated_authority_boundary "
            "(Android origin authority boundary)"
        ),
        distributed_role=DistributedRuntimeLayerRole.android_participation_runtime_node,
        is_distributed_runtime_main_chain=False,
        may_not_claim_distributed_control_plane=False,
        notes=(
            "Authority boundary classifier for Android-originated signals.  "
            "Distinguishes signals that carry runtime authority (execution "
            "results, state transitions, ownership acknowledgements) from "
            "signals that are informational only.  "
            "Preserves Android's first-class node status by correctly "
            "attributing authority to Android-side execution outcomes."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------


def get_distributed_runtime_registry() -> List[DistributedRuntimeSurface]:
    """Return all surfaces in the distributed runtime boundary registry."""
    return list(DISTRIBUTED_RUNTIME_SURFACE_REGISTRY)


def classify_distributed_surface(
    surface_id: str,
) -> Optional[DistributedRuntimeSurface]:
    """Return the :class:`DistributedRuntimeSurface` for *surface_id*, or ``None``."""
    for surface in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY:
        if surface.surface_id == surface_id:
            return surface
    return None


def get_surfaces_by_distributed_role(
    role: DistributedRuntimeLayerRole,
) -> List[DistributedRuntimeSurface]:
    """Return all surfaces classified with *role*."""
    return [
        s for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.distributed_role == role
    ]


def build_distributed_runtime_boundary_report() -> DistributedRuntimeBoundaryReport:
    """Build and return a :class:`DistributedRuntimeBoundaryReport`."""
    total = len(DISTRIBUTED_RUNTIME_SURFACE_REGISTRY)
    main_chain = sum(
        1 for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.distributed_role
        == DistributedRuntimeLayerRole.distributed_runtime_main_chain
    )
    transport = sum(
        1 for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.distributed_role
        == DistributedRuntimeLayerRole.transport_relay_dispatch_layer
    )
    handoff = sum(
        1 for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.distributed_role
        == DistributedRuntimeLayerRole.handoff_takeover_prototype
    )
    projection = sum(
        1 for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.distributed_role
        == DistributedRuntimeLayerRole.projection_diagnostics_operator
    )
    android = sum(
        1 for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.distributed_role
        == DistributedRuntimeLayerRole.android_participation_runtime_node
    )
    constrained = [
        s.surface_id
        for s in DISTRIBUTED_RUNTIME_SURFACE_REGISTRY
        if s.may_not_claim_distributed_control_plane
    ]
    return DistributedRuntimeBoundaryReport(
        total_surfaces=total,
        main_chain_count=main_chain,
        transport_relay_count=transport,
        handoff_takeover_prototype_count=handoff,
        projection_diagnostics_count=projection,
        android_participation_count=android,
        constrained_surfaces=constrained,
        generated_at=time.time(),
    )
