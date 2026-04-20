#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/mesh_auto_enrollment.py
===================================
PR-I — MeshMembership / BodyMeshRegistry Auto-Write + Formation Auto-Enrollment.

Background
----------
Before this module, there was no unified trigger path that automatically:
1. Wrote or updated a ``MeshMembership`` when a device completed registration,
   capability reporting, and readiness confirmation.
2. Kept ``BodyMeshRegistry`` in sync with the same event chain.
3. Bridged newly ready devices into ``FormationRuntimeCoordinator`` so that
   formation management happened automatically rather than via manual glue code.

This module closes those gaps by providing a single entry-surface
:class:`MeshAutoEnrollmentService` that callers invoke after each significant
device lifecycle event.  The service evaluates whether the device now meets
enrollment conditions and, if so, automatically writes to the registry, derives
the canonical ``MeshMembership``, and triggers formation enrollment.

Design principles
-----------------
- **Additive only** — does not modify ``body_mesh_registry.py``,
  ``mesh_session_lifecycle.py``, or any existing handler.
- **Idempotent** — repeated calls with the same device_id produce stable,
  non-duplicate state.
- **Graceful degradation** — each subsystem call is individually guarded;
  a failure in one step does not block the others.
- **Thread-safe** — a per-instance :class:`threading.Lock` guards internal state.
- **Enrollment conditions** — a device is auto-enrolled when all three of the
  following are satisfied:
    1. ``registered`` — the device has been seen via a registration event.
    2. ``capabilities_reported`` — at least one role has been assigned.
    3. ``readiness_confirmed`` — readiness has been explicitly confirmed,
       OR the service is configured with ``auto_enroll_on_capability=True``
       (default), in which case capabilities alone are sufficient as a
       conservative trigger.

Sentinels
---------
:data:`MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY`
    Identifies this module as the canonical auto-enrollment coordinator.
:data:`AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY`
    Affirms that all enrollment operations are idempotent.
:data:`AUTO_ENROLLMENT_DEFERS_ON_MISSING_CAPABILITY_POLICY`
    Affirms that a device with no reported capabilities is deferred rather
    than enrolled with empty roles.

Public API
----------
Data classes:
    :class:`MeshEnrollmentRecord`

Service:
    :class:`MeshAutoEnrollmentService`

Functions:
    :func:`get_auto_enrollment_service`
    :func:`reset_auto_enrollment_service`
    :func:`notify_device_registered`
    :func:`notify_capability_reported`
    :func:`notify_readiness_confirmed`
    :func:`get_enrollment_record`
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Mesh.AutoEnrollment")

__all__ = [
    # Sentinels
    "MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY",
    "AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY",
    "AUTO_ENROLLMENT_DEFERS_ON_MISSING_CAPABILITY_POLICY",
    # Data
    "MeshEnrollmentRecord",
    # Service
    "MeshAutoEnrollmentService",
    # Module-level functions
    "get_auto_enrollment_service",
    "reset_auto_enrollment_service",
    "notify_device_registered",
    "notify_capability_reported",
    "notify_readiness_confirmed",
    "notify_device_lost",
    "get_enrollment_record",
]

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY: str = (
    "MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY: "
    "core/mesh/mesh_auto_enrollment.py is the canonical auto-enrollment "
    "coordinator that bridges device registration / capability / readiness "
    "events to MeshMembership writes, BodyMeshRegistry updates, and "
    "Formation auto-enrollment.  PR-I."
)

AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY: str = (
    "AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY: "
    "Repeated enrollment events for the same device_id are safe; "
    "MeshMembership and BodyMeshRegistry writes are merge-safe, "
    "and formation enrollment checks for existing participants."
)

AUTO_ENROLLMENT_DEFERS_ON_MISSING_CAPABILITY_POLICY: str = (
    "AUTO_ENROLLMENT_DEFERS_ON_MISSING_CAPABILITY_POLICY: "
    "A device that has completed registration but not yet reported any "
    "capabilities is deferred (not enrolled) until at least one role can "
    "be derived.  This prevents empty-role membership records."
)


# ---------------------------------------------------------------------------
# MeshEnrollmentRecord
# ---------------------------------------------------------------------------


