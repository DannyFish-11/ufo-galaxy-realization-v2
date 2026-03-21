"""core/runtime/__init__.py
============================
Galaxy runtime sub-package.

Exports the target-side local takeover path introduced in PR-34, the
source-side dispatch orchestrator introduced in PR-35, and the cross-runtime
result merge helpers introduced in PR-36.
"""

from core.runtime.target_takeover import (
    TargetTakeoverHandler,
    adopt_handoff_session,
    build_local_takeover_context,
    resolve_or_create_runtime_session,
    normalize_handoff_envelope,
    execute_local_takeover,
)

# PR-35: Source Runtime Dispatch Orchestrator
from core.runtime.source_dispatch_orchestrator import (
    SourceDispatchOrchestrator,
    select_dispatch_mode,
    select_dispatch_target,
    build_source_dispatch_plan,
    orchestrate_source_runtime_dispatch,
)

# PR-36: Cross-Runtime Result Merge Contract helpers
from contracts.cross_runtime_result_merge import (
    RuntimeResultRole,
    RuntimeResultStatus,
    ResultMergePolicy,
    RuntimeResultUnit,
    MergedRuntimeResult,
    ResultMergeSummary,
    from_local_takeover_result as merge_unit_from_takeover_result,
    from_source_dispatch_result as merge_unit_from_dispatch_result,
    from_execution_output as merge_unit_from_execution_output,
    build_merged_runtime_result,
    merge_runtime_results,
    build_result_merge_summary,
)

__all__ = [
    # PR-34: Target Runtime Local Takeover Path
    "TargetTakeoverHandler",
    "adopt_handoff_session",
    "build_local_takeover_context",
    "resolve_or_create_runtime_session",
    "normalize_handoff_envelope",
    "execute_local_takeover",
    # PR-35: Source Runtime Dispatch Orchestrator
    "SourceDispatchOrchestrator",
    "select_dispatch_mode",
    "select_dispatch_target",
    "build_source_dispatch_plan",
    "orchestrate_source_runtime_dispatch",
    # PR-36: Cross-Runtime Result Merge Contract
    "RuntimeResultRole",
    "RuntimeResultStatus",
    "ResultMergePolicy",
    "RuntimeResultUnit",
    "MergedRuntimeResult",
    "ResultMergeSummary",
    "merge_unit_from_takeover_result",
    "merge_unit_from_dispatch_result",
    "merge_unit_from_execution_output",
    "build_merged_runtime_result",
    "merge_runtime_results",
    "build_result_merge_summary",
]
