#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/body_mesh_registry.py
================================
Block-4 (PR-4) — Body Mesh Model

Models the Galaxy device network as a *Body Mesh*: each device is assigned
one or more **roles** (perception / action / presence) and the mesh tracks
which device is the **primary body** vs **secondary bodies** for a given
cognitive agent.

Design
------
- **Additive** — does not replace any existing device registry.
- Roles are stored in device metadata; ``BodyMeshRegistry`` layers on top of
  :class:`~core.unified.device_manager.UnifiedDeviceManager`.
- Singleton via :func:`get_body_mesh_registry` / :func:`reset_body_mesh_registry`.

Role semantics
--------------
:attr:`DeviceRole.PERCEPTION`
    Device gathers sensory input (camera, mic, sensors).
:attr:`DeviceRole.ACTION`
    Device executes actuator commands (UI automation, file ops, motor control).
:attr:`DeviceRole.PRESENCE`
    Device surfaces the cognitive presence to the user (display, speaker,
    notification).  A device may carry multiple roles simultaneously.

Primary vs secondary
--------------------
The **primary body** is the device that anchors the current cognitive session
(highest combined role weight + health score).  All other participating
devices are **secondary bodies**.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.Mesh.BodyMeshRegistry")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DeviceRole(str, Enum):
    """Functional role a device plays in the Body Mesh."""

    PERCEPTION = "perception"
    """Sensory / input role — cameras, microphones, environmental sensors."""

    ACTION = "action"
    """Actuator / execution role — UI automation, command dispatch, motors."""

    PRESENCE = "presence"
    """Display / output role — surfaces cognitive state to the user."""


# Role weights used in primary-body scoring.
_ROLE_WEIGHTS: Dict[DeviceRole, float] = {
    DeviceRole.PERCEPTION: 1.0,
    DeviceRole.ACTION: 1.5,
    DeviceRole.PRESENCE: 1.2,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BodyEntry:
    """Registry entry for one device in the Body Mesh.

    Attributes
    ----------
    device_id:
        The unique identifier matching :attr:`UnifiedDevice.device_id`.
    roles:
        Set of :class:`DeviceRole` values assigned to this device.
    session_id:
        Optional cognitive session the device is active in.
    body_score:
        Numeric score used to determine primary-body precedence.  Higher is
        better.  Automatically updated when :meth:`BodyMeshRegistry.score_entry`
        is called.
    registered_at:
        Unix timestamp of first registration.
    metadata:
        Arbitrary extra fields (e.g. ``{"display_name": "Phone-1"}``).
    """

    device_id: str
    roles: Set[DeviceRole] = field(default_factory=set)
    session_id: Optional[str] = None
    body_score: float = 0.0
    registered_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: DeviceRole) -> bool:
        """Return ``True`` if this entry carries the given role."""
        return role in self.roles

    def role_weight(self) -> float:
        """Return the combined weight of all assigned roles."""
        return sum(_ROLE_WEIGHTS.get(r, 1.0) for r in self.roles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "roles": sorted(r.value for r in self.roles),
            "session_id": self.session_id,
            "body_score": self.body_score,
            "registered_at": self.registered_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class BodyAssignment:
    """Result of a primary/secondary body computation.

    Attributes
    ----------
    primary_body:
        :class:`BodyEntry` of the primary device, or ``None`` if no devices
        are registered.
    secondary_bodies:
        Ordered list (by descending body_score) of non-primary devices.
    session_id:
        Session for which this assignment was computed.
    computed_at:
        Unix timestamp of computation.
    """

    primary_body: Optional[BodyEntry]
    secondary_bodies: List[BodyEntry]
    session_id: Optional[str] = None
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_body": self.primary_body.to_dict() if self.primary_body else None,
            "secondary_bodies": [e.to_dict() for e in self.secondary_bodies],
            "session_id": self.session_id,
            "computed_at": self.computed_at,
        }


# ---------------------------------------------------------------------------
# BodyMeshRegistry
# ---------------------------------------------------------------------------


