#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation.formation_group
========================================

PR-17 (V4) — Device Formation & Multi-Device Group Model

Defines the **DeviceFormationGroup** — the central, wire-safe, serialisable
model that makes multi-device participation explicit and inspectable.

A ``DeviceFormationGroup`` captures:

* **Who** is in the formation (member device IDs and roles)
* **Which** device is the source / origin of the request
* **Which** device is the primary executor
* **Which** devices are support / observer / relay / fallback
* **Which** device owns merge responsibility
* **What** barrier/completion posture is intended
* **Why** the formation was assembled (``formation_reason``)
* **What** runtime domain intent applies (e.g. ``cross_device``)
* A stable ``formation_id`` and optional ``task_id`` / ``trace_id``

This dataclass is intentionally additive — it does not replace, extend, or
modify any existing device manager, device router, TaskGraph, or orchestration
module.  It is a pure **description** layer that can be attached to projection
payloads, API responses, and log records.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any, Dict, List, Optional

from .formation_role import FormationMember, FormationRole

__all__ = [
    "DeviceFormationGroup",
    "EMPTY_FORMATION_GROUP",
]


# ---------------------------------------------------------------------------
# DeviceFormationGroup
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DeviceFormationGroup:
    """Explicit, serialisable model of a multi-device execution formation.

    All fields are immutable once constructed.  Use :meth:`to_dict` for
    JSON serialisation and :meth:`from_dict` to reconstruct from stored or
    transmitted data.

    Attributes
    ----------
    formation_id:
        Stable unique identifier for this formation (UUID string).  Generated
        at construction time when not supplied.
    task_id:
        Optional identifier of the task this formation is serving.
    trace_id:
        Optional distributed-trace identifier for correlation with observability
        spans.
    source_device_id:
        Device ID of the device that originated the cross-device request.
    members:
        Ordered list of :class:`~.formation_role.FormationMember` records.  The
        list should include **all** participating devices, each with their
        assigned :class:`~.formation_role.FormationRole`.
    merge_owner_device_id:
        Device ID of the device that owns result-merge responsibility.  Derived
        from the MERGE_OWNER member when present; falls back to the primary
        execution device.
    barrier_posture:
        Human-readable string describing the barrier/completion posture for the
        formation (e.g. ``"wait_all"``, ``"wait_primary"``,
        ``"best_effort"``).  See :data:`BARRIER_POSTURES` for stable values.
    formation_reason:
        Human-readable explanation of why this formation was assembled.
    runtime_domain_intent:
        String describing the runtime domain that triggered formation assembly
        (e.g. ``"cross_device"``).  Mirrors the
        :class:`~core.continuum.types.RuntimeDomain` enum value when available.
    schema_version:
        Integer schema version.  Increment when the wire format changes.
    """

    formation_id: str = dataclasses.field(
        default_factory=lambda: str(uuid.uuid4())
    )
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    source_device_id: Optional[str] = None
    members: List[FormationMember] = dataclasses.field(default_factory=list)
    merge_owner_device_id: Optional[str] = None
    barrier_posture: str = "wait_primary"
    formation_reason: str = "unknown"
    runtime_domain_intent: str = "cross_device"
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def primary_execution_device_id(self) -> Optional[str]:
        """Return the device ID of the PRIMARY_EXECUTION member, or ``None``."""
        for member in self.members:
            if member.role == FormationRole.PRIMARY_EXECUTION:
                return member.device_id
        return None

    @property
    def fallback_device_ids(self) -> List[str]:
        """Return device IDs of all FALLBACK members."""
        return [
            m.device_id
            for m in self.members
            if m.role == FormationRole.FALLBACK and m.device_id is not None
        ]

    @property
    def support_device_ids(self) -> List[str]:
        """Return device IDs of all SUPPORT members."""
        return [
            m.device_id
            for m in self.members
            if m.role == FormationRole.SUPPORT and m.device_id is not None
        ]

    @property
    def observer_device_ids(self) -> List[str]:
        """Return device IDs of all OBSERVER members."""
        return [
            m.device_id
            for m in self.members
            if m.role == FormationRole.OBSERVER and m.device_id is not None
        ]

    @property
    def relay_device_ids(self) -> List[str]:
        """Return device IDs of all RELAY members."""
        return [
            m.device_id
            for m in self.members
            if m.role == FormationRole.RELAY and m.device_id is not None
        ]

    @property
    def all_member_device_ids(self) -> List[str]:
        """Return device IDs of all non-None members."""
        return [m.device_id for m in self.members if m.device_id is not None]

    @property
    def effective_merge_owner_device_id(self) -> Optional[str]:
        """Return merge owner device ID, falling back to primary execution device.

        Precedence:
        1. Explicitly declared ``merge_owner_device_id``
        2. First MERGE_OWNER role member
        3. PRIMARY_EXECUTION member
        4. ``None``
        """
        if self.merge_owner_device_id:
            return self.merge_owner_device_id
        for member in self.members:
            if member.role == FormationRole.MERGE_OWNER and member.device_id:
                return member.device_id
        return self.primary_execution_device_id

    @property
    def member_count(self) -> int:
        """Return the total number of members in the formation."""
        return len(self.members)

    @property
    def is_multi_device(self) -> bool:
        """Return ``True`` if the formation contains more than one device."""
        return len(set(self.all_member_device_ids)) > 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        The returned dict is stable and wire-safe: all values are JSON
        primitives (strings, numbers, booleans, lists, dicts, or ``None``).
        """
        return {
            "schema_version": self.schema_version,
            "formation_id": self.formation_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_device_id": self.source_device_id,
            "primary_execution_device_id": self.primary_execution_device_id,
            "merge_owner_device_id": self.effective_merge_owner_device_id,
            "barrier_posture": self.barrier_posture,
            "formation_reason": self.formation_reason,
            "runtime_domain_intent": self.runtime_domain_intent,
            "member_count": self.member_count,
            "is_multi_device": self.is_multi_device,
            "all_member_device_ids": self.all_member_device_ids,
            "fallback_device_ids": self.fallback_device_ids,
            "support_device_ids": self.support_device_ids,
            "observer_device_ids": self.observer_device_ids,
            "relay_device_ids": self.relay_device_ids,
            "members": [m.to_dict() for m in self.members],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceFormationGroup":
        """Reconstruct a :class:`DeviceFormationGroup` from a serialised dict.

        Unknown or missing fields are silently defaulted to allow graceful
        forward-compatibility.
        """
        raw_members = data.get("members", [])
        members: List[FormationMember] = []
        for item in raw_members:
            if isinstance(item, dict):
                members.append(FormationMember.from_dict(item))
            elif isinstance(item, FormationMember):
                members.append(item)

        return cls(
            formation_id=str(data.get("formation_id") or str(uuid.uuid4())),
            task_id=data.get("task_id"),
            trace_id=data.get("trace_id"),
            source_device_id=data.get("source_device_id"),
            members=members,
            merge_owner_device_id=data.get("merge_owner_device_id"),
            barrier_posture=str(data.get("barrier_posture", "wait_primary")),
            formation_reason=str(data.get("formation_reason", "reconstructed from dict")),
            runtime_domain_intent=str(data.get("runtime_domain_intent", "cross_device")),
            schema_version=int(data.get("schema_version", 1)),
        )

    def __repr__(self) -> str:
        return (
            f"<DeviceFormationGroup "
            f"id={self.formation_id!r} "
            f"members={self.member_count} "
            f"multi={self.is_multi_device}>"
        )


# ---------------------------------------------------------------------------
# Stable barrier posture values
# ---------------------------------------------------------------------------

#: Stable string values for :attr:`DeviceFormationGroup.barrier_posture`.
BARRIER_POSTURES = {
    "wait_all": (
        "Block completion until all participating devices have reported results."
    ),
    "wait_primary": (
        "Block completion only until the PRIMARY_EXECUTION device reports a "
        "result.  Support/observer devices may lag."
    ),
    "best_effort": (
        "Do not block — complete as soon as a usable result is available.  "
        "Suitable for fire-and-forget or low-criticality formations."
    ),
    "wait_merge_owner": (
        "Block completion until the MERGE_OWNER device has assembled and "
        "reported the merged result."
    ),
}


# ---------------------------------------------------------------------------
# Pre-built idle/empty sentinel
# ---------------------------------------------------------------------------

#: A pre-built empty formation group for use as an idle/uninitialised default.
#: Consumers that have no active formation context should use this rather than
#: constructing a partial group themselves.
EMPTY_FORMATION_GROUP = DeviceFormationGroup(
    formation_id="empty",
    task_id=None,
    trace_id=None,
    source_device_id=None,
    members=[],
    merge_owner_device_id=None,
    barrier_posture="wait_primary",
    formation_reason="no active formation",
    runtime_domain_intent="local",
    schema_version=1,
)
