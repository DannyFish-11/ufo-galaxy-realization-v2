"""
core/architecture_invariants.py — Compatibility shim.

This module has been moved to ``tools.architecture.architecture_invariants``.
This shim re-exports everything (including private names) for full backward
compatibility. Old import paths continue to work without changes.
"""
import sys as _sys
import importlib as _importlib

# Load the canonical implementation from its new location.
_real = _importlib.import_module("tools.architecture.architecture_invariants")

# Replace this entry in sys.modules so that all attribute accesses
# (including private names like _classify_readiness) resolve correctly.
_sys.modules[__name__] = _real
