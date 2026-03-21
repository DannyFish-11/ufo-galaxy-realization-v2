#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cross_device_policy.device_role
======================================

PR-13 (V4) — Cross-Device Role & Routing Policy

Defines the **device-role taxonomy** for cross-device task assignments in the
Galaxy runtime.  Each device participating in a ``cross_device`` runtime
domain is assigned exactly one :class:`DeviceRole` that describes its
functional relationship to the overall task.

Role Definitions
----------------
+-----------------------------+------------------------------------------------+
| Role                        | Meaning                                        |
+=============================+================================================+
| SOURCE                      | Device that originated the request.  May not  |
|                             | be the executor.                               |
+-----------------------------+------------------------------------------------+
| PRIMARY_EXECUTION           | Device primarily responsible for executing the |
|                             | task.  Exactly one device should hold this     |
|                             | role per task (or per split branch).           |
+-----------------------------+------------------------------------------------+
| SUPPORT                     | Assists the primary executor with a specific   |
|                             | capability (e.g. camera, microphone, extra     |
|                             | compute).  May perform sub-steps.              |
+-----------------------------+------------------------------------------------+
| OBSERVER                    | Receives a read-only view of task progress and |
|                             | results.  Does not perform any execution.      |
+-----------------------------+------------------------------------------------+
| RELAY                       | Forwards commands/data between devices without |
|                             | executing itself (e.g. gateway node).          |
+-----------------------------+------------------------------------------------+
| FALLBACK                    | Eligible to take over PRIMARY_EXECUTION if the |
|                             | primary device becomes unavailable.            |
+-----------------------------+------------------------------------------------+
| UNASSIGNED                  | Device is in the task roster but has not yet   |
|                             | been assigned a role (provisional state).      |
+-----------------------------+------------------------------------------------+

These definitions are **additive** — they do not modify any existing device
management, TaskGraph, or orchestration modules.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "DeviceRole",
    "ROLE_PRECEDENCE",
    "role_description",
    "DeviceRoleAssignment",
]


# ---------------------------------------------------------------------------
# Device role enum
# ---------------------------------------------------------------------------


class DeviceRole(str, Enum):
    """Taxonomy of participation roles for devices in a cross-device task.

    String values are stable identifiers safe for serialisation, logging, and
    API responses.
    """

    SOURCE = "source_device"
    """Device that originated the request."""

    PRIMARY_EXECUTION = "primary_execution_device"
    """Device primarily responsible for executing the task."""

    SUPPORT = "support_device"
    """Assists the primary executor with a specific capability."""

    OBSERVER = "observer_device"
    """Receives read-only view of task progress.  No execution."""

    RELAY = "relay_device"
    """Forwards commands/data; does not execute itself."""

    FALLBACK = "fallback_device"
    """Eligible to take over if the primary device is unavailable."""

    UNASSIGNED = "unassigned"
    """Device is in the roster but not yet assigned a role."""


# ---------------------------------------------------------------------------
# Role metadata
# ---------------------------------------------------------------------------

_ROLE_DESCRIPTIONS: Dict[str, str] = {
    DeviceRole.SOURCE.value: (
        "Originated the request.  May be the same device as PRIMARY_EXECUTION "
        "for local tasks, or a different device when the request crosses device "
        "boundaries."
    ),
    DeviceRole.PRIMARY_EXECUTION.value: (
        "Primarily responsible for executing the task.  Exactly one device "
        "should hold this role per task (or per split execution branch).  "
        "Receives the full task envelope."
    ),
    DeviceRole.SUPPORT.value: (
        "Assists the primary executor with a specific capability (camera, "
        "microphone, extra compute, specialist sensor).  May perform designated "
        "sub-steps under direction of the primary executor."
    ),
    DeviceRole.OBSERVER.value: (
        "Receives a read-only view of task progress and results.  Does not "
        "perform any execution.  Suitable for status boards and companion "
        "screens."
    ),
    DeviceRole.RELAY.value: (
        "Forwards commands and data between devices without executing tasks "
        "itself.  Typical for gateway nodes or protocol-bridging devices."
    ),
    DeviceRole.FALLBACK.value: (
        "Eligible to assume PRIMARY_EXECUTION if the current primary device "
        "becomes unavailable or exceeds its action budget.  Promoted by the "
        "routing resolver when conditions are met."
    ),
    DeviceRole.UNASSIGNED.value: (
        "Device is included in the task roster but has not yet been assigned a "
        "concrete participation role.  Provisional state pending policy "
        "resolution."
    ),
}

#: Precedence order from most authoritative to least.
#: Used by resolvers to select the 'most significant' role when a device
#: appears in multiple contexts.
ROLE_PRECEDENCE: List[DeviceRole] = [
    DeviceRole.PRIMARY_EXECUTION,
    DeviceRole.FALLBACK,
    DeviceRole.SUPPORT,
    DeviceRole.RELAY,
    DeviceRole.OBSERVER,
    DeviceRole.SOURCE,
    DeviceRole.UNASSIGNED,
]


def role_description(role: DeviceRole) -> str:
    """Return the human-readable description for *role*."""
    return _ROLE_DESCRIPTIONS.get(role.value, "Unknown role.")


# ---------------------------------------------------------------------------
# DeviceRoleAssignment dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DeviceRoleAssignment:
    """A single device's participation record in a cross-device task.

    Attributes
    ----------
    device_id:
        Stable identifier of the participating device (e.g. UDM device ID,
        hostname, or generated UUID).  May be ``None`` for placeholder / yet-
        to-be-selected assignments.
    role:
        The :class:`DeviceRole` this device is assigned.
    reason:
        Human-readable explanation of why this role was assigned.
        Suitable for logging, dashboards, and downstream hints.
    capabilities:
        Optional list of capability strings that justify the role assignment
        (e.g. ``["camera", "microphone"]`` for a SUPPORT device).
    is_local:
        True if this device is the local device running the current runtime
        session.  Helps downstream systems distinguish self-assignments from
        remote assignments.
    """

    device_id: Optional[str] = None
    role: DeviceRole = DeviceRole.UNASSIGNED
    reason: str = "unassigned"
    capabilities: List[str] = dataclasses.field(default_factory=list)
    is_local: bool = False

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "device_id": self.device_id,
            "role": self.role.value,
            "reason": self.reason,
            "capabilities": list(self.capabilities),
            "is_local": self.is_local,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceRoleAssignment":
        """Reconstruct a :class:`DeviceRoleAssignment` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        try:
            role = DeviceRole(data.get("role", DeviceRole.UNASSIGNED.value))
        except (ValueError, KeyError):
            role = DeviceRole.UNASSIGNED

        return cls(
            device_id=data.get("device_id"),
            role=role,
            reason=str(data.get("reason", "reconstructed from dict")),
            capabilities=list(data.get("capabilities", [])),
            is_local=bool(data.get("is_local", False)),
        )

    def __repr__(self) -> str:
        return (
            f"<DeviceRoleAssignment "
            f"device={self.device_id!r} "
            f"role={self.role.value} "
            f"local={self.is_local}>"
        )
