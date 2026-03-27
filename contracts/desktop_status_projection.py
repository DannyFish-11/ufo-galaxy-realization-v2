"""contracts/desktop_status_projection.py
==========================================
Desktop Status Projection Contract — PR-22.

This module defines the **canonical shell-facing desktop status projection**:
a single, fully serialisable contract that the runtime shell uses as the
primary contract for desktop status board rendering.

It answers the operator-facing question:

    *"What is the system currently doing, and why?"*

Architecture
------------
This projection is **produced by the control core** (OpenClawd via
:class:`~core.schemas.unified_control_plan.UnifiedControlPlan`) and
**consumed by the runtime shell** (:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`).
The shell combines control-core outputs with shell-owned facts (source
registry state, lifecycle phase) through the stable projection contract
rather than ad hoc UI logic.

.. code-block:: text

    RUNTIME SHELL (DesktopPresenceRuntime)
      ├── shell-owned facts: source_registry snapshot, tristate lifecycle
      └── build_desktop_status_projection(unified_control_plan, source_registry)
                │                         ↑
                │               OPENCLAWD (control core)
                │               produces: UnifiedControlPlan
                ▼
          DesktopStatusProjection   ← canonical projection contract
            ├── PerceptionProjection      (ingress / modalities)
            ├── ModelRoutingProjection    (provider / model / route)
            ├── ExecutionProjection       (path / remote-mode / devices)
            ├── LifecycleProjection       (stage / health)
            └── ExplainabilityProjection  (fallback / degradation / diagnostics)

Design principles
-----------------
- **Projection, not re-inference** — the shell consumes a canonical projection
  contract rather than rebuilding state from scattered metadata.
- **Explainability first** — helps an operator understand not just *what* is
  happening but *why*.
- **Graceful degradation** — missing sources, unavailable providers, or
  degraded execution still produce a coherent projection with appropriate
  health/severity signals.
- **Serialisable and testable** — snapshots are suitable for diagnostics,
  regression tests, and later UI evolution.
- **Shell/core boundary preserved** — OpenClawd provides projection-ready
  structured state; the shell owns desktop UI rendering.
- **Additive only** — does not modify any existing module.

Contract chain consumed
-----------------------
- **PR-19** (:class:`~core.schemas.unified_control_plan.UnifiedControlPlan`)
- **PR-16** (:class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`)
- **PR-17** (:class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`)
- **PR-18** (:class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`)
- **PR-20** — native multimodal routing fields
- **PR-21** (:class:`~core.schemas.unified_control_plan.UnifiedExecutionDecision`,
  :class:`~core.schemas.unified_control_plan.FallbackDecisionRecord`)

Usage::

    from contracts.desktop_status_projection import (
        DesktopStatusProjection,
        build_desktop_status_projection,
        desktop_status_projection_summary,
    )

    # From a unified control plan dict (produced by OpenClawd) and an
    # optional source registry snapshot (owned by the runtime shell):
    projection = build_desktop_status_projection(
        unified_control_plan=plan_dict,
        source_registry_snapshot=registry_snapshot,
        tristate=tristate_value,
        runtime_session_id=session_id,
    )
    print(projection.to_json(indent=2))
    summary = desktop_status_projection_summary(projection)
"""

from __future__ import annotations

import json
import logging
import os as _env_os
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse as _urlparse

from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PR-5: Server-side canonicalization — legacy field demotion registry
# ---------------------------------------------------------------------------

#: Frozenset of top-level UCP keys that are retained as **legacy/compatibility
#: bridges only**.  Downstream consumers **must not** rely on these keys when a
#: ``topology_route_plan`` block is present in the UCP.
#:
#: Background (PR-5):
#: - PR-2 established ``TopologyRoutePlan`` as the sole canonical routing output.
#: - PR-3 added ``vendor_source``/``oneapi_source`` to ``ModelRoutingProjection``.
#: - PR-4 completed OneAPI lower-horizon cleanup (``oneapi_integration`` block).
#: - PR-5 (this PR) formalises the demotion of these scattered keys so that
#:   machine-checkable guardrails can enforce canonical-first consumption.
#:
#: The canonical routing authority is always
#: ``core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY``.
#: See ``docs/MODEL_ROUTING_AUTHORITY.md`` and
#: ``docs/SERVER_SIDE_CANONICALIZATION.md`` for the full demotion policy.
LEGACY_UCP_ROUTING_KEYS: frozenset = frozenset(
    {
        "chosen_model",
        "chosen_provider",
        "is_native_multimodal",
        "support_model_ids",
        "route_reason",
        "multimodal_route",
    }
)

#: Sentinel string placed in serialised projection outputs to identify this
#: module as the canonical projection contract authority (PR-5).
PROJECTION_CONTRACT_AUTHORITY: str = (
    "contracts.desktop_status_projection.DesktopStatusProjection"
)

