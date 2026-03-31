"""
galaxy_gateway/legacy/task_decomposer.py — Canonical legacy location.

.. deprecated:: Batch PR-3
    Deprecation level: D1 (SOFT_DEPRECATED)
    Canonical replacement: ``galaxy_gateway.orchestrator`` package
    Removal target: **Batch PR-5**

    This module is a **compatibility shim only**.  New code must not import
    :class:`TaskDecomposer` or :class:`IntelligentTaskPlanner` from this path.
    Use :mod:`galaxy_gateway.orchestrator` directly instead.

    Active callers: legacy code that references the
    ``galaxy_gateway.legacy.task_decomposer`` import path.
    Do not delete until all callers have migrated.

This is the canonical import path for legacy task decomposition.
The implementation is in galaxy_gateway.task_decomposer (maintained for
backward compatibility at both paths).
"""
import warnings

warnings.warn(
    "galaxy_gateway.legacy.task_decomposer is deprecated (D1).  "
    "Use galaxy_gateway.orchestrator instead.  "
    "This shim will be removed in Batch PR-5.",
    DeprecationWarning,
    stacklevel=2,
)

from galaxy_gateway.task_decomposer import TaskDecomposer, IntelligentTaskPlanner  # noqa: F401, E402

__all__ = ["TaskDecomposer", "IntelligentTaskPlanner"]
