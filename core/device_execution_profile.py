#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — DeviceExecutionProfile
================================

Canonical schema describing what remote execution capabilities a target device
supports.  This profile is the authoritative source of truth consumed by
:mod:`core.remote_execution_mode_resolver` to determine whether a target
should be approached via the ``agent_runtime`` or ``command_only`` execution
style.

Design notes
------------
- **Additive only** — does not modify any existing module.
- **Serialisable** — :meth:`DeviceExecutionProfile.to_dict` produces a stable,
  round-trippable dict suitable for wire transfer or logging.
- **Graceful defaults** — all fields beyond the bare minimum are optional so
  that callers with partial device information can still construct a valid
  profile that resolves to a safe fallback mode.
- **Future-friendly** — :attr:`metadata` carries arbitrary extension data
  without requiring schema changes.

Profile classes
---------------
``rich``
    Full-capability target (phone, tablet, PC) that can host a remote agent
    runtime.  Supports both :attr:`~RemoteExecutionMode.agent_runtime` and
    :attr:`~RemoteExecutionMode.command_only`.
``thin``
    Lightweight / constrained target (drone, IoT sensor, kiosk) that can only
    receive structured commands.  Resolves exclusively to
    :attr:`~RemoteExecutionMode.command_only`.

Usage::

    from core.device_execution_profile import (
        DeviceExecutionProfile,
        DeviceProfileClass,
        build_profile_from_device_info,
    )

    profile = build_profile_from_device_info({"capabilities": ["screen", "touch"]})
    print(profile.profile_class)          # DeviceProfileClass.rich
    print(profile.supported_modes)        # ['agent_runtime', 'command_only']
    print(profile.preferred_mode)         # 'agent_runtime'
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DeviceProfileClass(str, Enum):
    """Coarse classification of a device's execution capacity.

    Attributes
    ----------
    rich:
        High-capability target (smartphone, tablet, desktop) that can run a
        full remote agent runtime alongside structured-command dispatch.
    thin:
        Resource-constrained target (drone, IoT node, embedded MCU) that
        supports only structured command dispatch.
    unknown:
        Capability information is absent or incomplete.  The resolver will
        default to ``command_only`` when this class is set.
    """

    rich = "rich"
    thin = "thin"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Core schema
# ---------------------------------------------------------------------------