#: PR-6: Sentinel string identifying the topology-ready projection delivery
#: block as a PR-6 canonical contract artefact.  Downstream desktop topology
#: surfaces should verify this sentinel to confirm the block was produced by
#: the canonical builder rather than assembled ad-hoc.
TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY: str = (
    "contracts.desktop_status_projection.DesktopTopologyProjection"
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProjectionHealthSeverity(str, Enum):
    """Overall health / alert severity of a projection block.

    ok
        All components are operating normally.
    advisory
        Minor advisory conditions; system is functional but a note exists.
    degraded
        One or more components are degraded; fallback path may be active.
    critical
        A critical condition has been detected; major capability unavailable.
    unknown
        Health cannot be determined from available context.
    """

    ok = "ok"
    advisory = "advisory"
    degraded = "degraded"
    critical = "critical"
    unknown = "unknown"


class LifecycleStage(str, Enum):
    """High-level lifecycle stage of the unified control loop.

    ingest
        System is ingesting/receiving the request.
    perceive
        Perception / canonicalisation of sensory inputs is in progress.
    route
        Model and execution routing decisions are being resolved.
    plan
        Execution plan is being constructed.
    delegate
        Execution has been delegated (local / cross-device / orchestration).
    run
        Active execution is in progress.
    succeed
        The lifecycle completed successfully.
    fail
        The lifecycle ended in failure.
    degrade
        A degradation or fallback occurred; system continued in reduced mode.
    idle
        System is idle / awaiting the next request (tristate: silent).
    unknown
        Stage cannot be determined.
    """

    ingest = "ingest"
    perceive = "perceive"
    route = "route"
    plan = "plan"
    delegate = "delegate"
    run = "run"
    succeed = "succeed"
    fail = "fail"
    degrade = "degrade"
    idle = "idle"
    unknown = "unknown"


class ExecutionPathKind(str, Enum):
    """Canonical execution path for a control-loop cycle.

    local
        Execution confined to the local device.
    cross_device
        Execution delegated to a single remote device.
    hybrid
        Local and remote execution combined (multi-device orchestration).
    none
        No execution path was taken (no-op / blocked).
    """

    local = "local"
    cross_device = "cross_device"
    hybrid = "hybrid"
    none = "none"


# ---------------------------------------------------------------------------
# Sub-contracts
# ---------------------------------------------------------------------------


class PerceptionProjection(BaseModel):
    """Perception / ingress state for the desktop status projection.

    Captures the current state of sensory input available to the system:
    whether continuous perception is active, which modalities are present,
    what the primary audio/video sources are, and the overall source health.

    All fields are optional so that a text-only projection is always valid.

    Fields
    ------
    continuous_perception_active
        Whether the native multimodal ingress bus is currently running.
    request_multimodal_present
        Whether the current or last request carried a multimodal payload.
    active_modalities
        List of modality labels currently active (e.g. ``["audio", "video"]``).
    primary_audio_source_id
        ID of the currently selected primary audio source.
    primary_audio_source_type
        Type label of the primary audio source (e.g. ``"microphone"``).
    primary_video_source_id
        ID of the currently selected primary video source.
    primary_video_source_type
        Type label of the primary video source (e.g. ``"webcam"``, ``"webrtc"``).
    source_health_summary
        Overall health summary string for the source registry.
    source_count
        Total number of registered perception sources.
    active_source_count
        Number of sources currently marked active.
    health_severity
        Aggregated health severity derived from source states.
    """

    continuous_perception_active: bool = Field(
        default=False,
        description="Whether the native multimodal ingress bus is running.",
    )
    request_multimodal_present: bool = Field(
        default=False,
        description="Whether the current/last request carried a multimodal payload.",
    )
    active_modalities: List[str] = Field(
        default_factory=list,
        description="Modality labels currently active (e.g. ['audio', 'video']).",
    )
    primary_audio_source_id: Optional[str] = Field(
        default=None,
        description="ID of the currently selected primary audio source.",
    )
    primary_audio_source_type: Optional[str] = Field(
        default=None,
        description="Type label of the primary audio source.",
    )
    primary_video_source_id: Optional[str] = Field(
        default=None,
        description="ID of the currently selected primary video source.",
    )
    primary_video_source_type: Optional[str] = Field(
        default=None,
        description="Type label of the primary video source.",
    )
    source_health_summary: Optional[str] = Field(
        default=None,
        description="Overall health summary string for the source registry.",
    )
    source_count: int = Field(
        default=0,
        description="Total number of registered perception sources.",
    )
    active_source_count: int = Field(
        default=0,
        description="Number of sources currently marked active.",
    )
    health_severity: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.unknown,
        description="Aggregated health severity derived from source states.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())


class ModelRoutingProjection(BaseModel):
    """Model / routing state for the desktop status projection.

    Captures the currently selected provider, model, native multimodal
    status, and route rationale — enabling operators to understand which
    model is active and why.

    Fields
    ------
    selected_provider
        Canonical provider identifier (e.g. ``"openai"``, ``"anthropic"``).
    selected_model
        Canonical model identifier (e.g. ``"gpt-4o"``, ``"claude-3-5-sonnet"``).
    is_native_multimodal
        Whether the selected route is a native multimodal path.
    support_model_hints
        Auxiliary / support model hints from the control plan.
    route_reason
        Human-readable explanation of the current routing decision.
    route_summary
        Compact structured routing summary for display purposes.
    vendor_source
        Vendor category of the selected primary model node:
        ``"direct"`` for top-layer direct/native providers,
        ``"oneapi"`` for OneAPI aggregator entries,
        ``"local"`` for local/embedded models, etc.
        Populated from the canonical ``TopologyRoutePlan`` node's
        ``vendor_source`` field; ``None`` on legacy path.
    oneapi_source
        Summary dict describing OneAPI's integration position when the
        selected route routes *through* OneAPI
        (i.e. ``vendor_source == "oneapi"``).  ``None`` when the selected
        route is NOT through OneAPI.  For the always-present lower-horizon
        OneAPI block, see :attr:`DesktopStatusProjection.oneapi_integration`
        (PR-4).  The ``oneapi_source`` field here must never be used to
        represent a top-layer provider peer.
    provider_available
        Whether the selected provider is currently available.
    health_severity
        Health severity for the model/routing block.
    routing_authority_source
        Identifies which source populated the routing fields.
        ``"topology_router"`` — fields sourced from a canonical
        ``TopologyRoutePlan`` (``ucp["topology_route_plan"]`` block).
        ``"legacy_ucp_keys"`` — fields assembled from legacy/compat UCP
        keys (``chosen_model``, ``chosen_provider``, ``multimodal_route``).
        ``"none"`` — no routing data was available.
        Consumers should prefer ``"topology_router"`` as the canonical source.
    legacy_routing_fallback_active
        PR-5 canonicalization flag.  ``True`` when routing fields were
        assembled from legacy/compat UCP keys (``routing_authority_source
        == "legacy_ucp_keys"``).  Downstream consumers should treat such a
        projection as degraded and prefer canonical ``TopologyRoutePlan``
        data when available.  ``False`` on the canonical topology-router
        path.  See :data:`LEGACY_UCP_ROUTING_KEYS` and
        ``docs/SERVER_SIDE_CANONICALIZATION.md``.
    """

    selected_provider: Optional[str] = Field(
        default=None,
        description="Canonical provider identifier for the selected route.",
    )
    selected_model: Optional[str] = Field(
        default=None,
        description="Canonical model identifier for the selected route.",
    )
    is_native_multimodal: bool = Field(
        default=False,
        description="Whether the selected route uses native multimodal APIs.",
    )
    support_model_hints: List[str] = Field(
        default_factory=list,
        description="Auxiliary/support model IDs hinted by the control plan.",
    )
    route_reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the current routing decision.",
    )
    route_summary: Optional[str] = Field(
        default=None,
        description="Compact structured routing summary for display.",
    )
    vendor_source: Optional[str] = Field(
        default=None,
        description=(
            "Vendor category of the selected primary model node "
            "('direct', 'oneapi', 'local', …).  Populated from the "
            "canonical TopologyRoutePlan; None on legacy path."
        ),
    )
    oneapi_source: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "OneAPI integration position summary when the selected route "
            "uses OneAPI (vendor_source == 'oneapi').  None otherwise.  "
            "Note: for the always-present lower-horizon OneAPI block, see "
            "DesktopStatusProjection.oneapi_integration (PR-4)."
        ),
    )
    provider_available: bool = Field(
        default=True,
        description="Whether the selected provider is currently available.",
    )
    health_severity: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.unknown,
        description="Health severity for the model/routing block.",
    )
    routing_authority_source: str = Field(
        default="none",
        description=(
            "Identifies which source populated the routing fields. "
            "'topology_router' = canonical TopologyRoutePlan path; "
            "'legacy_ucp_keys' = legacy/compat UCP keys; "
            "'none' = no routing data available."
        ),
    )
    legacy_routing_fallback_active: bool = Field(
        default=False,
        description=(
            "PR-5 canonicalization flag.  True when routing fields were "
            "assembled from legacy/compat UCP keys (routing_authority_source "
            "== 'legacy_ucp_keys') rather than the canonical "
            "TopologyRoutePlan.  Downstream consumers should treat this "
            "projection as degraded and prefer to source routing data from "
            "a canonical TopologyRoutePlan when possible.  "
            "See LEGACY_UCP_ROUTING_KEYS and docs/SERVER_SIDE_CANONICALIZATION.md."
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())


class ExecutionProjection(BaseModel):
    """Execution path and remote-mode state for the desktop status projection.

    Captures the current execution path, remote execution mode where
    applicable, target devices, and orchestration status — giving operators
    a clear view of *where* the system is executing.

    Fields
    ------
    execution_path
        Canonical execution path taken (local / cross_device / hybrid / none).
    remote_execution_mode
        Remote execution mode when execution_path is cross_device or hybrid:
        ``"command_only"`` or ``"agent_runtime"``.
    target_device_ids
        IDs of devices targeted for execution.
    orchestration_active
        Whether multi-device orchestration is active for this request.
    delegation_point
        Delegation boundary label from the control plan.
    execution_reason
        Human-readable rationale for the chosen execution path.
    health_severity
        Health severity for the execution block.
    """

    execution_path: ExecutionPathKind = Field(
        default=ExecutionPathKind.none,
        description="Canonical execution path taken.",
    )
    remote_execution_mode: Optional[str] = Field(
        default=None,
        description="Remote execution mode (command_only / agent_runtime).",
    )
    target_device_ids: List[str] = Field(
        default_factory=list,
        description="IDs of devices targeted for execution.",
    )
    orchestration_active: bool = Field(
        default=False,
        description="Whether multi-device orchestration is active.",
    )
    delegation_point: Optional[str] = Field(
        default=None,
        description="Delegation boundary label from the control plan.",
    )
    execution_reason: Optional[str] = Field(
        default=None,
        description="Rationale for the chosen execution path.",
    )
    health_severity: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.unknown,
        description="Health severity for the execution block.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())


class LifecycleProjection(BaseModel):
    """Lifecycle stage and health for the desktop status projection.

    Captures where the system is in its current lifecycle and its overall
    health status, providing operators with a clear, single-glance summary.

    Fields
    ------
    stage
        High-level lifecycle stage (ingest / perceive / route / plan /
        delegate / run / succeed / fail / degrade / idle).
    tristate
        Subject tri-state value from the runtime shell
        (``"silent"`` / ``"liminal"`` / ``"manifest"``).
    lifecycle_target
        Intended lifecycle target string from the control plan
        (e.g. ``"succeeded"``, ``"failed"``, ``"degraded"``).
    health_severity
        Overall health severity for the lifecycle block.
    decision_authority
        Canonical decision authority role from the control plan.
    """

    stage: LifecycleStage = Field(
        default=LifecycleStage.unknown,
        description="High-level lifecycle stage of the control loop.",
    )
    tristate: Optional[str] = Field(
        default=None,
        description="Subject tri-state from the runtime shell (silent/liminal/manifest).",
    )
    lifecycle_target: Optional[str] = Field(
        default=None,
        description="Intended lifecycle target from the control plan.",
    )
    health_severity: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.unknown,
        description="Overall health severity for the lifecycle block.",
    )
    decision_authority: Optional[str] = Field(
        default=None,
        description="Canonical decision authority role from the control plan.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())


class ExplainabilityProjection(BaseModel):
    """Fallback, degradation, and diagnostics state for the desktop status projection.

    Provides operators with an explanation of *why* the system is behaving
    as it is — surfacing fallback reasons, degradation details, and a
    diagnostics summary in a coherent, human-readable form.

    Fields
    ------
    has_fallback
        Whether any fallback or downgrade occurred in this cycle.
    fallback_kinds
        List of fallback kind labels (e.g. ``["native_multimodal_to_text"]``).
    fallback_reasons
        Human-readable reasons for each fallback/downgrade.
    degradation_summary
        Compact summary of all degradation events in this cycle.
    diagnostics_summary
        Diagnostics snapshot dict from the control plan.
    authority_chain_clear
        Whether the authority chain in the control plan is unambiguous.
    source_warnings
        Warnings about source/provider/capability availability.
    health_severity
        Health severity for the explainability block.
    """

    has_fallback: bool = Field(
        default=False,
        description="Whether any fallback or downgrade occurred.",
    )
    fallback_kinds: List[str] = Field(
        default_factory=list,
        description="List of fallback kind labels.",
    )
    fallback_reasons: List[str] = Field(
        default_factory=list,
        description="Human-readable reasons for each fallback/downgrade.",
    )
    degradation_summary: Optional[str] = Field(
        default=None,
        description="Compact summary of all degradation events.",
    )
    diagnostics_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Diagnostics snapshot dict from the control plan.",
    )
    authority_chain_clear: bool = Field(
        default=True,
        description="Whether the authority chain in the control plan is unambiguous.",
    )
    source_warnings: List[str] = Field(
        default_factory=list,
        description="Warnings about source/provider/capability availability.",
    )
    health_severity: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.ok,
        description="Health severity for the explainability block.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())


