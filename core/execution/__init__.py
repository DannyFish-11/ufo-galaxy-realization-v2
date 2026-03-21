"""core.execution — Decision Gate action execution layer.

Bridges ContinuumState decision output to OS-level actions via
:mod:`core.system_api`.  Execution is disabled by default and must be
explicitly enabled via ``enable_system_actions=true`` in ``config.json``.
"""

from core.execution.decision_executor import DecisionExecutor, ExecutionResult, PolicyGate
from core.execution.intent_profile import (
    ExecutionIntentProfile,
    IntentMode,
    build_execution_intent_profile,
)
from core.execution.readiness_gate import (
    ReadinessStatus,
    ReadinessResult,
    BlockedBy,
    ExecutionReadinessGate,
    evaluate_readiness,
    reset_readiness_gate,
)

# PR-25: Execution Trace Contract
from contracts.execution_trace import (
    ExecutionTraceEnvelope,
    ExecutionTraceEvent,
    ExecutionTraceStage,
    ExecutionTraceStatus,
    build_trace_envelope,
    from_execution_intent,
    from_execution_result,
    from_fallback_trace,
    from_readiness_result,
)

__all__ = [
    "DecisionExecutor",
    "ExecutionResult",
    "PolicyGate",
    "ExecutionIntentProfile",
    "IntentMode",
    "build_execution_intent_profile",
    # PR-23: Execution Readiness Gate
    "ReadinessStatus",
    "ReadinessResult",
    "BlockedBy",
    "ExecutionReadinessGate",
    "evaluate_readiness",
    "reset_readiness_gate",
    # PR-25: Execution Trace Contract
    "ExecutionTraceEnvelope",
    "ExecutionTraceEvent",
    "ExecutionTraceStage",
    "ExecutionTraceStatus",
    "build_trace_envelope",
    "from_execution_intent",
    "from_execution_result",
    "from_fallback_trace",
    "from_readiness_result",
]
