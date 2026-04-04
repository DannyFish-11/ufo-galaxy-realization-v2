#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/multi_device_coordination_authority.py
================================================
PR-6 (post-533 dual-repo runtime host unification, MAIN repo side):
Align multi-device coordination with canonical OpenClawd runtime authority.

**Architecture role**
---------------------
This module is the **canonical authority** for multi-device coordination roles
in the Galaxy runtime.  It explicitly models the four coordination roles that
devices may occupy in a multi-device session and provides mapping logic between
``source_runtime_posture`` (established in PR-533 / PR-1) and those roles.

Before this PR, multi-device formation described devices using
:class:`~core.device_formation.formation_role.FormationRole` (formation-level
participation) and routing-level ``DeviceRole``.  However, neither layer
explicitly modelled **canonical authority ownership** — i.e. which device
controls the runtime, which devices merely observe, and which devices are
pure execution targets with no control authority.

After this PR:

1. **Four canonical coordination roles** are defined and machine-readable:
   - ``source_controller``   — Owns the runtime authority; originated the
     request; may retain local execution or delegate to remote targets.
   - ``joined_runtime_participant`` — Joined the runtime session from a remote
     device; shares execution responsibility with the source controller.
   - ``target_only_executor``  — Executes tasks dispatched from the source
     controller but has no control-plane authority in this session.
   - ``observer_only``       — Receives read-only view of session state; no
     execution and no control authority.

2. **Canonical role derivation** is driven by ``source_runtime_posture`` and
   formation membership, keeping the derivation rules in one place.

3. **CoordinationRoleRecord** captures the role assignment for a device in a
   specific task/session, suitable for logging, projection payloads, and
   downstream authority checks.

4. **CoordinationRoleSnapshot** aggregates all per-device records within one
   formation/session, providing a machine-readable canonical view.

5. **Authority sentinels** make the canonical intent explicit and auditable.

Public API
----------
Sentinels::

    MULTI_DEVICE_COORDINATION_AUTHORITY
    MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL
    SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY
    TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY
    OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY
    COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY

Enums::

    CoordinationRole

Dataclasses::

    CoordinationRoleRecord
    CoordinationRoleSnapshot
    CoordinationRoleRuntime

Functions::

    derive_coordination_role(posture, formation_role) -> CoordinationRole
    build_coordination_role_record(…) -> CoordinationRoleRecord
    build_coordination_role_snapshot(records) -> CoordinationRoleSnapshot
    record_coordination_role(record) -> None
    get_coordination_role_runtime() -> CoordinationRoleRuntime
    reset_coordination_role_runtime() -> None
    get_source_controller_device_id(snapshot) -> Optional[str]

Relationship to other PR-6 components
--------------------------------------
* :class:`~core.device_formation.formation_role.FormationRole` —
  ``CoordinationRole`` is a higher-level authority classification that maps
  onto formation roles.  It does not replace :class:`FormationRole`.
* :mod:`core.source_runtime_posture` — ``source_runtime_posture`` is the
  primary signal for deriving coordination roles.
* :mod:`core.multi_device_control_integrity` — the PR-517 integrity layer
  reads coordination role records to strengthen its formation-truth audit.
* :mod:`core.multi_device_projection_canonicalization` — the PR-522
  enrichment layer now surfaces coordination roles in projection payloads.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
import time
import uuid
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.MultiDeviceCoordinationAuthority")

__all__ = [
    # Sentinels
    "MULTI_DEVICE_COORDINATION_AUTHORITY",
    "MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL",
    "SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY",
    "TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY",
    "OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY",
    "COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY",
    # Enums
    "CoordinationRole",
    # Dataclasses
    "CoordinationRoleRecord",
    "CoordinationRoleSnapshot",
    "CoordinationRoleRuntime",
    # Functions
    "derive_coordination_role",
    "build_coordination_role_record",
    "build_coordination_role_snapshot",
    "record_coordination_role",
    "get_coordination_role_runtime",
    "reset_coordination_role_runtime",
    "get_source_controller_device_id",
]

# ---------------------------------------------------------------------------
# Authority & policy sentinels
# ---------------------------------------------------------------------------

MULTI_DEVICE_COORDINATION_AUTHORITY: str = (
    "MULTI_DEVICE_COORDINATION_AUTHORITY::PR6_V1: "
    "Canonical authority for multi-device coordination role assignment. "
    "Derives source_controller / joined_runtime_participant / "
    "target_only_executor / observer_only roles from source_runtime_posture "
    "and formation membership.  Single source of coordination role truth "
    "for formation, projection, and session layers."
)

MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL: str = (
    "MULTI_DEVICE_COORDINATION_AUTHORITY::PR6_INTEGRATED: "
    "PR-6 (post-533 dual-repo runtime host unification, MAIN repo side) — "
    "multi-device coordination authority and role modeling are aligned with "
    "canonical OpenClawd runtime authority.  coordination role derivation "
    "is posture-driven; formation, projection, and integrity layers surface "
    "explicit role assignments."
)

SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY: str = (
    "MULTI_DEVICE_COORDINATION_AUTHORITY::SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY_V1: "
    "The source_controller role is the sole owner of runtime control authority "
    "in any multi-device session.  All other roles are subordinate.  A device "
    "with source_runtime_posture='control_only' or 'join_runtime' that "
    "originated the request is the source_controller; no other device may "
    "claim this role in the same session."
)

TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY: str = (
    "MULTI_DEVICE_COORDINATION_AUTHORITY::TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY_V1: "
    "A device assigned the target_only_executor coordination role has no "
    "control-plane authority.  It executes tasks delegated by the "
    "source_controller but may not initiate new dispatch decisions or modify "
    "formation membership."
)

OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY: str = (
    "MULTI_DEVICE_COORDINATION_AUTHORITY::OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY_V1: "
    "A device assigned the observer_only coordination role has neither "
    "control-plane authority nor execution responsibility.  It receives "
    "read-only updates from the session and must not affect task routing, "
    "result merging, or formation decisions."
)

COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY: str = (
    "MULTI_DEVICE_COORDINATION_AUTHORITY::COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY_V1: "
    "Coordination roles are derived from source_runtime_posture (canonical "
    "contract established in PR-533 / PR-1) and formation-level role "
    "assignments.  No module may assign coordination roles through a parallel "
    "authority path outside this derivation function."
)


# ---------------------------------------------------------------------------
# CoordinationRole enum
# ---------------------------------------------------------------------------


class CoordinationRole(str, Enum):
    """Canonical coordination role taxonomy for multi-device sessions.

    These four roles model **runtime authority ownership** for devices
    participating in a multi-device Galaxy session.  They sit above
    :class:`~core.device_formation.formation_role.FormationRole` (which
    models formation-level participation) and are driven by
    ``source_runtime_posture``.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.
    """

    SOURCE_CONTROLLER = "source_controller"
    """Owns runtime control authority.  Originated the request.  May delegate
    execution to remote targets but retains overall coordination authority."""

    JOINED_RUNTIME_PARTICIPANT = "joined_runtime_participant"
    """Joined the runtime session from a remote device with
    ``source_runtime_posture='join_runtime'``.  Shares execution
    responsibility with the source controller."""

    TARGET_ONLY_EXECUTOR = "target_only_executor"
    """Executes tasks dispatched from the source controller.  Has no
    control-plane authority; cannot initiate new dispatches or modify
    formation membership."""

    OBSERVER_ONLY = "observer_only"
    """Receives read-only updates from the session.  Has neither execution
    responsibility nor control-plane authority."""

    UNRESOLVED = "unresolved"
    """Role could not be determined from available signals.  Safe fallback
    pending further context."""


# Human-readable descriptions for each role.
_COORDINATION_ROLE_DESCRIPTIONS: Dict[str, str] = {
    CoordinationRole.SOURCE_CONTROLLER.value: (
        "Owns runtime control authority for this session.  The device that "
        "originated the request.  May delegate execution to remote targets "
        "while retaining overall coordination authority over the formation."
    ),
    CoordinationRole.JOINED_RUNTIME_PARTICIPANT.value: (
        "Joined the runtime session from a remote device with "
        "source_runtime_posture='join_runtime'.  Participates actively in "
        "execution alongside the source controller."
    ),
    CoordinationRole.TARGET_ONLY_EXECUTOR.value: (
        "Executes tasks delegated by the source controller but has no "
        "control-plane authority.  Cannot initiate new dispatch decisions "
        "or modify formation membership in this session."
    ),
    CoordinationRole.OBSERVER_ONLY.value: (
        "Receives read-only updates from the session.  No execution "
        "responsibility and no control-plane authority.  Suitable for "
        "companion screens, status boards, and monitoring integrations."
    ),
    CoordinationRole.UNRESOLVED.value: (
        "Coordination role could not be determined from available signals.  "
        "Safe fallback state pending context enrichment."
    ),
}


def coordination_role_description(role: CoordinationRole) -> str:
    """Return the human-readable description for *role*."""
    return _COORDINATION_ROLE_DESCRIPTIONS.get(role.value, "Unknown coordination role.")