# ---------------------------------------------------------------------------
# PR-6: DesktopTopologyProjection — topology-ready block
# ---------------------------------------------------------------------------


class DesktopTopologyProjection(BaseModel):
    """PR-6: Topology-ready projection block for desktop constellation/status-board surfaces.

    A single structured block designed for desktop topology surface consumption.
    Derived exclusively from canonical sources (``TopologyRoutePlan`` when
    available; legacy fallback explicitly marked and degraded).

    This block is **renderer-agnostic**: it contains no display coordinates,
    colours, pixel positions, or animation hints.  The visualisation grammar
    belongs to the rendering layer (e.g. ``windows_client/status_board_v2/``).

    A desktop topology surface consumes this block to understand:

    - Which model is the primary routed model
    - Which models are support/auxiliary
    - Provider identity and availability status
    - Route reason, phase, and domain when available
    - Whether canonical routing or legacy fallback was used
    - The OneAPI lower-horizon integration position (as a separate block)

    Architectural constraints
    -------------------------
    - ``oneapi_integration`` is a **lower-horizon** block only.  It must never
      be promoted to a top-layer provider peer.
    - ``legacy_fallback_active == True`` signals a degraded routing projection;
      the topology surface should surface this status to the operator.
    - ``contract_authority`` is a machine-checkable sentinel confirming this
      block was produced by the canonical builder.

    Fields
    ------
    primary_model_id
        Canonical model identifier for the primary route.
    primary_provider_id
        Canonical provider identifier for the primary route.
    primary_vendor_source
        Vendor category of the primary route (``"direct"``, ``"oneapi"``,
        ``"local"``, …).
    primary_is_native_multimodal
        Whether the primary route uses native multimodal APIs.
    support_model_ids
        Ordered list of support/auxiliary model identifiers.
    route_reason
        Human-readable explanation of the current routing decision.
    route_phase
        Active routing phase (e.g. ``"liminal"``, ``"manifest"``,
        ``"silent"``).
    route_domain
        Active routing domain (e.g. ``"local"``, ``"cross_device"``).
    primary_provider_available
        Whether the primary provider is currently available.
    routing_authority_source
        ``"topology_router"`` when sourced from canonical
        ``TopologyRoutePlan``; ``"legacy_ucp_keys"`` when sourced from
        legacy UCP keys; ``"none"`` when no routing data was available.
    canonical_source_present
        ``True`` when a canonical ``TopologyRoutePlan`` was the routing
        source for this block.
    legacy_fallback_active
        ``True`` when routing was assembled from legacy/compat UCP keys
        rather than a canonical ``TopologyRoutePlan``.  Downstream
        consumers should treat this topology block as degraded.
    oneapi_integration
        Lower-horizon OneAPI integration block (always present as a
        separate integration block, never promoted to top-layer peer).
        Contains at minimum: ``system_layer``, ``configured``, ``health``,
        ``base_url_hint``, ``model_count``, ``gateway_identity``.
    health_severity
        Aggregated health severity for this topology block.
    contract_authority
        Machine-checkable sentinel identifying this block as a PR-6
        topology-ready contract artefact produced by
        :func:`build_desktop_status_projection`.
    """

    primary_model_id: Optional[str] = Field(
        default=None,
        description="Canonical model identifier for the primary route.",
    )
    primary_provider_id: Optional[str] = Field(
        default=None,
        description="Canonical provider identifier for the primary route.",
    )
    primary_vendor_source: Optional[str] = Field(
        default=None,
        description=(
            "Vendor category of the primary route ('direct', 'oneapi', 'local', …). "
            "Populated from the canonical TopologyRoutePlan; None on legacy path."
        ),
    )
    primary_is_native_multimodal: bool = Field(
        default=False,
        description="Whether the primary route uses native multimodal APIs.",
    )
    support_model_ids: List[str] = Field(
        default_factory=list,
        description="Ordered list of support/auxiliary model identifiers.",
    )
    route_reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the current routing decision.",
    )
    route_phase: Optional[str] = Field(
        default=None,
        description="Active routing phase ('liminal', 'manifest', 'silent', …).",
    )
    route_domain: Optional[str] = Field(
        default=None,
        description="Active routing domain ('local', 'cross_device', …).",
    )
    primary_provider_available: bool = Field(
        default=True,
        description="Whether the primary provider is currently available.",
    )
    routing_authority_source: str = Field(
        default="none",
        description=(
            "Identifies which source populated the routing fields. "
            "'topology_router' = canonical TopologyRoutePlan path; "
            "'legacy_ucp_keys' = legacy/compat UCP keys; "
            "'none' = no routing data available."
        ),
    )
    canonical_source_present: bool = Field(
        default=False,
        description="True when a canonical TopologyRoutePlan was the routing source.",
    )
    legacy_fallback_active: bool = Field(
        default=False,
        description=(
            "True when routing was assembled from legacy/compat UCP keys rather than "
            "a canonical TopologyRoutePlan.  Downstream consumers should treat this "
            "topology block as degraded.  See LEGACY_UCP_ROUTING_KEYS and "
            "docs/SERVER_SIDE_CANONICALIZATION.md."
        ),
    )
    oneapi_integration: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "PR-4/PR-6 lower-horizon OneAPI integration block (always present as a "
            "separate block; never promoted to top-layer provider peer). "
            "Contains at minimum: system_layer, configured, health, base_url_hint, "
            "model_count, gateway_identity."
        ),
    )
    health_severity: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.unknown,
        description="Aggregated health severity for this topology block.",
    )
    contract_authority: str = Field(
        default=TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
        description=(
            "Machine-checkable sentinel identifying this block as a PR-6 "
            "topology-ready contract artefact produced by the canonical builder."
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())


# ---------------------------------------------------------------------------
# Top-level DesktopStatusProjection
# ---------------------------------------------------------------------------


class DesktopStatusProjection(BaseModel):
    """Canonical shell-facing desktop status projection — PR-22, extended PR-4, PR-6.

    A single, fully serialisable contract that the runtime shell uses as the
    primary contract for desktop status board rendering.

    This is the **top-level projection object** that aggregates all major
    control-loop dimensions into one coherent, operator-facing view:

    - **perception** — what the system is currently sensing
    - **model_routing** — which model/provider is selected and why
    - **execution** — which execution path is active and where
    - **lifecycle** — where in the lifecycle the system is
    - **explainability** — fallback/degradation reasons and diagnostics
    - **topology_ready** — PR-6 single structured block for desktop topology
      surface consumption (renderer-agnostic, canonical sources first)

    Produced by :func:`build_desktop_status_projection` from a
    :class:`~core.schemas.unified_control_plan.UnifiedControlPlan` dict
    (control-core output) combined with shell-owned source registry state.

    Fields
    ------
    projection_id
        Unique identifier for this projection instance.
    runtime_session_id
        Correlation ID linking this projection to the active runtime session.
    projected_at
        Unix epoch seconds when this projection was assembled.
    perception
        Perception / ingress state block.
    model_routing
        Model / routing state block.
    execution
        Execution path and remote-mode state block.
    lifecycle
        Lifecycle stage and health block.
    explainability
        Fallback, degradation, and diagnostics block.
    oneapi_integration
        PR-4 distinct lower-horizon OneAPI aggregator integration block.
        Always present (even when OneAPI is not configured) as a separate
        block intended for lower-horizon-only rendering.  Contains at
        minimum: ``system_layer``, ``configured``, ``health``,
        ``base_url_hint``, ``model_count``, ``gateway_identity``.
        **This block must never be merged into the top-layer provider list
        or route-plan primary/support fields.**
    topology_ready
        PR-6 topology-ready projection block for desktop constellation/
        status-board surfaces.  A single structured block derived from
        canonical sources (``TopologyRoutePlan`` first; legacy fallback
        explicitly marked).  Renderer-agnostic.  Desktop topology surfaces
        should consume this block rather than reconstructing routing truth
        from legacy keys or dashboard-era summaries.
    overall_health
        Rolled-up overall health severity across all blocks.
    schema_version
        Schema version for forward-compatibility tracking.
    """

    projection_id: str = Field(
        default_factory=lambda: f"dsp_{uuid.uuid4().hex[:12]}",
        description="Unique identifier for this projection instance.",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Correlation ID linking this projection to the active runtime session.",
    )
    projected_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this projection was assembled.",
    )
    perception: PerceptionProjection = Field(
        default_factory=PerceptionProjection,
        description="Perception / ingress state block.",
    )
    model_routing: ModelRoutingProjection = Field(
        default_factory=ModelRoutingProjection,
        description="Model / routing state block.",
    )
    execution: ExecutionProjection = Field(
        default_factory=ExecutionProjection,
        description="Execution path and remote-mode state block.",
    )
    lifecycle: LifecycleProjection = Field(
        default_factory=LifecycleProjection,
        description="Lifecycle stage and health block.",
    )
    explainability: ExplainabilityProjection = Field(
        default_factory=ExplainabilityProjection,
        description="Fallback, degradation, and diagnostics block.",
    )
    oneapi_integration: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "PR-4 distinct lower-horizon OneAPI aggregator integration block. "
            "Always present as a separate block for lower-horizon-only "
            "rendering.  Must never be merged into the top-layer provider "
            "list or route-plan primary/support fields."
        ),
    )
    topology_ready: Optional["DesktopTopologyProjection"] = Field(
        default=None,
        description=(
            "PR-6 topology-ready projection block for desktop constellation/status-board "
            "surfaces.  A single structured block derived from canonical sources "
            "(TopologyRoutePlan first; legacy fallback explicitly marked and degraded).  "
            "Renderer-agnostic: contains no display coordinates, colours, pixel positions, "
            "or animation hints.  Desktop topology surfaces should consume this block "
            "rather than reconstructing routing truth from legacy keys or dashboard-era "
            "summaries.  OneAPI remains a separate lower-horizon integration block inside "
            "this structure."
        ),
    )
    overall_health: ProjectionHealthSeverity = Field(
        default=ProjectionHealthSeverity.unknown,
        description="Rolled-up overall health severity across all blocks.",
    )
    schema_version: str = Field(
        default="1.0",
        description="Schema version for forward-compatibility tracking.",
    )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesktopStatusProjection":
        """Construct from a dict (round-trip from to_dict)."""
        try:
            return cls.model_validate(data)
        except Exception as err:
            _logger.warning("DesktopStatusProjection.from_dict failed: %s", err)
            return cls()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_oneapi_source_summary() -> Dict[str, Any]:
    """Return a compact OneAPI integration position summary dict.

    Pulls from :func:`~core.oneapi_system_position.build_oneapi_integration_summary`
    when available; falls back to a minimal static dict on import error.
    This function is intentionally cheap to call (no I/O).
    """
    try:
        from core.oneapi_system_position import build_oneapi_integration_summary
        snapshot = build_oneapi_integration_summary()
        return snapshot.to_dict()
    except Exception:
        return {
            "system_layer": "aggregator_integration",
            "provider_category_value": "oneapi",
            "routing_authority_ref": (
                "core.model_topology.topology_router.TopologyRouter"
            ),
        }


