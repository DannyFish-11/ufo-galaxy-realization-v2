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
PHYSICAL_DEVICE_TYPES: frozenset[str] = frozenset(
    {
        "ANDROID",
        "IOS",
        "WINDOWS",
        "MACOS",
        "LINUX",
        "IOT",
        "ROBOT",
        "DRONE",
    }
)


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


# ============================================================================
# Per-device dispatch policy (dimension 8 of the canonical dispatch slot chain)
# ============================================================================

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceDispatchPolicy:
    """单台设备的派发策略(canonical_dispatch_slot_authority 维度 8 消费)。

    策略真相从 UDM(设备身份 SSOT)的 metadata 派生——运维/面板可通过设备
    metadata 打 ``dispatch_allowed`` / ``disabled`` / ``maintenance_mode``
    标记来临时禁派某台设备,默认全部允许。
    """

    device_id: str
    dispatch_allowed: bool = True
    disabled: bool = False
    maintenance_mode: bool = False


def get_device_policy(device_id: str) -> DeviceDispatchPolicy:
    """Return the per-device dispatch policy derived from UDM metadata.

    未注册设备返回默认(允许)策略——注册性检查由槽位链其它维度负责,
    本维度只回答"策略是否明确禁止"。
    """
    meta = {}
    try:
        from core.unified.device_manager import get_unified_device_manager

        device = get_unified_device_manager().get_device(device_id)
        meta = dict(getattr(device, "metadata", None) or {}) if device is not None else {}
    except Exception:  # pragma: no cover - UDM 不可用时按默认允许
        meta = {}

    def _flag(key: str, default: bool) -> bool:
        val = meta.get(key, default)
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes")
        return bool(val)

    return DeviceDispatchPolicy(
        device_id=device_id,
        dispatch_allowed=_flag("dispatch_allowed", True),
        disabled=_flag("disabled", False),
        maintenance_mode=_flag("maintenance_mode", False),
    )
