#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cross_device_policy.routing_policy
=========================================

PR-13 (V4) — Cross-Device Role & Routing Policy

Defines the **routing posture taxonomy** and the :class:`RoutingPolicy`
dataclass that captures the full routing intent for a cross-device task in
the Galaxy runtime.

Routing Posture Definitions
----------------------------
+---------------------+-------------------------------------------------------+
| Posture             | Meaning                                               |
+=====================+=======================================================+
| LOCAL_PREFERRED     | Attempt local execution first; do not expand unless   |
|                     | the local device explicitly cannot satisfy the        |
|                     | request.                                              |
+---------------------+-------------------------------------------------------+
| LOCAL_THEN_EXPAND   | Begin on the local device; expand to cross-device if  |
|                     | capacity, capability, or policy permits.              |
+---------------------+-------------------------------------------------------+
| REMOTE_REQUIRED     | The request must be dispatched to a remote device.    |
|                     | Local execution is not acceptable.                    |
+---------------------+-------------------------------------------------------+
| SPLIT_EXECUTION     | The task is intentionally split across multiple       |
|                     | devices.  Each device executes a distinct branch or   |
|                     | sub-step.                                             |
+---------------------+-------------------------------------------------------+
| MIRRORED_OBSERVATION| The primary device executes; one or more remote       |
|                     | devices receive a mirrored read-only view for         |
|                     | monitoring or companion display.                      |
+---------------------+-------------------------------------------------------+
| UNDECIDED           | Routing posture has not yet been determined.          |
|                     | Provisional state pending further signals.            |
+---------------------+-------------------------------------------------------+

The :class:`RoutingPolicy` dataclass packages the posture together with the
full set of fields needed to express a routing contract: source device,
assigned devices, execution policy link, and expansion/confirmation gates.

Design rules
------------
- All fields have safe defaults so ``RoutingPolicy()`` produces a valid
  (conservative, single-device) policy.
- ``to_dict()`` is fully JSON-serialisable.
- The object is frozen once created.
- This schema is **read-only by consumers** — enforcement belongs to
  :mod:`core.execution_policy` guardrails.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, List, Optional

from .device_role import DeviceRole, DeviceRoleAssignment

__all__ = [
    "RoutingPosture",
    "POSTURE_DESCRIPTIONS",
    "RoutingPolicy",
    "DEFAULT_LOCAL_ROUTING_POLICY",
]


# ---------------------------------------------------------------------------
# Routing posture enum
# ---------------------------------------------------------------------------


class RoutingPosture(str, Enum):
    """Taxonomy of routing postures for cross-device task orchestration.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.
    """

    LOCAL_PREFERRED = "local_preferred"
    """Prefer local execution; expand only if local cannot satisfy."""

    LOCAL_THEN_EXPAND = "local_then_expand"
    """Begin locally; expand to cross-device if permitted."""

    REMOTE_REQUIRED = "remote_required"
    """Must be dispatched to a remote device; local is not acceptable."""

    SPLIT_EXECUTION = "split_execution"
    """Intentionally split across multiple devices (parallel branches)."""

    MIRRORED_OBSERVATION = "mirrored_observation"
    """Primary executes locally; remote device(s) receive a mirrored view."""

    UNDECIDED = "undecided"
    """Posture has not yet been determined (provisional)."""


# ---------------------------------------------------------------------------
# Posture descriptions
# ---------------------------------------------------------------------------

POSTURE_DESCRIPTIONS: Dict[str, str] = {
    RoutingPosture.LOCAL_PREFERRED.value: (
        "Execute on the local device.  Do not expand to cross-device unless the "
        "local device explicitly cannot satisfy the capability requirement."
    ),
    RoutingPosture.LOCAL_THEN_EXPAND.value: (
        "Begin execution on the local device.  If execution policy permits "
        "cross-device expansion and a suitable remote device is available, "
        "hand off or augment via a remote executor."
    ),
    RoutingPosture.REMOTE_REQUIRED.value: (
        "The request must be dispatched to a designated remote device.  Local "
        "execution is insufficient or explicitly disallowed for this task."
    ),
    RoutingPosture.SPLIT_EXECUTION.value: (
        "The task is split into distinct branches, each assigned to a different "
        "device.  Results are merged by the primary coordinator after all "
        "branches complete."
    ),
    RoutingPosture.MIRRORED_OBSERVATION.value: (
        "The primary device executes the task in full.  One or more remote "
        "devices receive a read-only mirrored view for monitoring, companion "
        "display, or parallel logging."
    ),
    RoutingPosture.UNDECIDED.value: (
        "The routing posture has not yet been determined.  The resolver will "
        "attempt to derive a posture from available signals; until then this "
        "provisional value is used."
    ),
}


