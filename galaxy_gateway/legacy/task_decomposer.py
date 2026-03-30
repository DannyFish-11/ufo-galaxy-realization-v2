"""
galaxy_gateway/legacy/task_decomposer.py — Canonical legacy location.

This is the canonical import path for legacy task decomposition.
The implementation is in galaxy_gateway.task_decomposer (maintained for
backward compatibility at both paths).
"""
from galaxy_gateway.task_decomposer import TaskDecomposer, IntelligentTaskPlanner  # noqa: F401

__all__ = ["TaskDecomposer", "IntelligentTaskPlanner"]