class BodyMeshRegistry:
    """Thread-safe registry that models the Body Mesh.

    Methods
    -------
    register(device_id, roles, session_id, metadata)
        Add or update a device in the mesh.
    unregister(device_id)
        Remove a device from the mesh.
    get(device_id) -> Optional[BodyEntry]
        Return the entry for a given device.
    list_entries() -> List[BodyEntry]
        Return all registered entries.
    get_by_role(role) -> List[BodyEntry]
        Return all devices carrying a specific role.
    compute_assignment(session_id) -> BodyAssignment
        Compute primary/secondary body assignment for a session.
    score_entry(device_id, health_score) -> None
        Update the body_score for a device using its current health score.
    snapshot() -> Dict[str, Any]
        Return a JSON-serialisable snapshot of the full mesh.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, BodyEntry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        device_id: str,
        roles: Optional[List[DeviceRole]] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BodyEntry:
        """Register or update a device in the Body Mesh.

        If the device is already registered, its roles/metadata are *merged*
        (additive) and session_id is updated when provided.

        Args:
            device_id:  Device identifier.
            roles:      Roles to assign (merged with existing on update).
            session_id: Optional cognitive session ID.
            metadata:   Arbitrary key/value metadata.

        Returns:
            The :class:`BodyEntry` for the device (newly created or updated).
        """
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is None:
                entry = BodyEntry(
                    device_id=device_id,
                    roles=set(roles or []),
                    session_id=session_id,
                    metadata=dict(metadata or {}),
                )
                self._entries[device_id] = entry
                logger.info(
                    "BodyMeshRegistry: registered device=%s roles=%s session=%s",
                    device_id,
                    [r.value for r in entry.roles],
                    session_id,
                )
            else:
                if roles:
                    entry.roles.update(roles)
                if session_id is not None:
                    entry.session_id = session_id
                if metadata:
                    entry.metadata.update(metadata)
                logger.debug(
                    "BodyMeshRegistry: updated device=%s roles=%s",
                    device_id,
                    [r.value for r in entry.roles],
                )
            return entry

    def unregister(self, device_id: str) -> None:
        """Remove a device from the mesh."""
        with self._lock:
            if device_id in self._entries:
                self._entries.pop(device_id)
                logger.info("BodyMeshRegistry: unregistered device=%s", device_id)
            else:
                logger.debug("BodyMeshRegistry: unregister unknown device=%s", device_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, device_id: str) -> Optional[BodyEntry]:
        """Return the :class:`BodyEntry` for *device_id*, or ``None``."""
        with self._lock:
            return self._entries.get(device_id)

    def list_entries(self) -> List[BodyEntry]:
        """Return a snapshot list of all registered entries."""
        with self._lock:
            return list(self._entries.values())

    def get_by_role(self, role: DeviceRole) -> List[BodyEntry]:
        """Return all entries that carry the specified role."""
        with self._lock:
            return [e for e in self._entries.values() if role in e.roles]

    def get_by_session(self, session_id: str) -> List[BodyEntry]:
        """Return all entries associated with *session_id*."""
        with self._lock:
            return [e for e in self._entries.values() if e.session_id == session_id]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_entry(self, device_id: str, health_score: float) -> None:
        """Update the *body_score* for a device.

        ``body_score = role_weight × health_score``

        This is called by :class:`~core.mesh.device_role_allocator.DeviceRoleAllocator`
        whenever health scores are refreshed.
        """
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is not None:
                entry.body_score = entry.role_weight() * max(0.0, health_score)
                logger.debug(
                    "BodyMeshRegistry: scored device=%s body_score=%.3f",
                    device_id,
                    entry.body_score,
                )

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def compute_assignment(self, session_id: Optional[str] = None) -> BodyAssignment:
        """Compute primary/secondary body assignment.

        When *session_id* is given, only devices associated with that session
        are considered.  Otherwise all registered devices participate.

        The primary body is the device with the highest :attr:`BodyEntry.body_score`.
        All other devices become secondary bodies, ordered by descending score.

        Returns:
            :class:`BodyAssignment` with ``primary_body`` and
            ``secondary_bodies``.
        """
        with self._lock:
            if session_id is not None:
                candidates = [e for e in self._entries.values() if e.session_id == session_id]
            else:
                candidates = list(self._entries.values())

        if not candidates:
            return BodyAssignment(
                primary_body=None,
                secondary_bodies=[],
                session_id=session_id,
            )

        sorted_entries = sorted(candidates, key=lambda e: e.body_score, reverse=True)
        primary = sorted_entries[0]
        secondary = sorted_entries[1:]

        assignment = BodyAssignment(
            primary_body=primary,
            secondary_bodies=secondary,
            session_id=session_id,
        )
        logger.info(
            "BodyMeshRegistry: assignment primary=%s secondary_count=%d session=%s",
            primary.device_id,
            len(secondary),
            session_id,
        )
        return assignment

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of the full mesh."""
        with self._lock:
            entries = list(self._entries.values())
        return {
            "total": len(entries),
            "entries": [e.to_dict() for e in entries],
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[BodyMeshRegistry] = None
_registry_lock = threading.Lock()


def get_body_mesh_registry() -> BodyMeshRegistry:
    """Return (or lazily create) the process-level :class:`BodyMeshRegistry`."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = BodyMeshRegistry()
    return _registry


def reset_body_mesh_registry() -> None:
    """Reset the singleton (intended for tests only)."""
    global _registry
    with _registry_lock:
        _registry = None
