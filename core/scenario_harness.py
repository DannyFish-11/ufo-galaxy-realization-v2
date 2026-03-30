"""
core/scenario_harness.py — Compatibility shim.

This module has been moved to tools.architecture.scenario_harness.
This shim re-exports everything for backward compatibility.
"""
# ruff: noqa: F401
from tools.architecture.scenario_harness import *  # noqa: F401, F403
try:
    from tools.architecture.scenario_harness import __all__
except ImportError:
    pass
