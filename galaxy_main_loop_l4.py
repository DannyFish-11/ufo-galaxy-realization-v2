# =============================================================================
# DEPRECATED — DO NOT USE AS PRIMARY ENTRYPOINT
# =============================================================================
# This file is a **legacy entrypoint** retained for backward compatibility.
# The authoritative startup path for UFO Galaxy is:
#     python main.py
# which runs the full 7-phase pre-flight before delegating to
# unified_launcher.py for async service bring-up.
#
# If you are starting Galaxy for the first time, use main.py instead.
# This file may be removed in a future release without further notice.
# =============================================================================

"""
galaxy_main_loop_l4 — retired root module (re-export tombstone)
===============================================================

.. deprecated:: post-PR-10
    This root-level module has been **retired**.  All classes and symbols
    have been moved to the canonical location:

        ``core.galaxy_main_loop_l4_enhanced``

    Update your imports::

        # Old (deprecated):
        from galaxy_main_loop_l4 import GalaxyMainLoopL4

        # New (canonical):
        from core.galaxy_main_loop_l4_enhanced import GalaxyMainLoopL4

    The authoritative startup chain remains ``main.py`` → ``unified_launcher.py``.
    The L4 runtime is managed through ``unified_launcher.py``.
"""
# Re-export everything from the canonical location so existing
# import paths continue to work during the transition.
from core.galaxy_main_loop_l4_enhanced import (  # noqa: F401
    CycleState,
    GalaxyMainLoopL4,
    GalaxyMainLoopL4Enhanced,
    L4CycleResult,
    PendingGoal,
    _CODER_AVAILABLE,
    _EXECUTOR_AVAILABLE,
    _GOAL_DECOMPOSER_AVAILABLE,
    _LEARNING_AVAILABLE,
    _METACOGNITION_AVAILABLE,
    _MONITOR_AVAILABLE,
    _PERCEPTION_AVAILABLE,
    _PLANNER_AVAILABLE,
    _SAFETY_AVAILABLE,
    _WORLD_MODEL_AVAILABLE,
    get_galaxy_loop,
)

__all__ = [
    "GalaxyMainLoopL4",
    "GalaxyMainLoopL4Enhanced",
    "CycleState",
    "L4CycleResult",
    "PendingGoal",
    "get_galaxy_loop",
    "_PERCEPTION_AVAILABLE",
    "_GOAL_DECOMPOSER_AVAILABLE",
    "_PLANNER_AVAILABLE",
    "_WORLD_MODEL_AVAILABLE",
    "_METACOGNITION_AVAILABLE",
    "_CODER_AVAILABLE",
    "_EXECUTOR_AVAILABLE",
    "_MONITOR_AVAILABLE",
    "_SAFETY_AVAILABLE",
    "_LEARNING_AVAILABLE",
]
