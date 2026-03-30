"""
galaxy_gateway/legacy/capability_registry.py — Canonical legacy location.

Legacy capability registry. Use core.capability_runtime for new work.
"""
from galaxy_gateway.capability_registry import *  # noqa: F401, F403
try:
    from galaxy_gateway.capability_registry import __all__
except ImportError:
    pass
