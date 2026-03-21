#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation.formation_role
======================================

PR-17 (V4) — Device Formation & Multi-Device Group Model

Defines the **formation-member role taxonomy** for devices participating in a
multi-device execution formation.  These roles are additive on top of the
existing :class:`~core.cross_device_policy.DeviceRole` from PR-13 and express
**formation-level** participation semantics (who owns what responsibility in
the group), rather than routing-level semantics (how the task is dispatched).

Role Definitions
----------------
+-----------------------------+---------------------------------------------------+
| Role                        | Meaning                                           |
+=============================+===================================================+
| SOURCE                      | Device that originated the cross-device request.  |
|                             | The request entered the formation from here.      |
+-----------------------------+---------------------------------------------------+
| PRIMARY_EXECUTION           | Device primarily responsible for executing the    |
|                             | task within the formation.  Exactly one device    |
|                             | per formation should hold this role.              |
+-----------------------------+---------------------------------------------------+
| SUPPORT                     | Assists the primary with a specific capability    |
|                             | (e.g. camera, extra compute).  May perform sub-   |
|                             | steps.                                            |
+-----------------------------+---------------------------------------------------+
| OBSERVER                    | Receives a read-only view of formation progress.  |
|                             | No execution responsibility.                      |
+-----------------------------+---------------------------------------------------+
| RELAY                       | Forwards commands/data between formation members  |
|                             | without executing tasks itself.                   |
+-----------------------------+---------------------------------------------------+
| FALLBACK                    | Eligible to take over PRIMARY_EXECUTION if the    |
|                             | primary becomes unavailable.                      |
+-----------------------------+---------------------------------------------------+
| MERGE_OWNER                 | Responsible for merging multi-device results into |
|                             | a coherent outcome.  When absent the primary      |
|                             | execution device is assumed to own merge.         |
+-----------------------------+---------------------------------------------------+
| UNASSIGNED                  | Device is in the formation roster but has not yet |
|                             | been assigned a concrete role.                    |
+-----------------------------+---------------------------------------------------+

Relationship to DeviceRole (PR-13)
-----------------------------------
:class:`~core.cross_device_policy.DeviceRole` describes routing-level intent
(how the task is dispatched across devices).  :class:`FormationRole` describes
formation-level responsibility (who does what inside the active group).  The
two enumerations share common names but live in separate semantic layers:

* ``DeviceRole`` is resolved at routing / policy time and governs dispatch.
* ``FormationRole`` is declared in the formation group and governs execution
  responsibility, merge ownership, and barrier/completion posture.

Using both together is additive — they reinforce each other rather than
replacing one another.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "FormationRole",
    "FORMATION_ROLE_PRECEDENCE",
    "formation_role_description",
    "FormationMember",
]


# ---------------------------------------------------------------------------
# Formation role enum
# ---------------------------------------------------------------------------


class FormationRole(str, Enum):
    """Taxonomy of participation roles for devices inside a formation group.

    String values are stable identifiers safe for serialisation, logging, and
    API responses.
    """

    SOURCE = "source_device"
    """Device that originated the cross-device request."""

    PRIMARY_EXECUTION = "primary_execution_device"
    """Device primarily responsible for executing the task."""

    SUPPORT = "support_device"
    """Assists the primary executor with a specific capability."""

    OBSERVER = "observer_device"
    """Receives read-only view of formation progress.  No execution."""

    RELAY = "relay_device"
    """Forwards commands/data between formation members; does not execute."""

    FALLBACK = "fallback_device"
    """Eligible to assume PRIMARY_EXECUTION if the primary is unavailable."""

    MERGE_OWNER = "merge_owner_device"
    """Owns result-merge responsibility for multi-device outcomes."""

    UNASSIGNED = "unassigned"
    """Device is in the roster but not yet assigned a concrete role."""


# ---------------------------------------------------------------------------
# Role metadata
# ---------------------------------------------------------------------------

