"""
galaxy_gateway/android/bridge.py — Android Bridge (secondary re-export surface).

Batch PR-6: canonical path declaration
---------------------------------------
This module is the **secondary re-export surface** for ``AndroidBridge``.
It is explicitly marked as secondary — ``galaxy_gateway.android_bridge`` is the
implementation authority (ANDROID_BRIDGE_IMPL_AUTHORITY), and this module
merely re-exports for caller convenience.

New code should import from ``galaxy_gateway.android`` (the package __init__)
or directly from ``galaxy_gateway.android.bridge``.  Direct imports from
``galaxy_gateway.android_bridge`` remain valid but are the internal surface.
"""
# Core components now live in dedicated sub-modules.
from galaxy_gateway.android.capabilities import DeviceCapability  # noqa: F401
from galaxy_gateway.android.models import Rect, UIElement, AndroidDevice  # noqa: F401
from galaxy_gateway.android.message_builder import MessageBuilder  # noqa: F401

# AndroidBridge is still in the top-level android_bridge module.
from galaxy_gateway.android_bridge import (  # noqa: F401
    AndroidBridge,
    android_bridge,
    ANDROID_BRIDGE_IMPL_AUTHORITY,
    ANDROID_BRIDGE_CANONICAL_PATH,
)

# Batch PR-6: explicit marker that this module is a secondary re-export surface.
ANDROID_BRIDGE_REEXPORT_SURFACE = "galaxy_gateway.android.bridge"
"""Sentinel: this module (galaxy_gateway.android.bridge) is the secondary
re-export surface for AndroidBridge.  It is explicitly NOT the implementation
authority — that is galaxy_gateway.android_bridge (ANDROID_BRIDGE_IMPL_AUTHORITY).
"""

__all__ = [
    "DeviceCapability",
    "Rect",
    "UIElement",
    "AndroidDevice",
    "MessageBuilder",
    "AndroidBridge",
    "android_bridge",
    "ANDROID_BRIDGE_IMPL_AUTHORITY",
    "ANDROID_BRIDGE_CANONICAL_PATH",
    "ANDROID_BRIDGE_REEXPORT_SURFACE",
]