def _safe_str(value: object, default: Optional[str] = None) -> Optional[str]:
    """Return a string from *value* or *default*."""
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def _safe_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def _safe_list(value: object) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _safe_dict(value: object) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _severity_from_str(value: Optional[str]) -> ProjectionHealthSeverity:
    if not value:
        return ProjectionHealthSeverity.unknown
    try:
        return ProjectionHealthSeverity(value.lower())
    except ValueError:
        return ProjectionHealthSeverity.unknown


def _rolled_up_severity(severities: List[ProjectionHealthSeverity]) -> ProjectionHealthSeverity:
    """Return the worst severity from a list."""
    _order = [
        ProjectionHealthSeverity.critical,
        ProjectionHealthSeverity.degraded,
        ProjectionHealthSeverity.advisory,
        ProjectionHealthSeverity.ok,
        ProjectionHealthSeverity.unknown,
    ]
    for sev in _order:
        if sev in severities:
            return sev
    return ProjectionHealthSeverity.unknown


def _lifecycle_stage_from_plan(ucp: Dict[str, Any], tristate: Optional[str]) -> LifecycleStage:
    """Derive a LifecycleStage from the unified control plan and tri-state."""
    lifecycle_target = _safe_str(ucp.get("lifecycle_target"))
    fallback_level = _safe_str(ucp.get("fallback_level"), "none")
    _ced = ucp.get("chosen_execution_decision")
    exec_path = _safe_str(_ced.get("execution_path") if isinstance(_ced, dict) else None, "")
    has_fallback = False
    fdr = ucp.get("fallback_decision_record")
    if isinstance(fdr, dict):
        has_fallback = _safe_bool(fdr.get("has_fallback"), False)
    if not has_fallback and fallback_level and fallback_level not in ("none", ""):
        has_fallback = True

    if tristate == "silent":
        if lifecycle_target in ("succeeded", "success"):
            return LifecycleStage.succeed
        if lifecycle_target in ("failed", "failure", "error"):
            return LifecycleStage.fail
        if has_fallback:
            return LifecycleStage.degrade
        return LifecycleStage.idle

    if tristate == "liminal":
        if lifecycle_target in ("routing", "route"):
            return LifecycleStage.route
        if lifecycle_target in ("planning", "plan"):
            return LifecycleStage.plan
        return LifecycleStage.perceive

    if tristate == "manifest":
        if exec_path and exec_path not in ("none", ""):
            return LifecycleStage.run
        return LifecycleStage.delegate

    if lifecycle_target in ("succeeded", "success"):
        return LifecycleStage.succeed
    if lifecycle_target in ("failed", "failure", "error"):
        return LifecycleStage.fail
    if has_fallback:
        return LifecycleStage.degrade
    return LifecycleStage.unknown


