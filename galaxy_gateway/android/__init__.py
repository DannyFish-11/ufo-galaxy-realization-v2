"""
galaxy_gateway/android — Android Bridge and Transport Package
==============================================================

This package provides Android device bridge, transport, and adapter logic
for the galaxy gateway.

After PR-3 modularization, the canonical sub-modules are:
  - galaxy_gateway.android.capabilities  — DeviceCapability
  - galaxy_gateway.android.models        — Rect, UIElement, AndroidDevice
  - galaxy_gateway.android.message_builder — MessageBuilder
  - galaxy_gateway.android.handlers.*   — isolated handler functions

The ``AndroidBridge`` class lives in ``galaxy_gateway.android_bridge``
and is imported lazily here to avoid circular imports.
"""
from galaxy_gateway.android.capabilities import DeviceCapability  # noqa: F401
from galaxy_gateway.android.models import Rect, UIElement, AndroidDevice  # noqa: F401
from galaxy_gateway.android.message_builder import MessageBuilder  # noqa: F401


def _get_android_bridge_class():
    """Lazy import to avoid circular imports."""
    from galaxy_gateway import android_bridge as _mod
    return _mod.AndroidBridge


__all__ = [
    "DeviceCapability",
    "Rect",
    "UIElement",
    "AndroidDevice",
    "MessageBuilder",
]