# ---------------------------------------------------------------------------
# Role derivation
# ---------------------------------------------------------------------------

#: Formation roles that indicate a device is the source/originator.
_SOURCE_FORMATION_ROLES = frozenset({"source_device", "primary_execution_device"})

#: Formation roles that indicate a device is a pure observer.
_OBSERVER_FORMATION_ROLES = frozenset({"observer_device"})


def derive_coordination_role(
    *,
    source_runtime_posture: Optional[str] = None,
    formation_role: Optional[str] = None,
    is_source_device: bool = False,
    is_target_device: bool = False,
) -> CoordinationRole:
    """Derive the canonical :class:`CoordinationRole` for one device.

    Derivation rules (applied in priority order):

    1. If ``formation_role`` is an observer role → ``observer_only``
       (observer role is definitive regardless of posture).
    2. If ``is_source_device`` OR ``formation_role`` is a source/primary role:
       - ``source_runtime_posture == 'join_runtime'``
         → ``joined_runtime_participant``
       - otherwise → ``source_controller``
    3. If ``is_target_device`` AND NOT a source role
       → ``target_only_executor``
    4. Fallback → ``unresolved``

    Parameters
    ----------
    source_runtime_posture:
        The posture value from the device's context.  May be ``None`` or
        unrecognised; defaults safely to ``control_only`` semantics.
    formation_role:
        The string value of the device's
        :class:`~core.device_formation.formation_role.FormationRole`.
        Used as a secondary signal when ``is_source_device`` / ``is_target_device``
        are not explicitly provided.
    is_source_device:
        ``True`` if the device is the originator of the cross-device request.
    is_target_device:
        ``True`` if the device is a target execution device.

    Returns
    -------
    CoordinationRole
        The derived canonical coordination role.
    """
    # Normalise posture — unknown values fall back to control_only semantics.
    normalised_posture = _normalise_posture(source_runtime_posture)

    # Rule 1: observer role is definitive.
    if formation_role in _OBSERVER_FORMATION_ROLES:
        return CoordinationRole.OBSERVER_ONLY

    # Rule 2: source device or source formation role.
    is_source = is_source_device or (formation_role in _SOURCE_FORMATION_ROLES)
    if is_source:
        if normalised_posture == "join_runtime":
            return CoordinationRole.JOINED_RUNTIME_PARTICIPANT
        return CoordinationRole.SOURCE_CONTROLLER

    # Rule 3: target-only executor.
    if is_target_device:
        return CoordinationRole.TARGET_ONLY_EXECUTOR

    # Rule 4: fallback.
    return CoordinationRole.UNRESOLVED


def _normalise_posture(posture: Optional[str]) -> str:
    """Return a normalised posture string; unknown values → 'control_only'."""
    if posture in ("control_only", "join_runtime"):
        return posture
    return "control_only"


