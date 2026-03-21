"""core/runtime/__init__.py
============================
Galaxy runtime sub-package.

Exports the target-side local takeover path introduced in PR-34.
"""

from core.runtime.target_takeover import (
    TargetTakeoverHandler,
    adopt_handoff_session,
    build_local_takeover_context,
    resolve_or_create_runtime_session,
    normalize_handoff_envelope,
    execute_local_takeover,
)

__all__ = [
    "TargetTakeoverHandler",
    "adopt_handoff_session",
    "build_local_takeover_context",
    "resolve_or_create_runtime_session",
    "normalize_handoff_envelope",
    "execute_local_takeover",
]
