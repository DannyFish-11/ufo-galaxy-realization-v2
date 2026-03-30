"""
core/architecture_live_status.py — Compatibility shim.

This module has been moved to tools.architecture.architecture_live_status.
This shim re-exports everything for backward compatibility.
"""
# ruff: noqa: F401
from tools.architecture.architecture_live_status import *  # noqa: F401, F403
try:
    from tools.architecture.architecture_live_status import __all__
except ImportError:
    pass
