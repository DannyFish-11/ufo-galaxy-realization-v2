"""
core/architecture_truth_guards.py — Compatibility shim.

This module has been moved to tools.architecture.architecture_truth_guards.
This shim re-exports everything for backward compatibility.
"""
# ruff: noqa: F401
from tools.architecture.architecture_truth_guards import *  # noqa: F401, F403
try:
    from tools.architecture.architecture_truth_guards import __all__
except ImportError:
    pass