_ROLE_DESCRIPTIONS: Dict[str, str] = {
    FormationRole.SOURCE.value: (
        "Originated the cross-device request.  May be co-located with the "
        "PRIMARY_EXECUTION device or a different device when the request crosses "
        "physical or network boundaries."
    ),
    FormationRole.PRIMARY_EXECUTION.value: (
        "Primarily responsible for executing the task within the formation.  "
        "Exactly one device per formation should hold this role.  Receives the "
        "full task envelope."
    ),
    FormationRole.SUPPORT.value: (
        "Assists the primary executor with a specific capability (camera, "
        "microphone, extra compute, specialist sensor).  May perform designated "
        "sub-steps under direction of the primary executor."
    ),
    FormationRole.OBSERVER.value: (
        "Receives a read-only view of formation progress and results.  Does not "
        "perform any execution.  Suitable for status boards and companion "
        "screens."
    ),
    FormationRole.RELAY.value: (
        "Forwards commands and data between formation members without executing "
        "tasks itself.  Typical for gateway nodes or protocol-bridging devices."
    ),
    FormationRole.FALLBACK.value: (
        "Eligible to assume PRIMARY_EXECUTION if the current primary device "
        "becomes unavailable or exceeds its action budget.  Promoted by the "
        "formation resolver when conditions are met."
    ),
    FormationRole.MERGE_OWNER.value: (
        "Owns responsibility for merging results from multiple participating "
        "devices into a coherent outcome.  When this role is absent the "
        "PRIMARY_EXECUTION device is assumed to own merge."
    ),
    FormationRole.UNASSIGNED.value: (
        "Device is included in the formation roster but has not yet been "
        "assigned a concrete participation role.  Provisional state pending "
        "policy resolution."
    ),
}

#: Precedence order from most authoritative to least.
#: Used by resolvers to select the 'most significant' role when a device
#: appears in multiple formation contexts.
FORMATION_ROLE_PRECEDENCE: List[FormationRole] = [
    FormationRole.PRIMARY_EXECUTION,
    FormationRole.MERGE_OWNER,
    FormationRole.FALLBACK,
    FormationRole.SUPPORT,
    FormationRole.RELAY,
    FormationRole.OBSERVER,
    FormationRole.SOURCE,
    FormationRole.UNASSIGNED,
]


def formation_role_description(role: FormationRole) -> str:
    """Return the human-readable description for *role*."""
    return _ROLE_DESCRIPTIONS.get(role.value, "Unknown formation role.")


# ---------------------------------------------------------------------------
# FormationMember dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FormationMember:
    """A single device's participation record inside a formation group.

    Attributes
    ----------
    device_id:
        Stable identifier of the participating device (e.g. UDM device ID,
        hostname, or generated UUID).  May be ``None`` for placeholder / yet-
        to-be-selected members.
    role:
        The :class:`FormationRole` this device holds in the formation.
    reason:
        Human-readable explanation of why this role was assigned.  Suitable
        for logging, dashboards, and downstream hints.
    capabilities:
        Optional list of capability strings that justify the role (e.g.
        ``["camera", "microphone"]`` for a SUPPORT member).
    is_local:
        ``True`` if this device is the local device running the current
        runtime session.
    health_score:
        Optional health score (0.0–1.0) sourced from the device health layer.
        ``None`` means health data was not available at formation time.
    """

    device_id: Optional[str] = None
    role: FormationRole = FormationRole.UNASSIGNED
    reason: str = "unassigned"
    capabilities: List[str] = dataclasses.field(default_factory=list)
    is_local: bool = False
    health_score: Optional[float] = None

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
            "health_score": self.health_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormationMember":
        """Reconstruct a :class:`FormationMember` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        try:
            role = FormationRole(data.get("role", FormationRole.UNASSIGNED.value))
        except (ValueError, KeyError):
            role = FormationRole.UNASSIGNED

        health_raw = data.get("health_score")
        health_score: Optional[float] = None
        if health_raw is not None:
            try:
                health_score = float(health_raw)
            except (TypeError, ValueError):
                health_score = None

        return cls(
            device_id=data.get("device_id"),
            role=role,
            reason=str(data.get("reason", "reconstructed from dict")),
            capabilities=list(data.get("capabilities", [])),
            is_local=bool(data.get("is_local", False)),
            health_score=health_score,
        )

    def __repr__(self) -> str:
        return (
            f"<FormationMember "
            f"device={self.device_id!r} "
            f"role={self.role.value} "
            f"local={self.is_local}>"
        )
