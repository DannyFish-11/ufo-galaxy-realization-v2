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

__all__ = [
    "DecisionExecutor",
    "ExecutionResult",
    "PolicyGate",
    "ExecutionIntentProfile",
    "IntentMode",
    "build_execution_intent_profile",
]