# ---------------------------------------------------------------------------
# Sub-contract builders
# ---------------------------------------------------------------------------


def _build_perception_projection(
    ucp: Dict[str, Any],
    source_registry_snapshot: Optional[Dict[str, Any]],
) -> PerceptionProjection:
    """Build the perception sub-projection from control plan and source registry."""
    # Extract canonical perception state from the unified control plan.
    cp = _safe_dict(ucp.get("canonical_perception"))
    active_modalities: List[str] = _safe_list(cp.get("active_modalities"))
    request_multimodal_present: bool = _safe_bool(cp.get("has_multimodal_input") or cp.get("requires_native_multimodal"))

    # If the UCP carries a multimodal_route block, use it as additional signal.
    mm_route = _safe_dict(ucp.get("multimodal_route"))
    if mm_route and not active_modalities:
        active_modalities = _safe_list(mm_route.get("active_modalities"))

    # Determine continuous perception from source registry.
    continuous_perception_active: bool = False
    primary_audio_id: Optional[str] = None
    primary_audio_type: Optional[str] = None
    primary_video_id: Optional[str] = None
    primary_video_type: Optional[str] = None
    source_count: int = 0
    active_source_count: int = 0
    source_health_summary: Optional[str] = None
    source_health_sev = ProjectionHealthSeverity.unknown

    if isinstance(source_registry_snapshot, dict):
        sources: List[Dict[str, Any]] = _safe_list(source_registry_snapshot.get("sources"))
        source_count = len(sources)
        active_sources = [s for s in sources if _safe_bool(s.get("is_active"))]
        active_source_count = len(active_sources)
        continuous_perception_active = active_source_count > 0

        # Find primary audio and video sources.
        for src in sources:
            if _safe_bool(src.get("is_primary_audio")) and primary_audio_id is None:
                primary_audio_id = _safe_str(src.get("source_id"))
                primary_audio_type = _safe_str(src.get("source_type"))
            if _safe_bool(src.get("is_primary_video")) and primary_video_id is None:
                primary_video_id = _safe_str(src.get("source_id"))
                primary_video_type = _safe_str(src.get("source_type"))

        # Derive health from sources.
        health_values = [_safe_str(s.get("health_status"), "unknown") for s in sources]
        if any(h == "unavailable" for h in health_values):
            source_health_sev = ProjectionHealthSeverity.degraded
            source_health_summary = "One or more sources unavailable"
        elif any(h == "degraded" for h in health_values):
            source_health_sev = ProjectionHealthSeverity.advisory
            source_health_summary = "One or more sources degraded"
        elif all(h == "healthy" for h in health_values) and health_values:
            source_health_sev = ProjectionHealthSeverity.ok
            source_health_summary = "All sources healthy"
        elif not health_values:
            source_health_sev = ProjectionHealthSeverity.ok
            source_health_summary = "No sources registered"
        else:
            source_health_sev = ProjectionHealthSeverity.unknown
            source_health_summary = "Source health unknown"

    # Active modalities from source registry if not already populated.
    if not active_modalities and isinstance(source_registry_snapshot, dict):
        sources_list: List[Dict[str, Any]] = _safe_list(source_registry_snapshot.get("sources"))
        mods: List[str] = []
        for src in sources_list:
            if _safe_bool(src.get("is_active")):
                modality = _safe_str(src.get("modality"))
                if modality and modality not in mods:
                    mods.append(modality)
        active_modalities = mods

    return PerceptionProjection(
        continuous_perception_active=continuous_perception_active,
        request_multimodal_present=request_multimodal_present,
        active_modalities=active_modalities,
        primary_audio_source_id=primary_audio_id,
        primary_audio_source_type=primary_audio_type,
        primary_video_source_id=primary_video_id,
        primary_video_source_type=primary_video_type,
        source_health_summary=source_health_summary,
        source_count=source_count,
        active_source_count=active_source_count,
        health_severity=source_health_sev,
    )


