"""core/runtime/__init__.py
============================
Galaxy runtime sub-package.

Exports the target-side local takeover path introduced in PR-34 and the
source-side dispatch orchestrator introduced in PR-35.
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
]
