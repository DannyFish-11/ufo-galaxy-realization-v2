"""
core/architecture_diagnostics.py — Compatibility shim.

This module has been moved to tools.architecture.architecture_diagnostics.
This shim re-exports everything for backward compatibility.
"""
# ruff: noqa: F401
from tools.architecture.architecture_diagnostics import *  # noqa: F401, F403
try:
    from tools.architecture.architecture_diagnostics import __all__
except ImportError:
    pass