# ---------------------------------------------------------------------------
# CoordinationRoleRecord
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CoordinationRoleRecord:
    """Per-device coordination role record for one task/session.

    Attributes
    ----------
    record_id:
        Stable unique identifier for this record.
    task_id:
        Identifier of the task this assignment belongs to.
    trace_id:
        Optional distributed-trace identifier.
    device_id:
        The device whose role is being recorded.
    coordination_role:
        The derived :class:`CoordinationRole`.
    source_runtime_posture:
        The ``source_runtime_posture`` value that contributed to derivation.
    formation_role:
        The :class:`~core.device_formation.formation_role.FormationRole`
        string value that contributed to derivation (may be ``None``).
    is_source_device:
        Whether this device was the request originator.
    is_target_device:
        Whether this device was a dispatch target.
    has_control_authority:
        Derived boolean: only ``source_controller`` and
        ``joined_runtime_participant`` have control authority.
    has_execution_responsibility:
        Derived boolean: all roles except ``observer_only`` have execution
        responsibility (when it matches their role scope).
    derivation_reason:
        Human-readable explanation of why this role was assigned.
    timestamp:
        Wall-clock time when the record was created.
    extra:
        Arbitrary additional metadata for diagnostics.
    """

    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    device_id: str = ""
    coordination_role: CoordinationRole = CoordinationRole.UNRESOLVED
    source_runtime_posture: str = "control_only"
    formation_role: Optional[str] = None
    is_source_device: bool = False
    is_target_device: bool = False
    has_control_authority: bool = False
    has_execution_responsibility: bool = False
    derivation_reason: str = ""
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        # Derive authority / responsibility flags from the assigned role.
        self.has_control_authority = self.coordination_role in (
            CoordinationRole.SOURCE_CONTROLLER,
            CoordinationRole.JOINED_RUNTIME_PARTICIPANT,
        )
        self.has_execution_responsibility = self.coordination_role not in (
            CoordinationRole.OBSERVER_ONLY,
            CoordinationRole.UNRESOLVED,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "device_id": self.device_id,
            "coordination_role": self.coordination_role.value,
            "source_runtime_posture": self.source_runtime_posture,
            "formation_role": self.formation_role,
            "is_source_device": self.is_source_device,
            "is_target_device": self.is_target_device,
            "has_control_authority": self.has_control_authority,
            "has_execution_responsibility": self.has_execution_responsibility,
            "derivation_reason": self.derivation_reason,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
            "authority": MULTI_DEVICE_COORDINATION_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# CoordinationRoleSnapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CoordinationRoleSnapshot:
    """Aggregated coordination role state for one formation/session.

    Attributes
    ----------
    snapshot_id:
        Stable unique identifier for this snapshot.
    task_id:
        Task identifier this snapshot covers.
    trace_id:
        Optional distributed-trace identifier.
    records:
        Ordered list of :class:`CoordinationRoleRecord` objects, one per
        participating device.
    source_controller_device_id:
        Device ID of the device assigned ``source_controller`` role, or
        ``None`` when not yet determined.
    has_joined_runtime_participant:
        ``True`` if at least one device is a ``joined_runtime_participant``.
    target_only_executor_device_ids:
        List of device IDs assigned ``target_only_executor`` role.
    observer_only_device_ids:
        List of device IDs assigned ``observer_only`` role.
    unresolved_device_ids:
        List of device IDs whose role is ``unresolved``.
    is_authority_clear:
        ``True`` when exactly one ``source_controller`` is present and no
        ``unresolved`` roles remain.
    timestamp:
        Wall-clock time when the snapshot was assembled.
    """

    snapshot_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    records: List[CoordinationRoleRecord] = dataclasses.field(default_factory=list)
    source_controller_device_id: Optional[str] = None
    has_joined_runtime_participant: bool = False
    target_only_executor_device_ids: List[str] = dataclasses.field(default_factory=list)
    observer_only_device_ids: List[str] = dataclasses.field(default_factory=list)
    unresolved_device_ids: List[str] = dataclasses.field(default_factory=list)
    is_authority_clear: bool = False
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_controller_device_id": self.source_controller_device_id,
            "has_joined_runtime_participant": self.has_joined_runtime_participant,
            "target_only_executor_device_ids": list(self.target_only_executor_device_ids),
            "observer_only_device_ids": list(self.observer_only_device_ids),
            "unresolved_device_ids": list(self.unresolved_device_ids),
            "is_authority_clear": self.is_authority_clear,
            "record_count": len(self.records),
            "records": [r.to_dict() for r in self.records],
            "timestamp": self.timestamp,
            "authority": MULTI_DEVICE_COORDINATION_AUTHORITY,
            "pr6_sentinel": MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL,
        }


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def build_coordination_role_record(
    *,
    device_id: str,
    task_id: str = "",
    trace_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    formation_role: Optional[str] = None,
    is_source_device: bool = False,
    is_target_device: bool = False,
    derivation_reason: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> CoordinationRoleRecord:
    """Build a :class:`CoordinationRoleRecord` for one device.

    Calls :func:`derive_coordination_role` internally so callers do not need
    to invoke the derivation function separately.
    """
    posture = _normalise_posture(source_runtime_posture)
    role = derive_coordination_role(
        source_runtime_posture=posture,
        formation_role=formation_role,
        is_source_device=is_source_device,
        is_target_device=is_target_device,
    )
    reason = derivation_reason or (
        f"derived from posture={posture!r} formation_role={formation_role!r} "
        f"is_source={is_source_device} is_target={is_target_device}"
    )
    return CoordinationRoleRecord(
        task_id=task_id,
        trace_id=trace_id,
        device_id=device_id,
        coordination_role=role,
        source_runtime_posture=posture,
        formation_role=formation_role,
        is_source_device=is_source_device,
        is_target_device=is_target_device,
        derivation_reason=reason,
        extra=dict(extra) if extra else {},
    )


def build_coordination_role_snapshot(
    records: List[CoordinationRoleRecord],
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
) -> CoordinationRoleSnapshot:
    """Build a :class:`CoordinationRoleSnapshot` from a list of records.

    Parameters
    ----------
    records:
        One :class:`CoordinationRoleRecord` per participating device.
    task_id:
        Task identifier this snapshot covers.  If not supplied the first
        record's ``task_id`` is used.
    trace_id:
        Optional distributed-trace identifier.
    """
    if not task_id and records:
        task_id = records[0].task_id
    if trace_id is None and records:
        trace_id = records[0].trace_id

    source_controller_id: Optional[str] = None
    has_joined = False
    target_ids: List[str] = []
    observer_ids: List[str] = []
    unresolved_ids: List[str] = []

    for rec in records:
        if rec.coordination_role == CoordinationRole.SOURCE_CONTROLLER:
            if source_controller_id is None:
                source_controller_id = rec.device_id
            else:
                # Multiple source controllers — authority is ambiguous.
                logger.warning(
                    "COORDINATION_AUTHORITY_AMBIGUOUS | task_id=%s "
                    "first_controller=%s second_controller=%s",
                    task_id,
                    source_controller_id,
                    rec.device_id,
                )
        elif rec.coordination_role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT:
            has_joined = True
        elif rec.coordination_role == CoordinationRole.TARGET_ONLY_EXECUTOR:
            target_ids.append(rec.device_id)
        elif rec.coordination_role == CoordinationRole.OBSERVER_ONLY:
            observer_ids.append(rec.device_id)
        elif rec.coordination_role == CoordinationRole.UNRESOLVED:
            unresolved_ids.append(rec.device_id)

    is_authority_clear = (
        source_controller_id is not None and len(unresolved_ids) == 0
    )

    return CoordinationRoleSnapshot(
        task_id=task_id,
        trace_id=trace_id,
        records=list(records),
        source_controller_device_id=source_controller_id,
        has_joined_runtime_participant=has_joined,
        target_only_executor_device_ids=target_ids,
        observer_only_device_ids=observer_ids,
        unresolved_device_ids=unresolved_ids,
        is_authority_clear=is_authority_clear,
    )


def get_source_controller_device_id(
    snapshot: CoordinationRoleSnapshot,
) -> Optional[str]:
    """Return the device ID of the ``source_controller`` in *snapshot*, or
    ``None`` if none is present."""
    return snapshot.source_controller_device_id


# ---------------------------------------------------------------------------
# CoordinationRoleRuntime (ring-buffer singleton)
# ---------------------------------------------------------------------------

_COORDINATION_ROLE_RUNTIME_RING_SIZE: int = 64


class CoordinationRoleRuntime:
    """In-memory ring-buffer store for :class:`CoordinationRoleRecord` objects.

    The runtime is a singleton (accessed via :func:`get_coordination_role_runtime`)
    and stores at most :data:`_COORDINATION_ROLE_RUNTIME_RING_SIZE` records.
    It is intentionally lightweight: no persistence, no I/O, no blocking.
    """

    def __init__(self, max_size: int = _COORDINATION_ROLE_RUNTIME_RING_SIZE) -> None:
        self._max_size = max_size
        self._records: Deque[CoordinationRoleRecord] = collections.deque(
            maxlen=max_size
        )

    def record(self, rec: CoordinationRoleRecord) -> None:
        """Append *rec* to the ring buffer."""
        self._records.append(rec)

    def snapshot(self, max_recent: int = 20) -> List[CoordinationRoleRecord]:
        """Return the *max_recent* most recent records (newest-last order)."""
        all_records = list(self._records)
        return all_records[-max_recent:]

    def __len__(self) -> int:
        return len(self._records)


# Module-level singleton.
_GLOBAL_COORDINATION_ROLE_RUNTIME: Optional[CoordinationRoleRuntime] = None


def get_coordination_role_runtime() -> CoordinationRoleRuntime:
    """Return (or lazily create) the global :class:`CoordinationRoleRuntime`."""
    global _GLOBAL_COORDINATION_ROLE_RUNTIME
    if _GLOBAL_COORDINATION_ROLE_RUNTIME is None:
        _GLOBAL_COORDINATION_ROLE_RUNTIME = CoordinationRoleRuntime()
    return _GLOBAL_COORDINATION_ROLE_RUNTIME


def reset_coordination_role_runtime() -> None:
    """Reset the global singleton.  Intended for tests only."""
    global _GLOBAL_COORDINATION_ROLE_RUNTIME
    _GLOBAL_COORDINATION_ROLE_RUNTIME = None


def record_coordination_role(rec: CoordinationRoleRecord) -> None:
    """Append *rec* to the global :class:`CoordinationRoleRuntime`.

    Fire-and-forget — never raises.
    """
    if not isinstance(rec, CoordinationRoleRecord):
        return
    try:
        get_coordination_role_runtime().record(rec)
    except Exception:  # pragma: no cover
        pass
