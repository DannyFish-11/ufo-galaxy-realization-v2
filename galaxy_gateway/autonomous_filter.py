"""
Autonomous-first device filter for Galaxy Gateway.
====================================================

Provides priority filtering for autonomous-capable devices with a safe
fallback to legacy routing when no qualifying devices are available.

Autonomous criteria (all must be true for a device to be preferred):
  - status == "online"
  - goal_execution_enabled == true  (in device metadata)
  - parallel_execution_enabled == true  (in device metadata)
  - cross_device_enabled == true  (only when *require_cross_device* is True)
  - device_role matches *task_role*  (only when *task_role* is provided)

Missing metadata fields are treated as False for backward compatibility.

Config flag ``prefer_autonomous`` (default ``True``) can be used to disable
this prioritisation globally while keeping the code path active; when
``False``, the filter returns all online devices unchanged.

Usage::

    from galaxy_gateway.autonomous_filter import filter_autonomous_devices

    preferred = filter_autonomous_devices(
        devices,
        get_metadata=lambda d: d.metadata,
        get_status=lambda d: d.status,
        require_cross_device=False,
        task_role=None,
    )
    # preferred is never empty if any online device exists
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def _prefer_autonomous() -> bool:
    """Return the ``prefer_autonomous`` config flag (default ``True``)."""
    try:
        from core.unified_config import config
        val = config.get("prefer_autonomous", default=True)
        if val is None:
            return True
        return bool(val)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Per-device check
# ---------------------------------------------------------------------------

def is_autonomous_device(
    metadata: Dict[str, Any],
    *,
    require_cross_device: bool = False,
    task_role: Optional[str] = None,
) -> bool:
    """Return ``True`` when *metadata* satisfies autonomous-execution criteria.

    Both ``None`` and an empty ``{}`` dict are treated as non-autonomous
    (backward-compatible default: any missing flag is considered ``False``).

    Args:
        metadata: Free-form dict attached to a device (may be None or empty).
        require_cross_device: When ``True``, ``cross_device_enabled`` must
            also be ``True`` in the metadata.
        task_role: When supplied, the device's ``device_role`` must match
            (or the device must not declare a role at all).

    Returns:
        ``True`` if the device qualifies as autonomous for the given task.
    """
    if not metadata:
        return False
    if not metadata.get("goal_execution_enabled", False):
        return False
    if not metadata.get("parallel_execution_enabled", False):
        return False
    if require_cross_device and not metadata.get("cross_device_enabled", False):
        return False
    if task_role is not None:
        dev_role = metadata.get("device_role")
        # A device with no role declaration is considered compatible; a device
        # with an explicit role must match the requested role.
        if dev_role is not None and dev_role != task_role:
            return False
    return True


# ---------------------------------------------------------------------------
# Collection-level filter with fallback
# ---------------------------------------------------------------------------

def filter_autonomous_devices(
    devices: Sequence[T],
    *,
    get_metadata: Callable[[T], Dict[str, Any]],
    get_status: Callable[[T], str],
    require_cross_device: bool = False,
    task_role: Optional[str] = None,
) -> List[T]:
    """Filter *devices* to prefer autonomous-capable, online devices.

    Behaviour:
    1. If the ``prefer_autonomous`` config flag is ``False``, return all online
       devices without autonomous filtering.
    2. Otherwise, collect online devices that pass :func:`is_autonomous_device`.
    3. If the autonomous subset is non-empty, return it.
    4. If no autonomous devices are found but online devices exist, emit a
       WARNING (downgrade message) and return all online devices so that the
       caller can fall back to legacy routing without failing the request.
    5. If no online devices exist at all, return an empty list.

    Args:
        devices: Iterable of device objects (any type).
        get_metadata: Callable that extracts a ``dict`` from a device.
        get_status: Callable that returns the device status string.
        require_cross_device: Forward to :func:`is_autonomous_device`.
        task_role: Forward to :func:`is_autonomous_device`.

    Returns:
        List of device objects (may be empty only when no online device exists).
    """
    online: List[T] = [d for d in devices if get_status(d) == "online"]

    if not _prefer_autonomous():
        return online

    autonomous: List[T] = [
        d for d in online
        if is_autonomous_device(
            get_metadata(d),
            require_cross_device=require_cross_device,
            task_role=task_role,
        )
    ]

    if autonomous:
        return autonomous

    if online:
        logger.warning(
            "autonomous-first: no autonomous devices satisfy criteria "
            "(goal_execution_enabled+parallel_execution_enabled%s%s); "
            "downgrading to legacy routing with %d online device(s).",
            "+cross_device_enabled" if require_cross_device else "",
            f"+role={task_role}" if task_role else "",
            len(online),
        )
        return online

    return []
