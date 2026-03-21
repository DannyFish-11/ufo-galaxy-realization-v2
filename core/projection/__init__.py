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

See ``docs/RUNTIME_PROJECTION.md`` for the base projection design rationale.
See ``docs/PROJECTION_ASSEMBLY_GOVERNANCE.md`` for the PR-26 governance layer.
"""

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
from .projection_compiler import ExecutionSummary, build_runtime_projection
from .runtime_projection import RuntimeProjection

__all__ = [
    "RuntimeProjection",
    "ExecutionSummary",
    "build_runtime_projection",
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
