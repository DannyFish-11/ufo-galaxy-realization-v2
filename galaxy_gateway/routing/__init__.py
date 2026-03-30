"""galaxy_gateway/routing — Routing concern sub-modules.

This package separates the routing and dispatch responsibilities that were
previously mixed in ``galaxy_gateway/device_router.py``:

- ``health_policy``   — device availability / health gating
- ``device_selection`` — which devices are eligible for a task
- ``policy``          — routing policy decisions (command analysis, strategy)
- ``dispatch``        — sending tasks/commands to devices via WebSocket
- ``router``          — thin orchestrating entry-point

``DeviceRouter`` in ``galaxy_gateway/device_router.py`` delegates to these
modules; external callers that already depend on ``DeviceRouter`` are
unaffected.
"""

from galaxy_gateway.routing.health_policy import (
    DEVICE_HEALTH_POLICY_AUTHORITY,
    is_device_available,
    is_device_online,
    filter_eligible_devices,
)
from galaxy_gateway.routing.device_selection import (
    DEVICE_SELECTION_AUTHORITY,
    select_devices,
)
from galaxy_gateway.routing.policy import (
    ROUTING_POLICY_AUTHORITY,
    analyze_command,
)
from galaxy_gateway.routing.dispatch import (
    DISPATCH_AUTHORITY,
    build_aip_message,
    dispatch_to_websocket,
)

__all__ = [
    # health_policy
    "DEVICE_HEALTH_POLICY_AUTHORITY",
    "is_device_available",
    "is_device_online",
    "filter_eligible_devices",
    # device_selection
    "DEVICE_SELECTION_AUTHORITY",
    "select_devices",
    # policy
    "ROUTING_POLICY_AUTHORITY",
    "analyze_command",
    # dispatch
    "DISPATCH_AUTHORITY",
    "build_aip_message",
    "dispatch_to_websocket",
]
