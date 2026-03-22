"""core/orchestration/__init__.py — Block-5 global orchestration package.

PR-8: Multi-device orchestration plan/result contracts are exported from this
package so that callers can clearly import from the orchestration layer without
crossing into the substrate (CommandRouter).
"""

from core.orchestration.multi_device_plan import (
    OrchestrationDecision,
    OrchestrationPlan,
    OrchestrationMemberResult,
    OrchestrationResult,
    build_orchestration_plan,
    build_orchestration_result,
)

__all__ = [
    "OrchestrationDecision",
    "OrchestrationPlan",
    "OrchestrationMemberResult",
    "OrchestrationResult",
    "build_orchestration_plan",
    "build_orchestration_result",
]