def _build_model_routing_projection(ucp: Dict[str, Any]) -> ModelRoutingProjection:
    """Build the model/routing sub-projection from the unified control plan.

    Source priority (highest to lowest):

    1. **CANONICAL** — ``ucp["topology_route_plan"]`` block
       (``TopologyRoutePlan.to_dict()`` output from
       ``core.model_topology.topology_router.TopologyRouter``).
       When present, *all* routing fields are read from this block and
       ``routing_authority_source`` is set to ``"topology_router"``.
       Extracts ``vendor_source`` and ``provider_id`` from the primary
       model node dict (PR-2 fields).  When ``vendor_source == "oneapi"``,
       populates ``oneapi_source`` with the canonical integration summary.
       ``legacy_routing_fallback_active`` is ``False`` on this path.

    2. **LEGACY COMPAT ONLY** — top-level UCP keys (``chosen_model``,
       ``chosen_provider``, ``is_native_multimodal``, ``support_model_ids``,
       ``route_reason``) and the ``multimodal_route`` block (PR-20).
       ``routing_authority_source`` is set to ``"legacy_ucp_keys"`` and
       ``legacy_routing_fallback_active`` is set to ``True`` (PR-5).
       These keys are listed in :data:`LEGACY_UCP_ROUTING_KEYS`.
       Downstream consumers **must not** treat these as canonical truth.

    Consumers should inspect ``routing_authority_source`` to understand which
    path was taken.  The canonical path (``"topology_router"``) is **always**
    preferred.  ``legacy_routing_fallback_active == True`` indicates the
    projection is in degraded / compatibility mode for routing fields.
    See ``docs/SERVER_SIDE_CANONICALIZATION.md`` for the PR-5 policy.
    """
    routing_authority_source = "none"
    chosen_model: Optional[str] = None
    chosen_provider: Optional[str] = None
    is_native_mm: bool = False
    support_model_hints: List[str] = []
    route_reason: Optional[str] = None
    vendor_source: Optional[str] = None
    oneapi_source: Optional[Dict[str, Any]] = None

    # -----------------------------------------------------------------------
    # CANONICAL PATH: topology_route_plan (TopologyRoutePlan.to_dict() output)
    # Use key-presence check so that an empty topology_route_plan dict still
    # activates the canonical path (it means "topology router ran, no routes").
    # -----------------------------------------------------------------------
    if "topology_route_plan" in ucp:
        routing_authority_source = "topology_router"
        topology_plan = _safe_dict(ucp["topology_route_plan"])
        primary = _safe_dict(topology_plan.get("primary_model"))
        if primary:
            chosen_model = _safe_str(primary.get("model_id"))
            is_native_mm = _safe_bool(primary.get("native_multimodal"))
            # provider_id and vendor_source are PR-2 canonical node fields.
            chosen_provider = _safe_str(primary.get("provider_id"))
            vendor_source = _safe_str(primary.get("vendor_source"))
        support_nodes = _safe_list(topology_plan.get("support_models"))
        support_model_hints = [
            _safe_str(s.get("model_id"))
            for s in support_nodes
            if isinstance(s, dict) and _safe_str(s.get("model_id"))
        ]
        route_reason = _safe_str(topology_plan.get("route_reason"))

        # When the selected provider is OneAPI, include the canonical
        # OneAPI integration position summary.
        if vendor_source == "oneapi":
            oneapi_source = _extract_oneapi_source_summary()

    else:
        # -------------------------------------------------------------------
        # LEGACY COMPAT PATH — top-level UCP keys and multimodal_route block
        # These paths are compatibility bridges only and must not be treated
        # as canonical routing authority.  See docs/MODEL_ROUTING_AUTHORITY.md
        # -------------------------------------------------------------------
        chosen_model = _safe_str(ucp.get("chosen_model"))
        chosen_provider = _safe_str(ucp.get("chosen_provider"))
        is_native_mm = _safe_bool(ucp.get("is_native_multimodal"))

        # Support model hints — from support_model_ids in the plan.
        support_model_hints = _safe_list(ucp.get("support_model_ids"))

        route_reason = _safe_str(ucp.get("route_reason"))

        # Try to get a richer route reason from the multimodal_route block (PR-20).
        mm_route = _safe_dict(ucp.get("multimodal_route"))
        if mm_route:
            if not route_reason:
                route_reason = _safe_str(mm_route.get("route_reason"))
            if not is_native_mm:
                is_native_mm = _safe_bool(mm_route.get("is_native_multimodal"))
            if not chosen_model:
                chosen_model = _safe_str(mm_route.get("selected_model"))
            if not chosen_provider:
                chosen_provider = _safe_str(mm_route.get("selected_provider"))

        if chosen_model or chosen_provider or route_reason:
            routing_authority_source = "legacy_ucp_keys"

    # If oneapi_source was not set from the canonical path, check whether the
    # UCP carries an explicit oneapi_summary block (e.g. from enriched plans).
    # Use explicit None check to avoid treating an empty dict as falsy.
    if oneapi_source is None:
        _ucp_oneapi = ucp.get("oneapi_summary") or ucp.get("oneapi_source")
        if isinstance(_ucp_oneapi, dict) and _ucp_oneapi:
            oneapi_source = _ucp_oneapi

    # Build a compact route summary for display.
    route_summary: Optional[str] = None
    if chosen_provider and chosen_model:
        mm_flag = " [native-MM]" if is_native_mm else ""
        vs_flag = f" [{vendor_source}]" if vendor_source and vendor_source != "direct" else ""
        route_summary = f"{chosen_provider}/{chosen_model}{mm_flag}{vs_flag}"

    # Determine provider availability from model supply state if embedded.
    provider_available = True
    model_supply = _safe_dict(ucp.get("canonical_model_supply"))
    if model_supply:
        provider_records = _safe_list(model_supply.get("providers"))
        if provider_records and chosen_provider:
            for rec in provider_records:
                if _safe_str(rec.get("provider_id")) == chosen_provider:
                    health = _safe_str(rec.get("health_status"), "healthy")
                    if health in ("unavailable", "error"):
                        provider_available = False
                    break

    # Health severity for routing block.
    if not chosen_model and not chosen_provider:
        sev = ProjectionHealthSeverity.unknown
    elif not provider_available:
        sev = ProjectionHealthSeverity.critical
    else:
        sev = ProjectionHealthSeverity.ok

    return ModelRoutingProjection(
        selected_provider=chosen_provider,
        selected_model=chosen_model,
        is_native_multimodal=is_native_mm,
        support_model_hints=support_model_hints,
        route_reason=route_reason,
        route_summary=route_summary,
        vendor_source=vendor_source,
        oneapi_source=oneapi_source,
        provider_available=provider_available,
        health_severity=sev,
        routing_authority_source=routing_authority_source,
        # PR-5: flag legacy path for downstream consumers to detect degraded routing.
        legacy_routing_fallback_active=(routing_authority_source == "legacy_ucp_keys"),
    )


def _build_execution_projection(ucp: Dict[str, Any]) -> ExecutionProjection:
    """Build the execution sub-projection from the unified control plan."""
    # Primary source: UnifiedExecutionDecision (PR-21).
    ued = _safe_dict(ucp.get("unified_execution_decision"))
    exec_path_str: str = _safe_str(ued.get("execution_path") if ued else None, "")
    remote_mode: Optional[str] = _safe_str(ued.get("remote_execution_mode") if ued else None)
    target_device_ids: List[str] = _safe_list(ued.get("target_device_ids") if ued else [])
    orchestration_active: bool = _safe_bool(ued.get("orchestration_active") if ued else False)
    exec_reason: Optional[str] = _safe_str(ued.get("execution_reason") if ued else None)
    delegation_point: Optional[str] = _safe_str(ued.get("delegation_point") if ued else None)

    # Fallback: try the legacy ChosenExecutionDecision block.
    if not exec_path_str:
        ced = _safe_dict(ucp.get("chosen_execution_decision"))
        exec_path_str = _safe_str(ced.get("execution_path") if ced else None, "none")
        if not remote_mode:
            remote_mode = _safe_str(ced.get("remote_execution_mode") if ced else None)
        if not target_device_ids:
            target_device_ids = _safe_list(ced.get("target_device_ids") if ced else [])
        if not orchestration_active:
            orchestration_active = _safe_bool(ced.get("orchestration_active") if ced else False)
        if not delegation_point:
            delegation_point = _safe_str(ced.get("delegation_point") if ced else None)

    # Normalise execution path to enum.
    try:
        exec_path = ExecutionPathKind(exec_path_str)
    except ValueError:
        exec_path = ExecutionPathKind.none

    # Health severity.
    fdr = _safe_dict(ucp.get("fallback_decision_record"))
    has_exec_fallback = _safe_bool(fdr.get("has_fallback") if fdr else False)
    if has_exec_fallback:
        sev = ProjectionHealthSeverity.degraded
    elif exec_path == ExecutionPathKind.none:
        sev = ProjectionHealthSeverity.advisory
    else:
        sev = ProjectionHealthSeverity.ok

    return ExecutionProjection(
        execution_path=exec_path,
        remote_execution_mode=remote_mode,
        target_device_ids=target_device_ids,
        orchestration_active=orchestration_active,
        delegation_point=delegation_point,
        execution_reason=exec_reason,
        health_severity=sev,
    )


def _build_lifecycle_projection(
    ucp: Dict[str, Any],
    tristate: Optional[str],
) -> LifecycleProjection:
    """Build the lifecycle sub-projection from the unified control plan and tri-state."""
    lifecycle_target = _safe_str(ucp.get("lifecycle_target"))
    decision_authority = _safe_str(ucp.get("decision_authority"))
    stage = _lifecycle_stage_from_plan(ucp, tristate)

    # Health severity from lifecycle stage.
    if stage == LifecycleStage.fail:
        sev = ProjectionHealthSeverity.critical
    elif stage == LifecycleStage.degrade:
        sev = ProjectionHealthSeverity.degraded
    elif stage in (LifecycleStage.succeed, LifecycleStage.idle, LifecycleStage.run):
        sev = ProjectionHealthSeverity.ok
    else:
        sev = ProjectionHealthSeverity.advisory

    return LifecycleProjection(
        stage=stage,
        tristate=tristate,
        lifecycle_target=lifecycle_target,
        health_severity=sev,
        decision_authority=decision_authority,
    )


