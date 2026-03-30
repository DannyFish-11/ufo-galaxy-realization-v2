"""
core/architecture_completion.py — Compatibility shim.

This module has been moved to tools.architecture.architecture_completion.
This shim re-exports everything for backward compatibility.
"""
# ruff: noqa: F401
from tools.architecture.architecture_completion import *  # noqa: F401, F403
try:
    from tools.architecture.architecture_completion import __all__
except ImportError:
    pass
