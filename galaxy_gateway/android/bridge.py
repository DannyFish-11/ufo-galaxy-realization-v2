"""
galaxy_gateway/android/bridge.py — Android Bridge (package entry point).

The canonical implementation lives in ``galaxy_gateway.android_bridge``.
This module re-exports the bridge for the package-based import path.
"""
from galaxy_gateway.android_bridge import *  # noqa: F401, F403
try:
    from galaxy_gateway.android_bridge import __all__
except ImportError:
    pass
