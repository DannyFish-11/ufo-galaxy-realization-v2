"""
core/projection/__init__.py
=============================
Public surface of the Runtime Projection package (PR-3).

Quick start::

    from core.projection import RuntimeProjection, build_runtime_projection, ExecutionSummary
    from core.continuum.types import ContinuumState, ContinuumPhase

    state = ContinuumState(phase=ContinuumPhase.LIMINAL)
    projection = build_runtime_projection(state)
    payload = projection.to_dict()

PR-5 exposes server-side canonicalization sentinels::

    from core.projection import LEGACY_PROJECTION_UCP_KEYS, PROJECTION_COMPILER_AUTHORITY

    # Machine-checkable: these keys are legacy/compatibility-only in projection
    print(LEGACY_PROJECTION_UCP_KEYS)   # ("chosen_model", "chosen_provider", ...)
    print(PROJECTION_COMPILER_AUTHORITY)  # "core.projection.projection_compiler.build_runtime_projection"

See ``docs/SERVER_SIDE_CANONICALIZATION.md`` for the PR-5 canonicalization policy.

PR-6 exposes the topology-ready projection delivery sentinel::

    from core.projection import TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY

    # Machine-checkable: confirms topology-ready block was produced by the canonical builder
    print(TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY)  # "contracts.desktop_status_projection.DesktopTopologyProjection"

See ``docs/SERVER_SIDE_CANONICALIZATION.md`` §8 for the PR-6 topology delivery policy.

PR-7 exposes the projection readiness / quality contract sentinel::

    from core.projection import TOPOLOGY_READINESS_CONTRACT_AUTHORITY

    # Machine-checkable: identifies the PR-7 quality/readiness block artefact
    print(TOPOLOGY_READINESS_CONTRACT_AUTHORITY)  # "contracts.desktop_status_projection.TopologyProjectionQualityBlock"

See ``docs/SERVER_SIDE_CANONICALIZATION.md`` §9 for the PR-7 readiness/quality policy.

PR-26 adds a governance-aware assembly layer::

    from core.projection import assemble_projection_governance

    governance = assemble_projection_governance(
        intent_profile=profile,
        readiness_result=readiness,
        fallback_trace=trace,
        execution_trace_envelope=envelope,
        state_continuum=state,
    )
    payload = governance.to_dict()

PR-8 adds a final desktop status board integration bridge::

    from core.projection import build_desktop_status_board_integration_from_runtime
    from core.continuum.types import ContinuumState, ContinuumPhase

    state = ContinuumState(phase=ContinuumPhase.ACTIVE)
    integration_payload = build_desktop_status_board_integration_from_runtime(
        continuum_state=state, route_plan=plan
    )
    # integration_payload is a DesktopStatusBoardIntegrationPayload
    print(integration_payload.readiness)    # e.g. "canonical"
    print(integration_payload.is_canonical) # True

See ``docs/RUNTIME_PROJECTION.md`` for the base projection design rationale.
See ``docs/PROJECTION_ASSEMBLY_GOVERNANCE.md`` for the PR-26 governance layer.
See ``docs/STATUS_BOARD_V2.md`` (PR-8 section) for the final integration contract.

PR-9 adds the desktop client consumption adapter::

    from core.projection import adapt_integration_payload, DesktopClientViewModel

    vm = adapt_integration_payload(integration_payload)
    print(vm.is_canonical)       # True / False
    print(vm.readiness_state)    # DesktopReadinessState.canonical / ...
    print(vm.integration_health) # "ok" / "degraded" / ...

See ``docs/DESKTOP_CONSUMPTION_ADAPTER.md`` for the post-PR-9 consumption guide.

Runtime truth compiler — single compilation authority::

    from core.projection import compile_runtime_truth, RUNTIME_TRUTH_COMPILER_AUTHORITY

    snapshot = compile_runtime_truth()
    # All route handlers and consumers should use this instead of
    # sourcing directly from subsystem modules.
    print(snapshot.tri_state_phase)       # e.g. "silent"
    print(snapshot.primary_model_id)      # e.g. "gpt-4o" or None
    print(snapshot.compiler_authority)    # == RUNTIME_TRUTH_COMPILER_AUTHORITY

See ``docs/PROJECTION_OUTPUT_AUTHORITY.md`` for the full canonical output
authority model including the endpoint directory.
"""

from .runtime_truth_compiler import (
    RUNTIME_TRUTH_COMPILER_AUTHORITY,
    RuntimeTruthSnapshot,
    compile_runtime_truth,
)
from .assembly_governance import (
    ProjectionExecutionSummary,
    ProjectionExecutionTraceSummary,
    ProjectionGovernanceSummary,
    ProjectionPolicySummary,
    ProjectionTraceSummary,
    assemble_projection_governance,
    summarize_execution_trace_for_projection,
    summarize_fallback_for_projection,
    summarize_intent_for_projection,
    summarize_readiness_for_projection,
)
from .projection_compiler import (
    DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY,
    ExecutionSummary,
    # PR-5: server-side canonicalization sentinels
    LEGACY_PROJECTION_UCP_KEYS,
    PROJECTION_COMPILER_AUTHORITY,
    # PR-6: topology-ready projection delivery sentinel
    TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY,
    # PR-7: projection readiness / quality contract sentinel
    TOPOLOGY_READINESS_CONTRACT_AUTHORITY,
    build_desktop_status_board_integration_from_runtime,
    build_runtime_projection,
)
from .runtime_projection import RuntimeProjection
from core.desktop_consumption_adapter import (
    DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    DesktopClientViewModel,
    DesktopOneAPIHorizonSummary,
    DesktopProviderRoutingSummary,
    DesktopReadinessState,
    adapt_integration_payload,
)

__all__ = [
    "RuntimeProjection",
    "ExecutionSummary",
    "build_runtime_projection",
    # Runtime truth compiler — canonical output authority
    "RUNTIME_TRUTH_COMPILER_AUTHORITY",
    "RuntimeTruthSnapshot",
    "compile_runtime_truth",
    # PR-5: server-side canonicalization sentinels
    "LEGACY_PROJECTION_UCP_KEYS",
    "PROJECTION_COMPILER_AUTHORITY",
    # PR-6: topology-ready projection delivery sentinel
    "TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY",
    # PR-7: projection readiness / quality contract sentinel
    "TOPOLOGY_READINESS_CONTRACT_AUTHORITY",
    # PR-8: final desktop status board integration bridge
    "build_desktop_status_board_integration_from_runtime",
    "DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY",
    # PR-9: desktop client consumption adapter
    "adapt_integration_payload",
    "DesktopClientViewModel",
    "DesktopReadinessState",
    "DesktopProviderRoutingSummary",
    "DesktopOneAPIHorizonSummary",
    "DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY",
    # PR-26 governance assembly
    "ProjectionGovernanceSummary",
    "ProjectionExecutionSummary",
    "ProjectionPolicySummary",
    "ProjectionTraceSummary",
    "ProjectionExecutionTraceSummary",
    "assemble_projection_governance",
    "summarize_intent_for_projection",
    "summarize_readiness_for_projection",
    "summarize_fallback_for_projection",
    "summarize_execution_trace_for_projection",
]
