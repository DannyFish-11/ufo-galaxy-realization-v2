"""
core/architecture_status_report.py — Compatibility shim.

This module has been moved to ``tools.architecture.architecture_status_report``.
This shim re-exports everything (including private names) for full backward
compatibility. Old import paths continue to work without changes.

.. deprecated::
    Import from ``tools.architecture.architecture_status_report`` directly.
    This shim will be removed in a future release.
"""
import sys as _sys
import importlib as _importlib
import warnings as _warnings

_warnings.warn(
    "core.architecture_status_report is a compatibility shim and will be removed "
    "in a future release. Import from tools.architecture.architecture_status_report instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Load the canonical implementation from its new location.
_real = _importlib.import_module("tools.architecture.architecture_status_report")

# Replace this entry in sys.modules so that all attribute accesses
# (including private names like _classify_readiness) resolve correctly.
_sys.modules[__name__] = _real
