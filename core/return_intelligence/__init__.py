"""
core/return_intelligence/__init__.py
=====================================
Public surface of the ``core.return_intelligence`` package.

Return Intelligence Formalization (PR-10)
------------------------------------------
This package provides a coherent, additive layer that makes it easy for
downstream systems (Status Board V2, Manifest Stage, Liminal layer, API
routes) to understand and consume return behaviour:

- **what** return mode / action is active
- **why** the system is receding/softening
- **how** return behaviour should influence projection surfaces

Public API
----------
ReturnMode
    Public-safe enum of return modes (``none``, ``hold``, ``soft_decay``,
    ``step_down``, ``return_to_formless``).  Does NOT expose ``receding``.

ReturnSummary
    Stable, serialisable dataclass carrying the return-intelligence state.
    Produced by :func:`build_return_summary` from a
    :class:`~core.continuum.return_engine.ReturnResult`.

IDLE_RETURN_SUMMARY
    A pre-built :class:`ReturnSummary` representing a healthy,
    non-returning system.  Use as a default when no engine result is
    available.

build_return_summary(result)
    Convert a :class:`~core.continuum.return_engine.ReturnResult` (or
    ``None``) into a public-safe :class:`ReturnSummary`.

attach_return_summary(projection_dict, summary)
    Attach a :class:`ReturnSummary` to a ``RuntimeProjection`` dict
    in an additive, backward-compatible way.

get_return_hints(summary)
    Extract a compact ``dict`` of boolean / scalar hints from a summary;
    handy for quick checks in Manifest and Liminal controllers.

MODES_THAT_SUPPRESS_MANIFEST
    ``frozenset`` of :class:`ReturnMode` values that degrade the Manifest
    Stage surface when active.

MODES_THAT_SOFTEN_LIMINAL
    ``frozenset`` of :class:`ReturnMode` values that soften the Liminal
    spatial projection when active.

ACTIVE_RETURN_MODES
    ``frozenset`` of :class:`ReturnMode` values that indicate an active
    return (excludes ``none`` and ``hold``).
"""

from __future__ import annotations

from .return_modes import (
    ReturnMode,
    MODES_THAT_SUPPRESS_MANIFEST,
    MODES_THAT_SOFTEN_LIMINAL,
    ACTIVE_RETURN_MODES,
)
from .return_summary import ReturnSummary, IDLE_RETURN_SUMMARY
from .return_projection_adapter import (
    build_return_summary,
    attach_return_summary,
    get_return_hints,
)

__all__ = [
    # Enums and constants
    "ReturnMode",
    "MODES_THAT_SUPPRESS_MANIFEST",
    "MODES_THAT_SOFTEN_LIMINAL",
    "ACTIVE_RETURN_MODES",
    # Data model
    "ReturnSummary",
    "IDLE_RETURN_SUMMARY",
    # Adapters
    "build_return_summary",
    "attach_return_summary",
    "get_return_hints",
]
