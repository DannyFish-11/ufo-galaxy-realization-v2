"""
core/device_policy.py
=====================
Device-type policy for the Galaxy agent dispatch pipeline.

Defines which device types are considered "physical/electronic" and
therefore require a mandatory agent pre-deploy step before any task
execution.  All routing logic should call :func:`requires_agent_deploy`
rather than duplicating the type-set locally.

Physical device types (scheme A – strictest, all hardware):
  ANDROID / IOS / WINDOWS / MACOS / LINUX / IOT / ROBOT / DRONE

Non-physical targets (cloud, browser, unknown, …) keep the existing
direct task-routing behaviour.
"""

from __future__ import annotations

# ============================================================================
# Policy constants
# ============================================================================

#: Set of normalised (upper-case) device type strings that represent
#: physical or electronic hardware and therefore require an agent
#: pre-deploy step before task execution.
PHYSICAL_DEVICE_TYPES: frozenset[str] = frozenset({
    "ANDROID",
    "IOS",
    "WINDOWS",
    "MACOS",
    "LINUX",
    "IOT",
    "ROBOT",
    "DRONE",
})


# ============================================================================
# Policy helpers
# ============================================================================

def is_physical_device(device_type: str) -> bool:
    """Return *True* if *device_type* represents a physical/electronic device.

    The comparison is case-insensitive.  ``None`` or empty strings return
    ``False``.

    Parameters
    ----------
    device_type:
        Device-type string as stored in :class:`~core.unified.models.UnifiedDevice`
        or returned by :func:`~core.unified.device_manager.UnifiedDeviceManager.get_device_type`.

    Examples
    --------
    >>> is_physical_device("android")
    True
    >>> is_physical_device("WINDOWS")
    True
    >>> is_physical_device("cloud")
    False
    >>> is_physical_device("")
    False
    """
    if not device_type:
        return False
    return device_type.strip().upper() in PHYSICAL_DEVICE_TYPES


def requires_agent_deploy(device_type: str) -> bool:
    """Return *True* when the given device type mandates a mandatory
    ``agent_deploy`` step prior to ``agent_execute``.

    This is the single authoritative policy gate.  All dispatch code must
    call this function instead of performing ad-hoc checks.

    Parameters
    ----------
    device_type:
        Normalised device-type string (case-insensitive).

    Returns
    -------
    bool
        ``True``  → caller must issue ``agent_deploy`` before ``agent_execute``.
        ``False`` → caller may route the task directly.
    """
    return is_physical_device(device_type)