def _build_explainability_projection(ucp: Dict[str, Any]) -> ExplainabilityProjection:
    """Build the explainability sub-projection from the unified control plan."""
    fdr = _safe_dict(ucp.get("fallback_decision_record"))
    has_fallback = _safe_bool(fdr.get("has_fallback") if fdr else False)
    fallback_kinds: List[str] = _safe_list(fdr.get("fallback_kinds") if fdr else [])

    # Collect human-readable fallback reasons from the record.
    fallback_reasons: List[str] = []
    if fdr:
        _reason_fields = [
            "model_fallback_reason",
            "agent_to_command_reason",
            "remote_to_local_reason",
            "multimodal_downgrade_reason",
            "orchestration_downgrade_reason",
            "blocked_reason",
        ]
        for rf in _reason_fields:
            r = _safe_str(fdr.get(rf))
            if r:
                fallback_reasons.append(r)

    # Also include the top-level fallback_reason from the plan.
    top_fallback_reason = _safe_str(ucp.get("fallback_reason"))
    if top_fallback_reason and top_fallback_reason not in fallback_reasons:
        fallback_reasons.append(top_fallback_reason)
        has_fallback = True

    # Degradation summary.
    degradation_summary: Optional[str] = None
    if fallback_kinds or fallback_reasons:
        parts = []
        if fallback_kinds:
            parts.append("kinds: " + ", ".join(fallback_kinds))
        if fallback_reasons:
            parts.append("reasons: " + "; ".join(fallback_reasons))
        degradation_summary = " | ".join(parts)

    # Diagnostics summary dict.
    diag_summary = _safe_dict(ucp.get("diagnostics_summary")) or None

    # Authority chain clarity.
    auth = _safe_str(ucp.get("decision_authority"))
    authority_chain_clear = auth == "subject_decision_authority"

    # Source warnings from model supply state.
    source_warnings: List[str] = []
    model_supply = _safe_dict(ucp.get("canonical_model_supply"))
    if model_supply:
        for rec in _safe_list(model_supply.get("providers")):
            health = _safe_str(rec.get("health_status"), "healthy")
            pid = _safe_str(rec.get("provider_id"), "unknown")
            if health in ("unavailable", "error"):
                source_warnings.append(f"Provider {pid!r} is {health}")
            elif health == "degraded":
                source_warnings.append(f"Provider {pid!r} is degraded")

    # Health severity for explainability block.
    if fallback_kinds or has_fallback:
        sev = ProjectionHealthSeverity.degraded
    elif source_warnings:
        sev = ProjectionHealthSeverity.advisory
    else:
        sev = ProjectionHealthSeverity.ok

    return ExplainabilityProjection(
        has_fallback=has_fallback,
        fallback_kinds=fallback_kinds,
        fallback_reasons=fallback_reasons,
        degradation_summary=degradation_summary,
        diagnostics_summary=diag_summary,
        authority_chain_clear=authority_chain_clear,
        source_warnings=source_warnings,
        health_severity=sev,
    )


def _build_oneapi_integration_projection(ucp: Dict[str, Any]) -> Dict[str, Any]:
    """PR-4: Build the distinct OneAPI lower-horizon integration block.

    This block is **always** present in :class:`DesktopStatusProjection` as
    a top-level ``oneapi_integration`` field.  When OneAPI is not configured
    it shows ``configured=False``; when configured it reflects live status.

    **Architectural constraint**: This block is for lower-horizon rendering
    only.  It must **never** be merged into the top-layer direct/native
    provider list or into route-plan ``primary``/``support`` fields.  Any
    such rendering is architecturally incorrect per
    ``docs/ONEAPI_SYSTEM_POSITION.md``.

    The function derives the summary from the following sources (in priority
    order):

    1. Explicit ``oneapi_status`` block in the UCP (from Node_01_OneAPI
       ``/status`` response forwarded by the runtime).
    2. ``oneapi_summary`` / ``oneapi_source`` blocks in the UCP (enriched
       topology plans, PR-3).
    3. Static build from :func:`~core.oneapi_system_position.build_oneapi_status_summary`
       using environment variable detection.
    """
    # Priority 1: explicit oneapi_status block in UCP
    _ucp_status = _safe_dict(ucp.get("oneapi_status"))
    if _ucp_status:
        _sl = _safe_str(_ucp_status.get("system_layer"))
        if _sl == "aggregator_integration" or not _sl:
            return dict(_ucp_status)

    # Priority 2: oneapi_summary / oneapi_source blocks from enriched plans
    _ucp_summary = _safe_dict(
        ucp.get("oneapi_summary") or ucp.get("oneapi_source")
    )
    if _ucp_summary and _ucp_summary.get("system_layer") == "aggregator_integration":
        return dict(_ucp_summary)

    # Priority 3: static build via the oneapi_system_position module
    try:
        from core.oneapi_system_position import build_oneapi_status_summary
        _base_url = _env_os.getenv("ONEAPI_BASE_URL", "")
        _api_key = _env_os.getenv("ONEAPI_API_KEY", "")
        _configured = bool(_base_url and _api_key)
        _base_url_hint: Optional[str] = None
        if _base_url:
            try:
                _p = _urlparse(_base_url)
                _base_url_hint = (
                    f"{_p.scheme}://{_p.netloc}" if _p.netloc else _base_url
                )
            except Exception:
                pass
        summary = build_oneapi_status_summary(
            configured=_configured,
            health="healthy" if _configured else "skipped",
            base_url_hint=_base_url_hint,
            model_count=None,
            gateway_identity="oneapi-gateway" if _base_url else None,
        )
        return summary.to_dict()
    except Exception as _exc:
        _logger.debug(
            "_build_oneapi_integration_projection: fallback to static dict: %s", _exc
        )

    # Absolute fallback: minimal static dict
    return {
        "system_layer": "aggregator_integration",
        "configured": False,
        "health": "skipped",
        "base_url_hint": None,
        "model_count": None,
        "gateway_identity": None,
    }


# ---------------------------------------------------------------------------
# Primary builders
# ---------------------------------------------------------------------------


