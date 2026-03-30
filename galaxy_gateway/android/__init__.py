"""
galaxy_gateway/android — Android Bridge and Transport Package
==============================================================

This package provides Android device bridge, transport, and adapter logic
for the galaxy gateway.

The primary implementation is in ``galaxy_gateway.android_bridge``
(the original module), which is re-exported here for the new canonical
package path.

For new code, prefer importing from ``galaxy_gateway.android`` rather than
``galaxy_gateway.android_bridge`` directly.
"""
from galaxy_gateway.android_bridge import AndroidBridge  # noqa: F401

try:
    from galaxy_gateway.android_bridge import __all__
except ImportError:
    __all__ = ["AndroidBridge"]
