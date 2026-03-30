"""
core/architecture_status_report.py — Compatibility shim.

This module has been moved to tools.architecture.architecture_status_report.
This shim re-exports everything for backward compatibility.
"""
# ruff: noqa: F401
from tools.architecture.architecture_status_report import *  # noqa: F401, F403
try:
    from tools.architecture.architecture_status_report import __all__
except ImportError:
    pass
