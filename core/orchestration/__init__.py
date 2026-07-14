"""core/orchestration/__init__.py — Galaxy orchestration package.

PR-8: Multi-device orchestration plan/result contracts are exported from this
package so that callers can clearly import from the orchestration layer without
crossing into the substrate (CommandRouter).

PR-7: Decomposition of core/openclawd.py (god object) into dedicated submodules.
Authority sentinels and submodule façades are maintained in the submodules below.
"""

# ============================================================================
# PR-7: Top-level authority sentinel
# ============================================================================

OPENCLAWD_ORCHESTRATION_AUTHORITY = "OPENCLAWD_ORCHESTRATION_AUTHORITY"

# ============================================================================
# PR-8: Multi-device plan contracts (original exports — preserved)
# ============================================================================

from core.orchestration.execution import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    EXECUTION_PIPELINE_AUTHORITY,
    ExecutionPipeline,
)
from core.orchestration.helpers import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    ORCHESTRATION_HELPERS_AUTHORITY,
    OrchestrationHelpers,
)
from core.orchestration.lifecycle import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    _LOCAL_DEVICE_PREFIXES,
    _LOCAL_HOSTNAME,
    LIFECYCLE_MANAGER_AUTHORITY,
    LifecycleManager,
    ParallelGroupTracker,
    ParallelResult,
    _is_local_device,
    _SubtaskEntry,
    _SubtaskStatus,
)
from core.orchestration.multi_device_plan import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    OrchestrationDecision,
    OrchestrationMemberResult,
    OrchestrationPlan,
    OrchestrationResult,
    build_orchestration_plan,
    build_orchestration_result,
)
from core.orchestration.perception import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    PERCEPTION_PIPELINE_AUTHORITY,
    PerceptionPipeline,
)
from core.orchestration.planning import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    PLANNING_PIPELINE_AUTHORITY,
    PlanningPipeline,
)
from core.orchestration.reflection import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    REFLECTION_PIPELINE_AUTHORITY,
    ReflectionPipeline,
)
from core.orchestration.state import (  # noqa: E402  哨兵权威声明置顶是本仓设计习语
    STATE_MANAGER_AUTHORITY,
    ContinuumStateAdapter,
    SessionMemoryManager,
)

# ============================================================================
# PR-7: Submodule re-exports for convenience
# ============================================================================


__all__ = [
    # PR-7 sentinel
    "OPENCLAWD_ORCHESTRATION_AUTHORITY",
    # PR-8 plan contracts
    "OrchestrationDecision",
    "OrchestrationPlan",
    "OrchestrationMemberResult",
    "OrchestrationResult",
    "build_orchestration_plan",
    "build_orchestration_result",
    # PR-7 lifecycle
    "LIFECYCLE_MANAGER_AUTHORITY",
    "LifecycleManager",
    "ParallelGroupTracker",
    "ParallelResult",
    "_SubtaskEntry",
    "_SubtaskStatus",
    "_is_local_device",
    "_LOCAL_DEVICE_PREFIXES",
    "_LOCAL_HOSTNAME",
    # PR-7 state
    "STATE_MANAGER_AUTHORITY",
    "SessionMemoryManager",
    "ContinuumStateAdapter",
    # PR-7 perception
    "PERCEPTION_PIPELINE_AUTHORITY",
    "PerceptionPipeline",
    # PR-7 planning
    "PLANNING_PIPELINE_AUTHORITY",
    "PlanningPipeline",
    # PR-7 execution
    "EXECUTION_PIPELINE_AUTHORITY",
    "ExecutionPipeline",
    # PR-7 reflection
    "REFLECTION_PIPELINE_AUTHORITY",
    "ReflectionPipeline",
    # PR-7 helpers
    "ORCHESTRATION_HELPERS_AUTHORITY",
    "OrchestrationHelpers",
]