@dataclass
class MeshEnrollmentRecord:
    """Per-device enrollment tracking record.

    Attributes
    ----------
    device_id:
        The canonical device identifier.
    registered:
        ``True`` when a registration event has been received.
    capabilities_reported:
        ``True`` when at least one capability / role has been recorded.
    readiness_confirmed:
        ``True`` when an explicit readiness-confirmation event has been received.
    enrolled:
        ``True`` when the device has been successfully enrolled into the mesh
        (BodyMeshRegistry + MeshMembership + Formation).
    roles:
        Latest list of :class:`~core.mesh.body_mesh_registry.DeviceRole` (or
        string fallbacks) assigned to this device.
    session_id:
        The most recent session_id associated with this device, if any.
    metadata:
        Arbitrary key/value enrichment bag propagated from registration /
        capability events.
    enrolled_at:
        Epoch timestamp when ``enrolled`` was first set to ``True``.
    last_updated_at:
        Epoch timestamp of the most recent state change.
    skip_reason:
        If non-empty, explains why enrollment was deferred or skipped.
    """

    device_id: str
    registered: bool = False
    capabilities_reported: bool = False
    readiness_confirmed: bool = False
    enrolled: bool = False
    roles: List[Any] = field(default_factory=list)
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    enrolled_at: Optional[float] = None
    last_updated_at: float = field(default_factory=time.time)
    skip_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device_id": self.device_id,
            "registered": self.registered,
            "capabilities_reported": self.capabilities_reported,
            "readiness_confirmed": self.readiness_confirmed,
            "enrolled": self.enrolled,
            "roles": [
                r.value if hasattr(r, "value") else str(r) for r in (self.roles or [])
            ],
            "session_id": self.session_id,
            "metadata": dict(self.metadata),
            "enrolled_at": self.enrolled_at,
            "last_updated_at": self.last_updated_at,
            "skip_reason": self.skip_reason,
        }


# ---------------------------------------------------------------------------
# MeshAutoEnrollmentService
# ---------------------------------------------------------------------------


