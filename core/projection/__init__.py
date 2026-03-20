"""
core/projection/__init__.py
=============================
Public surface of the Runtime Projection package (PR-3).

Quick start::

    from core.projection import RuntimeProjection, build_runtime_projection, ExecutionSummary
    from core.continuum.types import ContinuumState, ContinuumPhase

    state = ContinuumState(phase=ContinuumPhase.LIMINAL)
    projection = build_runtime_projection(state)
    payload = projection.to_dict()

See ``docs/RUNTIME_PROJECTION.md`` for the full design rationale.
"""

from .projection_compiler import ExecutionSummary, build_runtime_projection
from .runtime_projection import RuntimeProjection

__all__ = [
    "RuntimeProjection",
    "ExecutionSummary",
    "build_runtime_projection",
]
