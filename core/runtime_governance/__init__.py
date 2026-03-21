"""
core/runtime_governance/__init__.py
=====================================
Runtime Governance package — PR-27.

Public surface
--------------
Contracts:
    - :class:`~core.runtime_governance.snapshot.RuntimeGovernanceExecutionSummary`
    - :class:`~core.runtime_governance.snapshot.RuntimeGovernancePolicySummary`
    - :class:`~core.runtime_governance.snapshot.RuntimeGovernanceTraceSummary`
    - :class:`~core.runtime_governance.snapshot.RuntimeGovernanceProjectionSummary`
    - :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`

Assembly helpers:
    - :func:`~core.runtime_governance.snapshot.summarize_runtime_intent`
    - :func:`~core.runtime_governance.snapshot.summarize_runtime_readiness`
    - :func:`~core.runtime_governance.snapshot.summarize_runtime_fallback`
    - :func:`~core.runtime_governance.snapshot.summarize_runtime_execution_trace`
    - :func:`~core.runtime_governance.snapshot.summarize_projection_governance_for_runtime`
    - :func:`~core.runtime_governance.snapshot.assemble_runtime_governance_snapshot`
"""

from core.runtime_governance.snapshot import (
    RuntimeGovernanceExecutionSummary,
    RuntimeGovernancePolicySummary,
    RuntimeGovernanceProjectionSummary,
    RuntimeGovernanceSnapshot,
    RuntimeGovernanceTraceSummary,
    assemble_runtime_governance_snapshot,
    summarize_projection_governance_for_runtime,
    summarize_runtime_execution_trace,
    summarize_runtime_fallback,
    summarize_runtime_intent,
    summarize_runtime_readiness,
)

__all__ = [
    "RuntimeGovernanceExecutionSummary",
    "RuntimeGovernancePolicySummary",
    "RuntimeGovernanceTraceSummary",
    "RuntimeGovernanceProjectionSummary",
    "RuntimeGovernanceSnapshot",
    "summarize_runtime_intent",
    "summarize_runtime_readiness",
    "summarize_runtime_fallback",
    "summarize_runtime_execution_trace",
    "summarize_projection_governance_for_runtime",
    "assemble_runtime_governance_snapshot",
]
