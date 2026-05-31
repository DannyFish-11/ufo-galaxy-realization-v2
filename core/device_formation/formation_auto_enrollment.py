#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/device_formation/formation_auto_enrollment.py
====================================================
PR-I — Formation Auto-Enrollment Manager.

Background
----------
The existing :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`
manages formation lifecycle for a *fixed* :class:`~.formation_group.DeviceFormationGroup`
initialised at construction time.  It has no built-in mechanism for accepting
new participants that arrive after the initial group is seeded.

This module closes that gap by providing a **process-level singleton**
:class:`FormationAutoEnrollmentManager` that:

1. Maintains a *mutable* participant table that grows as devices register.
2. Constructs (or rebuilds) a :class:`~.formation_group.DeviceFormationGroup`
   from the current participant table so that a
   :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator` always
   reflects the live membership.
3. Exposes :meth:`enroll_device`, :meth:`remove_device`, and
   :meth:`update_device_readiness` as the primary auto-enrollment surface.
4. Delegates structural decisions (promote fallback, continue degraded, reshape)
   to :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`.

Design principles
-----------------
- **Additive only** — does not modify ``formation_runtime_coordinator.py``,
  ``formation_resolver.py``, or any other existing module.
- **Idempotent** — :meth:`enroll_device` is safe to call repeatedly; the
  participant table is a dict keyed by device_id.
- **Thread-safe** — a per-instance :class:`threading.Lock` guards all mutations.
- **Graceful degradation** — every public method is guarded.

Sentinels
---------
:data:`FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY`
    Identifies this module as the canonical auto-enrollment manager for
    formation lifecycle.
:data:`FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY`
    Affirms that enroll_device is idempotent.

Public API
----------
Data classes:
    :class:`FormationParticipantEntry`

Classes:
    :class:`FormationAutoEnrollmentManager`

Functions:
    :func:`get_formation_auto_enrollment_manager`
    :func:`reset_formation_auto_enrollment_manager`
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceFormation.AutoEnrollment")

__all__ = [
    # Sentinels
    "FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY",
    "FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY",
    # Data
    "FormationParticipantEntry",
    # Manager
    "FormationAutoEnrollmentManager",
    # Module-level functions
    "get_formation_auto_enrollment_manager",
    "reset_formation_auto_enrollment_manager",
]

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY: str = (
    "FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY: "
    "core/device_formation/formation_auto_enrollment.py is the canonical "
    "auto-enrollment manager that dynamically adds and removes participants "
    "in a process-level FormationRuntimeCoordinator.  PR-I."
)

FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY: str = (
    "FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY: "
    "enroll_device() is safe to call repeatedly for the same device_id; "
    "the participant table is a dict keyed by device_id and repeated calls "
    "merge rather than duplicate."
)


# ---------------------------------------------------------------------------
# FormationParticipantEntry
# ---------------------------------------------------------------------------


@dataclass
class FormationParticipantEntry:
    """Lightweight participant record used by the auto-enrollment manager.

    Attributes
    ----------
    device_id:
        The canonical device identifier.
    role:
        String role for this participant in the formation (e.g.
        ``"primary_execution_device"``).
    health_score:
        Current health score in ``[0.0, 1.0]``.
    roles:
        List of :class:`~core.mesh.body_mesh_registry.DeviceRole` (or strings)
        reported via capability / registration events.
    session_id:
        Optional session identifier.
    enrolled_at:
        Epoch timestamp when this participant was first enrolled.
    last_updated_at:
        Epoch timestamp of the most recent update.
    is_active:
        ``False`` when the device has been removed (lost/disconnected).
    """

    device_id: str
    role: str = "unassigned"
    health_score: float = 1.0
    roles: List[Any] = field(default_factory=list)
    session_id: Optional[str] = None
    enrolled_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "role": self.role,
            "health_score": self.health_score,
            "roles": [
                r.value if hasattr(r, "value") else str(r) for r in (self.roles or [])
            ],
            "session_id": self.session_id,
            "enrolled_at": self.enrolled_at,
            "last_updated_at": self.last_updated_at,
            "is_active": self.is_active,
        }


# ---------------------------------------------------------------------------
# FormationAutoEnrollmentManager
# ---------------------------------------------------------------------------


class FormationAutoEnrollmentManager:
    """Process-level manager for dynamic formation participant enrollment.

    Unlike :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`,
    which is constructed from a fixed formation group, this manager owns a
    *mutable* participant table.  Callers invoke :meth:`enroll_device` to
    add participants and :meth:`remove_device` to remove them; the manager
    rebuilds the underlying group and coordinator accordingly.

    The formation_id is stable for the lifetime of the manager instance and
    is used consistently across all coordinator rebuilds.
    """

    def __init__(self, formation_id: Optional[str] = None) -> None:
        self._formation_id: str = formation_id or f"auto_{uuid.uuid4().hex[:8]}"
        self._participants: Dict[str, FormationParticipantEntry] = {}
        self._coordinator: Optional[Any] = None  # FormationRuntimeCoordinator
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public enrollment surface
    # ------------------------------------------------------------------

    def enroll_device(
        self,
        device_id: str,
        *,
        roles: Optional[List[Any]] = None,
        session_id: Optional[str] = None,
        health_score: float = 1.0,
        formation_role: Optional[str] = None,
    ) -> FormationParticipantEntry:
        """Enroll (or re-enroll) a device in the managed formation.

        If the device is already present the entry is updated (roles merged,
        health_score refreshed); no duplicate is created.

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        roles:
            Body mesh / capability roles to associate with this participant.
        session_id:
            Optional session identifier.
        health_score:
            Current health score.
        formation_role:
            Explicit formation role string (e.g. ``"primary_execution_device"``).
            When ``None`` the role is inferred from the current participant count
            (first participant becomes primary, subsequent ones become support).

        Returns
        -------
        FormationParticipantEntry
        """
        if not device_id:
            logger.warning("enroll_device: empty device_id — skipping")
            return FormationParticipantEntry(device_id="")

        with self._lock:
            existing = self._participants.get(device_id)
            if existing is not None:
                # Update existing entry (idempotent merge)
                if roles:
                    existing.roles = self._merge_roles(existing.roles, roles)
                if session_id:
                    existing.session_id = session_id
                existing.health_score = health_score
                if formation_role:
                    existing.role = formation_role
                existing.is_active = True
                existing.last_updated_at = time.time()
                entry = existing
                logger.debug(
                    "enroll_device: updated: device_id=%s role=%s", device_id, entry.role
                )
            else:
                # Derive formation_role from participant count when not explicit
                if formation_role is None:
                    active_count = sum(
                        1 for p in self._participants.values() if p.is_active
                    )
                    formation_role = self._derive_formation_role(active_count)
                entry = FormationParticipantEntry(
                    device_id=device_id,
                    role=formation_role,
                    health_score=health_score,
                    roles=list(roles or []),
                    session_id=session_id,
                )
                self._participants[device_id] = entry
                logger.info(
                    "enroll_device: new participant: device_id=%s role=%s",
                    device_id,
                    formation_role,
                )

            # Rebuild group and coordinator
            self._rebuild_coordinator_locked()

        logger.info(
            "formation_auto_enrollment: enrolled device_id=%s role=%s formation_id=%s",
            device_id,
            entry.role,
            self._formation_id,
        )
        return entry

    def remove_device(
        self,
        device_id: str,
        *,
        reason: Optional[str] = None,
    ) -> Optional[FormationParticipantEntry]:
        """Remove a device from the managed formation.

        The entry is marked inactive and the coordinator is notified via
        :meth:`~.formation_runtime_coordinator.FormationRuntimeCoordinator.on_participant_lost`.

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        reason:
            Optional human-readable reason.

        Returns
        -------
        FormationParticipantEntry or None
            The updated entry, or ``None`` when the device was not tracked.
        """
        with self._lock:
            entry = self._participants.get(device_id)
            if entry is None:
                logger.debug("remove_device: unknown device_id=%s — skipping", device_id)
                return None

            entry.is_active = False
            entry.last_updated_at = time.time()

            if self._coordinator is not None:
                try:
                    from .formation_runtime_coordinator import FormationParticipantState
                    decision = self._coordinator.on_participant_lost(
                        device_id, reason=reason or "auto_enrollment_remove"
                    )
                    logger.info(
                        "formation_auto_enrollment: participant_lost device_id=%s "
                        "formation_state=%s",
                        device_id,
                        decision.runtime_state.value,
                    )
                except Exception as exc:
                    logger.debug(
                        "remove_device: coordinator notify non-fatal: device_id=%s error=%s",
                        device_id, exc,
                    )

        logger.info(
            "formation_auto_enrollment: removed device_id=%s reason=%s formation_id=%s",
            device_id,
            reason,
            self._formation_id,
        )
        return entry

    def update_device_readiness(
        self,
        device_id: str,
        *,
        is_ready: bool,
        health_score: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Notify the formation coordinator of a readiness change.

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        is_ready:
            ``True`` when the device is ready; ``False`` when degraded or lost.
        health_score:
            Optional explicit health score.
        reason:
            Optional human-readable reason.
        """
        with self._lock:
            entry = self._participants.get(device_id)
            if entry is None:
                logger.debug(
                    "update_device_readiness: unknown device_id=%s — skipping", device_id
                )
                return

            if health_score is not None:
                entry.health_score = health_score
            entry.last_updated_at = time.time()

            if self._coordinator is None:
                return

            try:
                from .formation_runtime_coordinator import FormationParticipantState
                new_state = (
                    FormationParticipantState.READY
                    if is_ready
                    else FormationParticipantState.DEGRADED
                )
                effective_score = health_score if health_score is not None else entry.health_score
                decision = self._coordinator.on_participant_readiness_changed(
                    device_id,
                    new_state,
                    health_score=effective_score,
                    reason=reason or ("ready" if is_ready else "not_ready"),
                )
                logger.info(
                    "formation_auto_enrollment: readiness_changed device_id=%s "
                    "is_ready=%s formation_state=%s",
                    device_id,
                    is_ready,
                    decision.runtime_state.value,
                )
            except Exception as exc:
                logger.debug(
                    "update_device_readiness: coordinator notify non-fatal: "
                    "device_id=%s error=%s",
                    device_id, exc,
                )

    def get_coordinator(self) -> Optional[Any]:
        """Return the current :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`."""
        with self._lock:
            return self._coordinator

    def get_participant(self, device_id: str) -> Optional[FormationParticipantEntry]:
        """Return the entry for *device_id*, or ``None``."""
        with self._lock:
            return self._participants.get(device_id)

    def list_active_device_ids(self) -> List[str]:
        """Return the IDs of all active (enrolled) participants."""
        with self._lock:
            return [
                did for did, e in self._participants.items() if e.is_active
            ]

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of the manager state."""
        with self._lock:
            coord_snap = None
            if self._coordinator is not None:
                try:
                    coord_snap = self._coordinator.snapshot().to_dict()
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            return {
                "formation_id": self._formation_id,
                "participants": {
                    did: e.to_dict() for did, e in self._participants.items()
                },
                "coordinator_snapshot": coord_snap,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _derive_formation_role(self, existing_active_count: int) -> str:
        """Derive a conservative formation role from participant count."""
        try:
            from .formation_role import FormationRole
            if existing_active_count == 0:
                return FormationRole.PRIMARY_EXECUTION.value
            return FormationRole.SUPPORT.value
        except Exception:
            return "primary_execution_device" if existing_active_count == 0 else "support_device"

    @staticmethod
    def _merge_roles(existing: List[Any], new_roles: List[Any]) -> List[Any]:
        """Merge *new_roles* into *existing* without duplicates."""
        existing_values = {
            r.value if hasattr(r, "value") else str(r) for r in existing
        }
        result = list(existing)
        for role in new_roles:
            val = role.value if hasattr(role, "value") else str(role)
            if val not in existing_values:
                result.append(role)
                existing_values.add(val)
        return result

    def _rebuild_coordinator_locked(self) -> None:
        """Rebuild the :class:`~.formation_runtime_coordinator.FormationRuntimeCoordinator`
        from the current active participant table.

        Must be called under ``self._lock``.
        """
        try:
            from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
            from .formation_role import FormationRole, FormationMember
            from .formation_runtime_coordinator import (
                FormationRuntimeCoordinator,
                FormationParticipantState,
            )

            active = [e for e in self._participants.values() if e.is_active]
            if not active:
                self._coordinator = FormationRuntimeCoordinator(EMPTY_FORMATION_GROUP)
                return

            members: List[FormationMember] = []
            source_device_id = ""
            for entry in active:
                try:
                    role = FormationRole(entry.role)
                except ValueError:
                    role = FormationRole.UNASSIGNED

                if not source_device_id and role == FormationRole.PRIMARY_EXECUTION:
                    source_device_id = entry.device_id

                members.append(
                    FormationMember(
                        device_id=entry.device_id,
                        role=role,
                        health_score=entry.health_score,
                    )
                )

            if not source_device_id and members:
                source_device_id = members[0].device_id

            group = DeviceFormationGroup(
                formation_id=self._formation_id,
                source_device_id=source_device_id,
                members=members,
            )
            self._coordinator = FormationRuntimeCoordinator(group)
            logger.debug(
                "_rebuild_coordinator: formation_id=%s active_count=%d",
                self._formation_id,
                len(active),
            )
        except Exception as exc:
            logger.warning("_rebuild_coordinator_locked: error: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_manager_singleton: Optional[FormationAutoEnrollmentManager] = None
_manager_lock = threading.Lock()


def get_formation_auto_enrollment_manager(
    formation_id: Optional[str] = None,
) -> FormationAutoEnrollmentManager:
    """Return the process-level singleton :class:`FormationAutoEnrollmentManager`.

    Parameters
    ----------
    formation_id:
        Used only when the singleton is first created.
    """
    global _manager_singleton
    if _manager_singleton is None:
        with _manager_lock:
            if _manager_singleton is None:
                _manager_singleton = FormationAutoEnrollmentManager(
                    formation_id=formation_id
                )
    return _manager_singleton


def reset_formation_auto_enrollment_manager() -> None:
    """Reset the module-level singleton — **for testing only**."""
    global _manager_singleton
    with _manager_lock:
        _manager_singleton = None