def _build_topology_ready_projection(
    ucp: Dict[str, Any],
    oneapi_integration_block: Optional[Dict[str, Any]] = None,
) -> "DesktopTopologyProjection":
    """PR-6: Build the topology-ready projection block for desktop surfaces.

    Derives a :class:`DesktopTopologyProjection` from the canonical
    ``topology_route_plan`` block in the UCP when available, falling back to
    legacy UCP keys with explicit degradation marking.

    Parameters
    ----------
    ucp:
        Unified control plan dict (from ``plan.to_dict()``).
    oneapi_integration_block:
        Pre-built OneAPI lower-horizon integration block (from
        :func:`_build_oneapi_integration_projection`).  When ``None`` the
        function builds its own copy so the topology block is always
        self-contained.

    Returns
    -------
    DesktopTopologyProjection
        A fully populated, renderer-agnostic topology-ready block.
    """
    primary_model_id: Optional[str] = None
    primary_provider_id: Optional[str] = None
    primary_vendor_source: Optional[str] = None
    primary_is_native_mm: bool = False
    support_model_ids: List[str] = []
    route_reason: Optional[str] = None
    route_phase: Optional[str] = None
    route_domain: Optional[str] = None
    routing_authority_source: str = "none"
    canonical_source_present: bool = False

    # ------------------------------------------------------------------
    # CANONICAL PATH: topology_route_plan
    # ------------------------------------------------------------------
    if "topology_route_plan" in ucp:
        routing_authority_source = "topology_router"
        canonical_source_present = True
        topology_plan = _safe_dict(ucp["topology_route_plan"])
        primary = _safe_dict(topology_plan.get("primary_model"))
        if primary:
            primary_model_id = _safe_str(primary.get("model_id"))
            primary_provider_id = _safe_str(primary.get("provider_id"))
            primary_vendor_source = _safe_str(primary.get("vendor_source"))
            primary_is_native_mm = _safe_bool(primary.get("native_multimodal"))
        support_nodes = _safe_list(topology_plan.get("support_models"))
        support_model_ids = [
            _safe_str(s.get("model_id"))
            for s in support_nodes
            if isinstance(s, dict) and _safe_str(s.get("model_id"))
        ]
        route_reason = _safe_str(topology_plan.get("route_reason"))
        route_phase = _safe_str(topology_plan.get("phase"))
        route_domain = _safe_str(topology_plan.get("domain"))

    else:
        # ------------------------------------------------------------------
        # LEGACY COMPAT PATH — top-level UCP keys only
        # ------------------------------------------------------------------
        _model = _safe_str(ucp.get("chosen_model"))
        _provider = _safe_str(ucp.get("chosen_provider"))
        _reason = _safe_str(ucp.get("route_reason"))
        _is_mm = _safe_bool(ucp.get("is_native_multimodal"))
        _support = _safe_list(ucp.get("support_model_ids"))

        # Also check multimodal_route block
        mm_route = _safe_dict(ucp.get("multimodal_route"))
        if mm_route:
            if not _reason:
                _reason = _safe_str(mm_route.get("route_reason"))
            if not _is_mm:
                _is_mm = _safe_bool(mm_route.get("is_native_multimodal"))
            if not _model:
                _model = _safe_str(mm_route.get("selected_model"))
            if not _provider:
                _provider = _safe_str(mm_route.get("selected_provider"))

        primary_model_id = _model
        primary_provider_id = _provider
        primary_is_native_mm = _is_mm
        support_model_ids = [s for s in _support if isinstance(s, str) and s]
        route_reason = _reason

        if _model or _provider or _reason:
            routing_authority_source = "legacy_ucp_keys"

    # ------------------------------------------------------------------
    # Provider availability
    # ------------------------------------------------------------------
    primary_provider_available = True
    model_supply = _safe_dict(ucp.get("canonical_model_supply"))
    if model_supply and primary_provider_id:
        for rec in _safe_list(model_supply.get("providers")):
            if _safe_str(rec.get("provider_id")) == primary_provider_id:
                health = _safe_str(rec.get("health_status"), "healthy")
                if health in ("unavailable", "error"):
                    primary_provider_available = False
                break

    # ------------------------------------------------------------------
    # OneAPI integration block (lower-horizon; always separate)
    # ------------------------------------------------------------------
    if oneapi_integration_block is None:
        oneapi_integration_block = _build_oneapi_integration_projection(ucp)

    # ------------------------------------------------------------------
    # Health severity
    # ------------------------------------------------------------------
    legacy_fallback = routing_authority_source == "legacy_ucp_keys"
    if not primary_model_id and not primary_provider_id:
        sev = ProjectionHealthSeverity.unknown
    elif not primary_provider_available:
        sev = ProjectionHealthSeverity.critical
    elif legacy_fallback:
        sev = ProjectionHealthSeverity.degraded
    else:
        sev = ProjectionHealthSeverity.ok

    return DesktopTopologyProjection(
        primary_model_id=primary_model_id,
        primary_provider_id=primary_provider_id,
        primary_vendor_source=primary_vendor_source,
        primary_is_native_multimodal=primary_is_native_mm,
        support_model_ids=support_model_ids,
        route_reason=route_reason,
        route_phase=route_phase,
        route_domain=route_domain,
        primary_provider_available=primary_provider_available,
        routing_authority_source=routing_authority_source,
        canonical_source_present=canonical_source_present,
        legacy_fallback_active=legacy_fallback,
        oneapi_integration=oneapi_integration_block,
        health_severity=sev,
        contract_authority=TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
    )


def build_desktop_status_projection(
    *,
    unified_control_plan: Optional[Dict[str, Any]] = None,
    source_registry_snapshot: Optional[Dict[str, Any]] = None,
    tristate: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> DesktopStatusProjection:
    """Build a canonical :class:`DesktopStatusProjection` for shell-facing status board rendering.

    This is the primary builder consumed by the runtime shell
    (:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`).

    The shell combines control-core outputs (:class:`~core.schemas.unified_control_plan.UnifiedControlPlan`
    produced by OpenClawd) with shell-owned state (source registry snapshot,
    tri-state lifecycle) through this stable projection contract.

    All parameters are optional — a valid projection is always produced even
    when sources or the control plan are unavailable.

    Parameters
    ----------
    unified_control_plan:
        Serialised :class:`~core.schemas.unified_control_plan.UnifiedControlPlan`
        dict (from ``plan.to_dict()``).  ``None`` produces a minimal, valid
        projection with graceful defaults.
    source_registry_snapshot:
        Snapshot dict from
        :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.snapshot_source_registry`.
        ``None`` means no source registry information is available.
    tristate:
        Current subject tri-state value from the runtime shell
        (``"silent"`` / ``"liminal"`` / ``"manifest"``).  ``None`` treated as
        unknown.
    runtime_session_id:
        Correlation ID for the active runtime session.

    Returns
    -------
    DesktopStatusProjection
        A fully populated, serialisable desktop status projection.  Never
        raises; degrades gracefully on any internal error.
    """
    try:
        ucp: Dict[str, Any] = unified_control_plan or {}

        perception = _build_perception_projection(ucp, source_registry_snapshot)
        model_routing = _build_model_routing_projection(ucp)
        execution = _build_execution_projection(ucp)
        lifecycle = _build_lifecycle_projection(ucp, tristate)
        explainability = _build_explainability_projection(ucp)

        # PR-4: distinct lower-horizon OneAPI integration block.
        # Always built; must not be merged into model_routing or any top-layer block.
        oneapi_integration = _build_oneapi_integration_projection(ucp)

        # PR-6: topology-ready projection block for desktop topology surfaces.
        # Pass the pre-built OneAPI block so it is shared (not rebuilt twice).
        topology_ready = _build_topology_ready_projection(
            ucp, oneapi_integration_block=oneapi_integration
        )

        # Roll up overall health from all blocks.
        overall_health = _rolled_up_severity([
            perception.health_severity,
            model_routing.health_severity,
            execution.health_severity,
            lifecycle.health_severity,
            explainability.health_severity,
        ])

        return DesktopStatusProjection(
            runtime_session_id=runtime_session_id,
            perception=perception,
            model_routing=model_routing,
            execution=execution,
            lifecycle=lifecycle,
            explainability=explainability,
            oneapi_integration=oneapi_integration,
            topology_ready=topology_ready,
            overall_health=overall_health,
        )
    except Exception as _err:
        _logger.warning("build_desktop_status_projection failed, returning minimal: %s", _err)
        return DesktopStatusProjection(
            runtime_session_id=runtime_session_id,
            overall_health=ProjectionHealthSeverity.unknown,
        )


def desktop_status_projection_summary(
    projection: Optional["DesktopStatusProjection"],
) -> Optional[Dict[str, Any]]:
    """Return a compact, serialisable summary dict for the given projection.

    Suitable for embedding in response metadata or API payloads.

    Returns ``None`` when *projection* is ``None``.
    """
    if projection is None:
        return None
    return {
        "projection_id": projection.projection_id,
        "runtime_session_id": projection.runtime_session_id,
        "projected_at": projection.projected_at,
        "overall_health": projection.overall_health.value,
        "lifecycle_stage": projection.lifecycle.stage.value,
        "tristate": projection.lifecycle.tristate,
        "selected_provider": projection.model_routing.selected_provider,
        "selected_model": projection.model_routing.selected_model,
        "is_native_multimodal": projection.model_routing.is_native_multimodal,
        "execution_path": projection.execution.execution_path.value,
        "remote_execution_mode": projection.execution.remote_execution_mode,
        "orchestration_active": projection.execution.orchestration_active,
        "continuous_perception_active": projection.perception.continuous_perception_active,
        "active_modalities": projection.perception.active_modalities,
        "has_fallback": projection.explainability.has_fallback,
        "fallback_kinds": projection.explainability.fallback_kinds,
        "degradation_summary": projection.explainability.degradation_summary,
    }