class DeviceExecutionProfile(BaseModel):
    """Execution capability profile for a single remote target device.

    Parameters
    ----------
    device_id:
        Stable identifier for the target device.  May be ``None`` when the
        profile is constructed speculatively (e.g. from a device-type hint
        before a live device is selected).
    profile_class:
        Coarse classification used by the resolver as a fast path.
    supports_agent_runtime:
        True when the device can host a remote agent execution session
        (``agent_execute`` / ``agent_deploy`` payloads).
    supports_command_only:
        True when the device accepts structured gateway commands.  Nearly
        always ``True``; ``False`` only for purely-read-only telemetry nodes.
    supported_modes:
        Explicit list of ``RemoteExecutionMode`` values (as stable strings)
        that the device supports.  Populated automatically by
        :meth:`derive_supported_modes` if left empty.
    preferred_mode:
        The resolver's preferred execution mode for this device when the
        task context does not force a specific choice.  Defaults to
        ``"agent_runtime"`` for ``rich`` profiles and ``"command_only"`` for
        all others.
    capabilities:
        Raw capability strings declared by the device (e.g. ``"screen"``,
        ``"touch"``, ``"camera"``).  These mirror the strings used by
        :class:`~core.control_plane.smart_scheduler.DeviceScoreInput`.
    device_type:
        Free-form device type label (e.g. ``"android"``, ``"windows"``,
        ``"drone"``, ``"iot"``).  Informational; used by
        :func:`build_profile_from_device_info` for heuristic classification.
    metadata:
        Arbitrary extension data for future requirements.
    """

    device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier for the target device.",
    )
    profile_class: DeviceProfileClass = Field(
        default=DeviceProfileClass.unknown,
        description="Coarse classification of the device's execution capacity.",
    )
    supports_agent_runtime: bool = Field(
        default=False,
        description="True when the device can host a remote agent runtime.",
    )
    supports_command_only: bool = Field(
        default=True,
        description="True when the device accepts structured gateway commands.",
    )
    supported_modes: List[str] = Field(
        default_factory=list,
        description=(
            "Explicit list of RemoteExecutionMode values supported by this device. "
            "Populated lazily via derive_supported_modes()."
        ),
    )
    preferred_mode: Optional[str] = Field(
        default=None,
        description=(
            "Preferred execution mode for this device when task context is neutral. "
            "'agent_runtime' for rich profiles; 'command_only' for thin/unknown."
        ),
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="Raw capability strings declared by the device.",
    )
    device_type: Optional[str] = Field(
        default=None,
        description="Free-form device type label (android, windows, drone, iot, …).",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension data for future requirements.",
    )

    model_config = {"use_enum_values": True}

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def derive_supported_modes(self) -> List[str]:
        """Return the list of supported ``RemoteExecutionMode`` strings.

        Populates :attr:`supported_modes` in-place and returns the list so
        callers can chain::

            modes = profile.derive_supported_modes()
        """
        modes: List[str] = []
        if self.supports_agent_runtime:
            modes.append("agent_runtime")
        if self.supports_command_only:
            modes.append("command_only")
        self.supported_modes = modes
        return modes

    def is_agent_runtime_capable(self) -> bool:
        """True when the device can execute agent_runtime tasks."""
        return bool(self.supports_agent_runtime)

    def is_command_only_capable(self) -> bool:
        """True when the device can accept command_only dispatch."""
        return bool(self.supports_command_only)

    def supports_mode(self, mode: str) -> bool:
        """Return True when *mode* (as a string value) is supported.

        Parameters
        ----------
        mode:
            A ``RemoteExecutionMode`` value string, e.g. ``"agent_runtime"``.
        """
        if not self.supported_modes:
            self.derive_supported_modes()
        return mode in self.supported_modes

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, serialisable representation of this profile."""
        if not self.supported_modes:
            self.derive_supported_modes()
        return self.model_dump()


# ---------------------------------------------------------------------------
# Profile builders / factories
# ---------------------------------------------------------------------------

#: Capability names that strongly indicate a rich (agent_runtime-capable) device.
_RICH_CAPABILITY_HINTS: frozenset = frozenset({
    "screen",
    "touch",
    "keyboard",
    "camera",
    "microphone",
    "display",
    "agent_runtime",
    "execute_agent",
})

#: Device-type strings that indicate a thin (command_only) device.
_THIN_DEVICE_TYPES: frozenset = frozenset({
    "drone",
    "iot",
    "sensor",
    "embedded",
    "kiosk",
    "mcu",
    "rpi",
    "raspberrypi",
    "arduino",
})

#: Device-type strings that indicate a rich device.
_RICH_DEVICE_TYPES: frozenset = frozenset({
    "android",
    "ios",
    "windows",
    "macos",
    "linux",
    "phone",
    "tablet",
    "desktop",
    "laptop",
    "pc",
})


def _classify_from_info(
    capabilities: List[str],
    device_type: Optional[str],
) -> DeviceProfileClass:
    """Heuristically classify a device as rich/thin/unknown.

    Priority order:
    1. Explicit ``"agent_runtime"`` or ``"execute_agent"`` capability → rich.
    2. Device-type label in ``_THIN_DEVICE_TYPES`` → thin.
    3. Device-type label in ``_RICH_DEVICE_TYPES`` → rich.
    4. Any capability from ``_RICH_CAPABILITY_HINTS`` → rich.
    5. Default → unknown.
    """
    cap_set = {c.lower() for c in capabilities}

    # Explicit agent capability is the strongest signal
    if cap_set & {"agent_runtime", "execute_agent"}:
        return DeviceProfileClass.rich

    # Device-type based classification
    if device_type:
        dt_lower = device_type.lower()
        if dt_lower in _THIN_DEVICE_TYPES:
            return DeviceProfileClass.thin
        if dt_lower in _RICH_DEVICE_TYPES:
            return DeviceProfileClass.rich

    # Capability-based heuristic
    if cap_set & _RICH_CAPABILITY_HINTS:
        return DeviceProfileClass.rich

    return DeviceProfileClass.unknown


def build_profile_from_device_info(
    device_info: Dict[str, Any],
    device_id: Optional[str] = None,
) -> "DeviceExecutionProfile":
    """Construct a :class:`DeviceExecutionProfile` from a raw device-info dict.

    This factory is the standard entry point when a live device record is
    available (e.g. from ``connection_manager.get_all_devices()``).

    Parameters
    ----------
    device_info:
        Raw device-info dict as stored by the connection manager.  Expected
        keys include ``"capabilities"``, ``"device_type"``, and optional
        ``"execution_profile"`` (pre-built profile dict for fast path).
    device_id:
        Device identifier; overrides ``device_info.get("device_id")``.

    Returns
    -------
    DeviceExecutionProfile
    """
    # Fast path: caller already computed a profile dict
    pre_built = device_info.get("execution_profile")
    if isinstance(pre_built, DeviceExecutionProfile):
        return pre_built
    if isinstance(pre_built, dict) and pre_built:
        try:
            return DeviceExecutionProfile.model_validate(pre_built)
        except Exception as exc:
            logging.warning("Exception suppressed: %s", exc)

    did = device_id or device_info.get("device_id") or device_info.get("id")

    # Normalise capabilities list
    raw_caps = device_info.get("capabilities", [])
    if isinstance(raw_caps, list):
        caps: List[str] = [
            c if isinstance(c, str) else (c.get("name", "") if isinstance(c, dict) else str(c))
            for c in raw_caps
        ]
    else:
        caps = []
    caps = [c for c in caps if c]  # drop empty strings

    device_type: Optional[str] = device_info.get("device_type") or device_info.get("type")

    profile_class = _classify_from_info(caps, device_type)

    supports_agent = profile_class == DeviceProfileClass.rich
    supports_cmd = True  # all devices support command_only by default

    preferred: str
    if profile_class == DeviceProfileClass.rich:
        preferred = "agent_runtime"
    else:
        preferred = "command_only"

    profile = DeviceExecutionProfile(
        device_id=did,
        profile_class=profile_class,
        supports_agent_runtime=supports_agent,
        supports_command_only=supports_cmd,
        preferred_mode=preferred,
        capabilities=caps,
        device_type=device_type,
        metadata={
            "source": "build_profile_from_device_info",
        },
    )
    profile.derive_supported_modes()
    return profile


def build_thin_profile(
    device_id: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    device_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "DeviceExecutionProfile":
    """Convenience factory for an explicitly thin device profile.

    Thin profiles always resolve to ``command_only``.
    """
    profile = DeviceExecutionProfile(
        device_id=device_id,
        profile_class=DeviceProfileClass.thin,
        supports_agent_runtime=False,
        supports_command_only=True,
        preferred_mode="command_only",
        capabilities=list(capabilities or []),
        device_type=device_type,
        metadata=dict(metadata or {}),
    )
    profile.derive_supported_modes()
    return profile


def build_rich_profile(
    device_id: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    device_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "DeviceExecutionProfile":
    """Convenience factory for an explicitly rich device profile.

    Rich profiles prefer ``agent_runtime`` but also support ``command_only``.
    """
    profile = DeviceExecutionProfile(
        device_id=device_id,
        profile_class=DeviceProfileClass.rich,
        supports_agent_runtime=True,
        supports_command_only=True,
        preferred_mode="agent_runtime",
        capabilities=list(capabilities or []),
        device_type=device_type,
        metadata=dict(metadata or {}),
    )
    profile.derive_supported_modes()
    return profile


def build_unknown_profile(
    device_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "DeviceExecutionProfile":
    """Convenience factory for a profile with no capability information.

    Unknown profiles resolve conservatively to ``command_only``.
    """
    profile = DeviceExecutionProfile(
        device_id=device_id,
        profile_class=DeviceProfileClass.unknown,
        supports_agent_runtime=False,
        supports_command_only=True,
        preferred_mode="command_only",
        metadata=dict(metadata or {}),
    )
    profile.derive_supported_modes()
    return profile
