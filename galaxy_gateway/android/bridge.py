"""
galaxy_gateway/android/bridge.py — Android Bridge (package entry point).

After PR-3 modularization, this module re-exports the key components
from their canonical locations for backward compatibility.
"""
# Core components now live in dedicated sub-modules.
from galaxy_gateway.android.capabilities import DeviceCapability  # noqa: F401
from galaxy_gateway.android.models import Rect, UIElement, AndroidDevice  # noqa: F401
from galaxy_gateway.android.message_builder import MessageBuilder  # noqa: F401

# AndroidBridge is still in the top-level android_bridge module.
from galaxy_gateway.android_bridge import AndroidBridge, android_bridge  # noqa: F401
