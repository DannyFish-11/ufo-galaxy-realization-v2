"""
core/legacy — Legacy Compatibility and Adapter Layer
======================================================
Canonical legacy location. Legacy adapters live in core.legacy_adapters
for now; this package provides the forward-looking namespace.
"""
from core import legacy_adapters as adapters  # noqa: F401

__all__ = ["adapters"]