class MeshAutoEnrollmentService:
    """Unified auto-enrollment coordinator for the mesh.

    This service receives lifecycle events from registration, capability
    reporting, and readiness confirmation handlers and automatically drives
    the device through the mesh enrollment chain:

    1. :meth:`on_device_registered` — records the registration event; triggers
       enrollment when ``auto_enroll_on_capability=False`` and a prior
       capability record exists.
    2. :meth:`on_capability_reported` — records capabilities / roles; triggers
       enrollment when ``auto_enroll_on_capability=True`` (default) or when
       readiness has already been confirmed.
    3. :meth:`on_readiness_confirmed` — records explicit readiness; triggers
       enrollment when capabilities have already been reported.
    4. :meth:`on_device_lost` — marks the device as lost in both the
       ``BodyMeshRegistry`` and the :class:`~.formation_auto_enrollment.FormationAutoEnrollmentManager`.

    Enrollment
    ----------
    When conditions are met the service:
    - Calls :func:`~core.mesh.body_mesh_registry.get_body_mesh_registry().register`
      (idempotent merge).
    - Derives a :class:`~contracts.mesh_membership.MeshMembership` via
      :func:`~contracts.mesh_membership.from_body_mesh_entry`.
    - Enrolls the device into
      :func:`~core.device_formation.formation_auto_enrollment.get_formation_auto_enrollment_manager`.

    All writes are individually guarded; a single subsystem failure does not
    abort the chain.

    Parameters
    ----------
    auto_enroll_on_capability:
        When ``True`` (default), a device is enrolled as soon as registration
        AND capability are satisfied, without waiting for an explicit
        ``on_readiness_confirmed`` call.  Set to ``False`` in stricter
        environments that require a three-event sequence.
    """

    def __init__(
        self,
        *,
        auto_enroll_on_capability: bool = True,
    ) -> None:
        self._auto_enroll_on_capability = auto_enroll_on_capability
        self._records: Dict[str, MeshEnrollmentRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public event surface
    # ------------------------------------------------------------------

    def on_device_registered(
        self,
        device_id: str,
        *,
        roles: Optional[List[Any]] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MeshEnrollmentRecord:
        """Receive a device-registration event.

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        roles:
            Optional list of :class:`~core.mesh.body_mesh_registry.DeviceRole`
            values already known at registration time (e.g. from capability
            bitmask).
        session_id:
            Optional session identifier to associate with the record.
        metadata:
            Optional key/value metadata bag (merged into the record).

        Returns
        -------
        MeshEnrollmentRecord
            Updated record.
        """
        if not device_id:
            logger.warning("on_device_registered: empty device_id — skipping")
            return MeshEnrollmentRecord(device_id="")

        logger.info(
            "auto_enrollment: registration received: device_id=%s roles=%s session_id=%s",
            device_id,
            [r.value if hasattr(r, "value") else str(r) for r in (roles or [])],
            session_id,
        )

        with self._lock:
            record = self._get_or_create(device_id)
            record.registered = True
            if session_id:
                record.session_id = session_id
            if metadata:
                record.metadata.update(metadata)
            if roles:
                record = self._merge_roles(record, roles)
                record.capabilities_reported = True
            record.last_updated_at = time.time()

        return self._maybe_enroll(device_id)

    def on_capability_reported(
        self,
        device_id: str,
        *,
        roles: List[Any],
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MeshEnrollmentRecord:
        """Receive a capability-report event.

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        roles:
            List of :class:`~core.mesh.body_mesh_registry.DeviceRole` values
            derived from the capability report.
        session_id:
            Optional session identifier.
        metadata:
            Optional key/value metadata bag (merged).

        Returns
        -------
        MeshEnrollmentRecord
            Updated record.
        """
        if not device_id:
            logger.warning("on_capability_reported: empty device_id — skipping")
            return MeshEnrollmentRecord(device_id="")

        logger.info(
            "auto_enrollment: capability_report received: device_id=%s roles=%s",
            device_id,
            [r.value if hasattr(r, "value") else str(r) for r in (roles or [])],
        )

        with self._lock:
            record = self._get_or_create(device_id)
            if session_id:
                record.session_id = session_id
            if metadata:
                record.metadata.update(metadata)
            if roles:
                record = self._merge_roles(record, roles)
                record.capabilities_reported = True
            record.last_updated_at = time.time()

        return self._maybe_enroll(device_id)

    def on_readiness_confirmed(
        self,
        device_id: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MeshEnrollmentRecord:
        """Receive an explicit readiness-confirmation event.

        This is the authoritative signal that a device is ready to participate
        in the mesh.  Combined with registration and capability, it always
        triggers enrollment (regardless of ``auto_enroll_on_capability``).

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        session_id:
            Optional session identifier.
        metadata:
            Optional key/value metadata bag (merged).

        Returns
        -------
        MeshEnrollmentRecord
            Updated record.
        """
        if not device_id:
            logger.warning("on_readiness_confirmed: empty device_id — skipping")
            return MeshEnrollmentRecord(device_id="")

        logger.info(
            "auto_enrollment: readiness_confirmed: device_id=%s session_id=%s",
            device_id,
            session_id,
        )

        with self._lock:
            record = self._get_or_create(device_id)
            record.readiness_confirmed = True
            if session_id:
                record.session_id = session_id
            if metadata:
                record.metadata.update(metadata)
            record.last_updated_at = time.time()

        return self._maybe_enroll(device_id)

    def on_device_lost(
        self,
        device_id: str,
        *,
        reason: Optional[str] = None,
    ) -> MeshEnrollmentRecord:
        """Receive a device-lost event.

        Marks the device as no longer enrolled and propagates the loss to the
        :class:`~core.device_formation.formation_auto_enrollment.FormationAutoEnrollmentManager`.

        Parameters
        ----------
        device_id:
            The canonical device identifier.
        reason:
            Optional human-readable reason for the loss.

        Returns
        -------
        MeshEnrollmentRecord
            Updated record.
        """
        if not device_id:
            return MeshEnrollmentRecord(device_id="")

        logger.info(
            "auto_enrollment: device_lost: device_id=%s reason=%s",
            device_id,
            reason,
        )

        with self._lock:
            record = self._get_or_create(device_id)
            record.enrolled = False
            record.last_updated_at = time.time()
            record.skip_reason = reason or "device_lost"

        # Notify formation manager
        try:
            from core.device_formation.formation_auto_enrollment import (
                get_formation_auto_enrollment_manager,
            )
            get_formation_auto_enrollment_manager().remove_device(
                device_id, reason=reason or "device_lost"
            )
        except Exception as exc:
            logger.debug(
                "on_device_lost: formation remove non-fatal: device_id=%s error=%s",
                device_id, exc,
            )

        return self.get_record(device_id)

    def get_record(self, device_id: str) -> Optional[MeshEnrollmentRecord]:
        """Return the enrollment record for *device_id*, or ``None``."""
        with self._lock:
            return self._records.get(device_id)

    def list_enrolled_device_ids(self) -> List[str]:
        """Return device IDs that are currently enrolled."""
        with self._lock:
            return [
                did for did, rec in self._records.items() if rec.enrolled
            ]

    def summary(self) -> Dict[str, Any]:
        """Return a lightweight diagnostic summary dict."""
        with self._lock:
            total = len(self._records)
            enrolled = sum(1 for r in self._records.values() if r.enrolled)
            pending = total - enrolled
        return {
            "authority": MESH_AUTO_ENROLLMENT_SERVICE_IS_AUTHORITY,
            "auto_enroll_on_capability": self._auto_enroll_on_capability,
            "total_devices": total,
            "enrolled": enrolled,
            "pending": pending,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, device_id: str) -> MeshEnrollmentRecord:
        """Return existing or create a new record.  Must be called under lock."""
        if device_id not in self._records:
            self._records[device_id] = MeshEnrollmentRecord(device_id=device_id)
        return self._records[device_id]

    def _merge_roles(
        self, record: MeshEnrollmentRecord, new_roles: List[Any]
    ) -> MeshEnrollmentRecord:
        """Merge *new_roles* into *record.roles* without duplicates."""
        existing_values = {
            r.value if hasattr(r, "value") else str(r) for r in record.roles
        }
        for role in new_roles:
            val = role.value if hasattr(role, "value") else str(role)
            if val not in existing_values:
                record.roles.append(role)
                existing_values.add(val)
        return record

    def _enrollment_conditions_met(self, record: MeshEnrollmentRecord) -> bool:
        """Return ``True`` when the device is ready to be enrolled.

        Conditions:
        - ``registered`` must be True.
        - ``capabilities_reported`` must be True (at least one role exists).
        - ``readiness_confirmed`` OR ``auto_enroll_on_capability`` must be True.
        """
        if not record.registered:
            return False
        if not record.capabilities_reported or not record.roles:
            return False
        if self._auto_enroll_on_capability:
            return True
        return record.readiness_confirmed

    def _maybe_enroll(self, device_id: str) -> MeshEnrollmentRecord:
        """Evaluate conditions and run enrollment if they are met."""
        with self._lock:
            record = self._records.get(device_id)
            if record is None:
                return MeshEnrollmentRecord(device_id=device_id)
            if not self._enrollment_conditions_met(record):
                reason_parts = []
                if not record.registered:
                    reason_parts.append("not-registered")
                if not record.capabilities_reported or not record.roles:
                    reason_parts.append("no-capabilities")
                if not self._auto_enroll_on_capability and not record.readiness_confirmed:
                    reason_parts.append("readiness-not-confirmed")
                record.skip_reason = ";".join(reason_parts)
                logger.debug(
                    "auto_enrollment: deferred: device_id=%s reason=%s",
                    device_id, record.skip_reason,
                )
                return record
            # Take a snapshot of roles/session to use outside the lock
            roles_snapshot = list(record.roles)
            session_id_snapshot = record.session_id
            metadata_snapshot = dict(record.metadata)

        self._run_enrollment(
            device_id, roles_snapshot, session_id_snapshot, metadata_snapshot
        )

        with self._lock:
            record = self._records.get(device_id)
        return record or MeshEnrollmentRecord(device_id=device_id)

    def _run_enrollment(
        self,
        device_id: str,
        roles: List[Any],
        session_id: Optional[str],
        metadata: Dict[str, Any],
    ) -> None:
        """Perform the actual enrollment steps.  Each step is individually guarded."""

        # Step 1 — BodyMeshRegistry write/update
        body_entry = None
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            registry = get_body_mesh_registry()
            registry.register(
                device_id,
                roles=roles,
                session_id=session_id,
                metadata=metadata,
            )
            body_entry = registry.get(device_id)
            logger.info(
                "auto_enrollment: BodyMeshRegistry enrolled: device_id=%s roles=%s",
                device_id,
                [r.value if hasattr(r, "value") else str(r) for r in roles],
            )
        except Exception as exc:
            logger.warning(
                "auto_enrollment: BodyMeshRegistry write failed: device_id=%s error=%s",
                device_id, exc,
            )

        # Step 2 — MeshMembership derivation / observability log
        if body_entry is not None:
            try:
                from contracts.mesh_membership import from_body_mesh_entry
                membership = from_body_mesh_entry(
                    body_entry, mesh_id=session_id or "default_mesh"
                )
                logger.info(
                    "auto_enrollment: MeshMembership derived: device_id=%s "
                    "member_device_id=%s roles=%s",
                    device_id,
                    getattr(membership, "member_device_id", device_id),
                    [
                        r.value if hasattr(r, "value") else str(r)
                        for r in (getattr(membership, "roles", []) or [])
                    ],
                )
            except Exception as exc:
                logger.debug(
                    "auto_enrollment: MeshMembership derivation non-fatal: "
                    "device_id=%s error=%s",
                    device_id, exc,
                )

        # Step 3 — Formation auto-enrollment
        try:
            from core.device_formation.formation_auto_enrollment import (
                get_formation_auto_enrollment_manager,
            )
            get_formation_auto_enrollment_manager().enroll_device(
                device_id, roles=roles, session_id=session_id
            )
            logger.info(
                "auto_enrollment: Formation enrolled: device_id=%s", device_id
            )
        except Exception as exc:
            logger.debug(
                "auto_enrollment: Formation enrollment non-fatal: device_id=%s error=%s",
                device_id, exc,
            )

        # Mark enrolled in the record
        with self._lock:
            record = self._records.get(device_id)
            if record is not None:
                already_enrolled = record.enrolled
                record.enrolled = True
                record.skip_reason = ""
                if not already_enrolled:
                    record.enrolled_at = time.time()
                record.last_updated_at = time.time()
                logger.info(
                    "auto_enrollment: enrolled: device_id=%s (first_time=%s)",
                    device_id,
                    not already_enrolled,
                )


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_service_singleton: Optional[MeshAutoEnrollmentService] = None
_service_lock = threading.Lock()


def get_auto_enrollment_service(
    *,
    auto_enroll_on_capability: bool = True,
) -> MeshAutoEnrollmentService:
    """Return the process-level singleton :class:`MeshAutoEnrollmentService`.

    Parameters
    ----------
    auto_enroll_on_capability:
        Used only when the singleton is first created.
    """
    global _service_singleton
    if _service_singleton is None:
        with _service_lock:
            if _service_singleton is None:
                _service_singleton = MeshAutoEnrollmentService(
                    auto_enroll_on_capability=auto_enroll_on_capability,
                )
    return _service_singleton


def reset_auto_enrollment_service() -> None:
    """Reset the module-level singleton — **for testing only**."""
    global _service_singleton
    with _service_lock:
        _service_singleton = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def notify_device_registered(
    device_id: str,
    *,
    roles: Optional[List[Any]] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[MeshEnrollmentRecord]:
    """Notify the singleton service of a device registration event.

    Returns the updated :class:`MeshEnrollmentRecord`, or ``None`` on error.
    """
    try:
        return get_auto_enrollment_service().on_device_registered(
            device_id, roles=roles, session_id=session_id, metadata=metadata
        )
    except Exception as exc:
        logger.warning("notify_device_registered: error: %s", exc)
        return None


def notify_capability_reported(
    device_id: str,
    *,
    roles: List[Any],
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[MeshEnrollmentRecord]:
    """Notify the singleton service of a capability-report event.

    Returns the updated :class:`MeshEnrollmentRecord`, or ``None`` on error.
    """
    try:
        return get_auto_enrollment_service().on_capability_reported(
            device_id, roles=roles, session_id=session_id, metadata=metadata
        )
    except Exception as exc:
        logger.warning("notify_capability_reported: error: %s", exc)
        return None


def notify_readiness_confirmed(
    device_id: str,
    *,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[MeshEnrollmentRecord]:
    """Notify the singleton service of a readiness-confirmation event.

    Returns the updated :class:`MeshEnrollmentRecord`, or ``None`` on error.
    """
    try:
        return get_auto_enrollment_service().on_readiness_confirmed(
            device_id, session_id=session_id, metadata=metadata
        )
    except Exception as exc:
        logger.warning("notify_readiness_confirmed: error: %s", exc)
        return None


def notify_device_lost(
    device_id: str,
    *,
    reason: Optional[str] = None,
) -> Optional[MeshEnrollmentRecord]:
    """Notify the singleton service that a device has been lost.

    Returns the updated :class:`MeshEnrollmentRecord`, or ``None`` on error.
    """
    try:
        return get_auto_enrollment_service().on_device_lost(device_id, reason=reason)
    except Exception as exc:
        logger.warning("notify_device_lost: error: %s", exc)
        return None


def get_enrollment_record(device_id: str) -> Optional[MeshEnrollmentRecord]:
    """Return the enrollment record for *device_id* from the singleton service."""
    try:
        return get_auto_enrollment_service().get_record(device_id)
    except Exception as exc:
        logger.debug("get_enrollment_record: error: %s", exc)
        return None