# ---------------------------------------------------------------------------
# RoutingPolicy dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RoutingPolicy:
    """Canonical, immutable routing-policy object for a cross-device task.

    Attributes
    ----------
    posture:
        The routing posture that governs how this task is dispatched.
        See :class:`RoutingPosture`.
    source_device_id:
        Identifier of the device that originated the request.  ``None`` if
        not yet determined or for purely local tasks.
    assigned_devices:
        Ordered list of :class:`~.device_role.DeviceRoleAssignment` entries
        describing every participating device and their role.  The primary
        executor (if any) should appear first in practice, though the list is
        not required to be sorted.
    runtime_domain_intent:
        The intended :class:`~core.continuum.types.RuntimeDomain` value for
        this task (e.g. ``"cross_device"``, ``"local"``).  Stored as a plain
        string to avoid a hard import dependency on the continuum module.
    policy_reason:
        Human-readable explanation of why this routing policy was chosen.
        Always non-empty.
    expansion_allowed_by_execution_policy:
        Whether the active :class:`~core.execution_policy.ExecutionPolicy`
        permits cross-device expansion.  Derived from
        ``ExecutionPolicy.cross_device_allowed``.  Defaults to ``False``
        (conservative).
    confirmation_required_before_expansion:
        Whether a human-in-the-loop confirmation step is required before
        cross-device expansion is initiated.  Derived from
        ``ExecutionPolicy.requires_confirmation`` and posture.
    task_id:
        Optional task identifier for traceability.  Propagated from the
        :class:`~core.unified.command_envelope.CommandEnvelope` when
        available.
    trace_id:
        Optional distributed-trace identifier.
    """

    # Routing posture
    posture: RoutingPosture = RoutingPosture.UNDECIDED

    # Source device
    source_device_id: Optional[str] = None

    # Device assignments
    assigned_devices: List[DeviceRoleAssignment] = dataclasses.field(
        default_factory=list
    )

    # Domain intent (plain string to avoid hard import)
    runtime_domain_intent: Optional[str] = None

    # Policy narrative
    policy_reason: str = "default local routing policy"

    # Execution-policy gates
    expansion_allowed_by_execution_policy: bool = False
    confirmation_required_before_expansion: bool = True

    # Traceability
    task_id: Optional[str] = None
    trace_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def is_cross_device(self) -> bool:
        """True if the posture involves more than one device."""
        return self.posture not in (
            RoutingPosture.LOCAL_PREFERRED,
            RoutingPosture.UNDECIDED,
        )

    @property
    def primary_execution_device_id(self) -> Optional[str]:
        """Return the ``device_id`` of the PRIMARY_EXECUTION assignment, if any."""
        for assignment in self.assigned_devices:
            if assignment.role is DeviceRole.PRIMARY_EXECUTION:
                return assignment.device_id
        return None

    @property
    def source_assignment(self) -> Optional[DeviceRoleAssignment]:
        """Return the SOURCE assignment entry, if any."""
        for assignment in self.assigned_devices:
            if assignment.role is DeviceRole.SOURCE:
                return assignment
        return None

    def devices_with_role(self, role: DeviceRole) -> List[DeviceRoleAssignment]:
        """Return all assignments that match *role*."""
        return [a for a in self.assigned_devices if a.role is role]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        Enum values are converted to their string ``.value``.
        """
        return {
            "posture": self.posture.value,
            "source_device_id": self.source_device_id,
            "assigned_devices": [a.to_dict() for a in self.assigned_devices],
            "runtime_domain_intent": self.runtime_domain_intent,
            "policy_reason": self.policy_reason,
            "expansion_allowed_by_execution_policy": self.expansion_allowed_by_execution_policy,
            "confirmation_required_before_expansion": self.confirmation_required_before_expansion,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            # Derived helpers for convenience
            "is_cross_device": self.is_cross_device,
            "primary_execution_device_id": self.primary_execution_device_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoutingPolicy":
        """Reconstruct a :class:`RoutingPolicy` from a previously serialised dict.

        Unknown or missing fields are silently ignored / defaulted.
        """
        try:
            posture = RoutingPosture(
                data.get("posture", RoutingPosture.UNDECIDED.value)
            )
        except (ValueError, KeyError):
            posture = RoutingPosture.UNDECIDED

        raw_assignments = data.get("assigned_devices", [])
        assignments = []
        for raw in raw_assignments:
            if isinstance(raw, dict):
                assignments.append(DeviceRoleAssignment.from_dict(raw))
            elif isinstance(raw, DeviceRoleAssignment):
                assignments.append(raw)

        return cls(
            posture=posture,
            source_device_id=data.get("source_device_id"),
            assigned_devices=assignments,
            runtime_domain_intent=data.get("runtime_domain_intent"),
            policy_reason=str(data.get("policy_reason", "reconstructed from dict")),
            expansion_allowed_by_execution_policy=bool(
                data.get("expansion_allowed_by_execution_policy", False)
            ),
            confirmation_required_before_expansion=bool(
                data.get("confirmation_required_before_expansion", True)
            ),
            task_id=data.get("task_id"),
            trace_id=data.get("trace_id"),
        )

    def __repr__(self) -> str:
        return (
            f"<RoutingPolicy "
            f"posture={self.posture.value} "
            f"source={self.source_device_id!r} "
            f"devices={len(self.assigned_devices)} "
            f"expansion={self.expansion_allowed_by_execution_policy}>"
        )


# ---------------------------------------------------------------------------
# Default conservative policy (safe fallback)
# ---------------------------------------------------------------------------

DEFAULT_LOCAL_ROUTING_POLICY: RoutingPolicy = RoutingPolicy(
    posture=RoutingPosture.LOCAL_PREFERRED,
    source_device_id=None,
    assigned_devices=[],
    runtime_domain_intent="local",
    policy_reason="default local routing policy — no cross-device signals available",
    expansion_allowed_by_execution_policy=False,
    confirmation_required_before_expansion=True,
    task_id=None,
    trace_id=None,
)
"""Pre-built :class:`RoutingPolicy` for safe-fallback use.

Returned by the resolver whenever inputs are absent or cannot be parsed.
Favours local execution; disallows cross-device expansion.
"""
