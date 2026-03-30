"""galaxy_gateway/routing/health_policy.py — Device health / availability gating.

This module owns the decision of whether a device is eligible to receive a
task based on its current runtime health state.  It is intentionally separate
from device *selection* (which device to pick) and *dispatch* (how to send).

Separation of concerns
-----------------------
- ``is_device_available`` — does the device have an active transport session?
- ``is_device_online``    — is the device's declared status "online"?
- ``filter_eligible_devices`` — apply health gating across a list of devices.

These functions are consumed by ``galaxy_gateway.routing.device_selection``
and directly by ``DeviceRouter`` for fallback checks.
"""

from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level authority sentinel (mirrors the pattern in device_router.py)
# ---------------------------------------------------------------------------

DEVICE_HEALTH_POLICY_AUTHORITY = "galaxy_gateway.routing.health_policy"
"""Sentinel string identifying this module as the health-gating authority."""


# ---------------------------------------------------------------------------
# Health / availability predicates
# ---------------------------------------------------------------------------


def is_device_available(device: Any) -> bool:
    """Return ``True`` when *device* has an active transport (WebSocket) session.

    A device is considered *available* if its ``websocket`` attribute is not
    ``None``.  This is a transport-level liveness check distinct from the
    device's declared online/offline status.

    Args:
        device: Any object exposing a ``websocket`` attribute (typically a
                ``galaxy_gateway.device_router.Device`` instance).

    Returns:
        ``True`` if ``device.websocket`` is not ``None``, ``False`` otherwise.
    """
    return getattr(device, "websocket", None) is not None


def is_device_online(device: Any) -> bool:
    """Return ``True`` when *device* reports an "online" status.

    Checks the ``status`` attribute of *device* against the canonical
    ``"online"`` string value.  Both plain string and enum-with-value forms
    are handled.

    Args:
        device: Any object exposing a ``status`` attribute.

    Returns:
        ``True`` if the status value is ``"online"``, ``False`` otherwise.
    """
    status = getattr(device, "status", None)
    if status is None:
        return False
    status_str = status.value if hasattr(status, "value") else str(status)
    return status_str.lower() == "online"


def filter_eligible_devices(devices: List[Any]) -> List[Any]:
    """Return the subset of *devices* that are currently online.

    This is the primary health-gating step applied before device selection.
    Only devices whose ``status`` is ``"online"`` are eligible.

    Args:
        devices: Iterable of device objects to evaluate.

    Returns:
        A new list containing only the devices that pass ``is_device_online``.
    """
    eligible = [d for d in devices if is_device_online(d)]
    if len(eligible) < len(devices):
        logger.debug(
            "filter_eligible_devices: %d/%d devices are online",
            len(eligible),
            len(devices),
        )
    return eligible
