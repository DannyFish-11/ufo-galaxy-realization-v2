#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.mesh_participation_summary
=================================

PR-8 — Unified Formation, Mesh, and Session Participation Summaries.

This module provides a **canonical, additive summary layer** that flattens
current mesh/session/formation state into a single, serialisable view.

The summary can be used by:

- Participation logic (role assignment, authority checks).
- Projections (read-only diagnostic surfaces).
- Debugging and observability tooling.
- Orchestration diagnostics (without changing orchestration behaviour).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every helper returns a valid result even when
  optional subsystems are unavailable; reasons are recorded instead of
  raising.
- **Defensive imports** — each subsystem is imported lazily inside a
  ``try/except`` block so that missing dependencies never prevent the
  module from loading.
- **No circular imports** — this module only imports from ``contracts.*``
  and ``core.device_formation``, ``core.mesh``, ``core.cross_device_policy``.
  It does **not** import from ``core.command_router``, ``core.unified``,
  or ``galaxy_gateway``.
- **No orchestration side-effects** — the helpers are pure readers; they do
  not mutate any registry or session state.

Public surface
--------------
Model:
    :class:`MeshParticipationSummary` — unified dataclass summary.

Sentinel:
    :data:`MESH_PARTICIPATION_SUMMARY_AUTHORITY` — module identity string.
    :data:`EMPTY_MESH_PARTICIPATION_SUMMARY` — idle/empty pre-built instance.

Helpers:
    :func:`get_current_mesh_participation_summary` — aggregate from all
    available subsystems.

    :func:`get_device_mesh_summary` — extract a device-scoped view from the
    current summary.

Usage::

    from core.mesh_participation_summary import (
        MeshParticipationSummary,
        get_current_mesh_participation_summary,
        get_device_mesh_summary,
        EMPTY_MESH_PARTICIPATION_SUMMARY,
    )

    summary = get_current_mesh_participation_summary()
    print(summary.to_dict())

    device_view = get_device_mesh_summary("phone_001")
    print(device_view)
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

__all__ = [
    "MESH_PARTICIPATION_SUMMARY_AUTHORITY",
    "MESH_SUMMARY_SUBORDINATE_TO_READINESS",
    "MeshParticipationSummary",
    "EMPTY_MESH_PARTICIPATION_SUMMARY",
    "get_current_mesh_participation_summary",
    "get_device_mesh_summary",
]


# ---------------------------------------------------------------------------
# Lazy module-level references (patchable by tests)
# ---------------------------------------------------------------------------
# These thin wrappers delegate to the real implementations lazily so that
# the module loads even when subsystems are absent, while still being
# patchable via ``unittest.mock.patch("core.mesh_participation_summary.*")``.


def resolve_formation_summary(**kwargs: Any) -> Any:  # type: ignore[return]
    """Lazy proxy for :func:`core.device_formation.formation_summary.resolve_formation_summary`."""
    from core.device_formation.formation_summary import (
        resolve_formation_summary as _real,
    )
    return _real(**kwargs)


def get_body_mesh_registry() -> Any:  # type: ignore[return]
    """Lazy proxy for :func:`core.mesh.body_mesh_registry.get_body_mesh_registry`."""
    from core.mesh.body_mesh_registry import get_body_mesh_registry as _real

    return _real()

#: Module-level authority sentinel — identifies this module unambiguously in
#: diagnostic / registry surfaces.
MESH_PARTICIPATION_SUMMARY_AUTHORITY = (
    "core.mesh_participation_summary:MESH_PARTICIPATION_SUMMARY_AUTHORITY"
)

#: Affirms that mesh/session summaries are *subordinate* to Layer-1 canonical
#: readiness (``core.device_readiness``) and Layer-2 participation
#: (``core.device_participation``).
#:
#: Mesh membership or session visibility does NOT automatically imply:
#:   - that a device is registered (Layer-1 readiness fact)
#:   - that a device is routable (Layer-1 readiness fact)
#:   - that a device is orchestration-eligible (Layer-2 participation fact)
#:
#: This summary is enrichment data only.  Callers must consult the canonical
#: admissibility chain (``core.admissibility_chain``) for authoritative facts.
MESH_SUMMARY_SUBORDINATE_TO_READINESS: bool = True

_logger = logging.getLogger("Galaxy.MeshParticipationSummary")


# ---------------------------------------------------------------------------
# MeshParticipationSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class MeshParticipationSummary:
    """Unified, serialisable summary of mesh/session/formation participation.

    This is the canonical view of participation state, flattening fields from:

    - :class:`~core.device_formation.formation_summary.FormationSummary`
      (PR-17)
    - :class:`~contracts.mesh_membership.MeshMembership` (PR-32)
    - :class:`~contracts.mesh_session.MeshSession` (PR-33)
    - :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
      (PR-37)
    - :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` (PR-4)

    All fields are optional (beyond ``device_ids``) so that the summary can
    be populated incrementally from whichever subsystems are available.

    Attributes
    ----------
    session_id:
        Session identifier, when a mesh session is active.
    device_ids:
        All device IDs participating in the current mesh/formation.
    primary_device_id:
        The device anchoring the current cognitive/execution session.
    source_device_id:
        The device that originated the current request/task.
    roles_by_device:
        Mapping from device ID → list of role strings for that device.
    merge_policy:
        Merge policy string (e.g. ``"parallel"``, ``"sequential"``).
    barrier_posture:
        Barrier/completion posture string (e.g. ``"wait_primary"``).
    routing_intents:
        Mapping from device ID → routing intent string.
    reasons:
        List of human-readable reasons or diagnostic messages collected
        during summary assembly.
    sources:
        Mapping from subsystem name → raw subsystem data (serialisable).
        Useful for debugging without re-querying subsystems.
    """

    session_id: Optional[str] = None
    device_ids: List[str] = dataclasses.field(default_factory=list)
    primary_device_id: Optional[str] = None
    source_device_id: Optional[str] = None
    roles_by_device: Dict[str, List[str]] = dataclasses.field(default_factory=dict)
    merge_policy: Optional[str] = None
    barrier_posture: Optional[str] = None
    routing_intents: Dict[str, str] = dataclasses.field(default_factory=dict)
    reasons: List[str] = dataclasses.field(default_factory=list)
    sources: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "session_id": self.session_id,
            "device_ids": list(self.device_ids),
            "primary_device_id": self.primary_device_id,
            "source_device_id": self.source_device_id,
            "roles_by_device": {k: list(v) for k, v in self.roles_by_device.items()},
            "merge_policy": self.merge_policy,
            "barrier_posture": self.barrier_posture,
            "routing_intents": dict(self.routing_intents),
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string of :meth:`to_dict`."""
        import json as _json

        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshParticipationSummary":
        """Reconstruct a :class:`MeshParticipationSummary` from a dict.

        Unknown keys are silently ignored.  Missing keys fall back to
        defaults.
        """
        if not isinstance(data, dict):
            return cls()
        return cls(
            session_id=data.get("session_id"),
            device_ids=list(data.get("device_ids") or []),
            primary_device_id=data.get("primary_device_id"),
            source_device_id=data.get("source_device_id"),
            roles_by_device={
                k: list(v)
                for k, v in (data.get("roles_by_device") or {}).items()
            },
            merge_policy=data.get("merge_policy"),
            barrier_posture=data.get("barrier_posture"),
            routing_intents=dict(data.get("routing_intents") or {}),
            reasons=list(data.get("reasons") or []),
            sources=dict(data.get("sources") or {}),
        )


# ---------------------------------------------------------------------------
# Internal aggregation helpers
# ---------------------------------------------------------------------------


def _aggregate_from_formation_summary(
    summary: "MeshParticipationSummary",
) -> None:
    """Populate *summary* from the current device formation summary.

    Uses :func:`resolve_formation_summary` which always returns a valid
    object, never raises.
    """
    try:
        fs = resolve_formation_summary()
        summary.sources["formation_summary"] = fs.to_dict()

        # Device IDs
        _merge_device_ids(summary, fs.all_member_device_ids or [])

        # Primary / source
        if fs.primary_execution_device_id and not summary.primary_device_id:
            summary.primary_device_id = fs.primary_execution_device_id
        if fs.source_device_id and not summary.source_device_id:
            summary.source_device_id = fs.source_device_id

        # Barrier posture
        if fs.barrier_posture and not summary.barrier_posture:
            summary.barrier_posture = fs.barrier_posture

        # Roles by device
        _merge_role(summary.roles_by_device, fs.source_device_id, "source")
        _merge_role(summary.roles_by_device, fs.primary_execution_device_id, "primary")
        _merge_role(summary.roles_by_device, fs.merge_owner_device_id, "merge_owner")
        for did in fs.fallback_device_ids or []:
            _merge_role(summary.roles_by_device, did, "fallback")
        for did in fs.support_device_ids or []:
            _merge_role(summary.roles_by_device, did, "support")
        for did in fs.observer_device_ids or []:
            _merge_role(summary.roles_by_device, did, "observer")
        for did in fs.relay_device_ids or []:
            _merge_role(summary.roles_by_device, did, "relay")

        if fs.formation_reason and fs.formation_reason != "no active formation":
            summary.reasons.append(f"formation: {fs.formation_reason}")

    except Exception as exc:  # pragma: no cover – defensive
        summary.reasons.append(f"formation_summary unavailable: {exc}")
        _logger.debug("formation_summary aggregation failed: %s", exc)


def _aggregate_from_body_mesh_registry(
    summary: "MeshParticipationSummary",
) -> None:
    """Populate *summary* from the body mesh registry."""
    try:
        registry = get_body_mesh_registry()
        entries = list(registry.entries.values()) if hasattr(registry, "entries") else []

        source_data: List[Dict[str, Any]] = []
        for entry in entries:
            did = getattr(entry, "device_id", None)
            if not did:
                continue
            _merge_device_ids(summary, [did])
            roles = getattr(entry, "roles", [])
            role_strs = [r.value if hasattr(r, "value") else str(r) for r in roles]
            for role_str in role_strs:
                _merge_role(summary.roles_by_device, did, role_str)
            source_data.append(
                {
                    "device_id": did,
                    "roles": role_strs,
                    "session_id": getattr(entry, "session_id", None),
                    "body_score": getattr(entry, "body_score", None),
                }
            )

        if source_data:
            summary.sources["body_mesh_registry"] = source_data

        # Derive primary from registry primary_device_id method if available
        if hasattr(registry, "primary_device_id") and not summary.primary_device_id:
            primary = registry.primary_device_id()
            if primary:
                summary.primary_device_id = primary
                _merge_role(summary.roles_by_device, primary, "primary")

    except Exception as exc:
        summary.reasons.append(f"body_mesh_registry unavailable: {exc}")
        _logger.debug("body_mesh_registry aggregation failed: %s", exc)


def _aggregate_from_mesh_session(
    summary: "MeshParticipationSummary",
) -> None:
    """Populate *summary* from a mesh session via :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry`."""
    try:
        registry = get_body_mesh_registry()
        if not hasattr(registry, "get_mesh_session"):
            return

        mesh_session = registry.get_mesh_session()
        if mesh_session is None:
            return

        summary.sources["mesh_session"] = (
            mesh_session.to_dict()
            if hasattr(mesh_session, "to_dict")
            else str(mesh_session)
        )

        # Session ID
        sid = getattr(mesh_session, "session_id", None)
        if sid and not summary.session_id:
            summary.session_id = sid

        # Primary / source
        primary = getattr(mesh_session, "primary_device_id", None)
        if primary and not summary.primary_device_id:
            summary.primary_device_id = primary

        source = getattr(mesh_session, "source_device_id", None)
        if source and not summary.source_device_id:
            summary.source_device_id = source

        # Merge policy / barrier posture
        mp = getattr(mesh_session, "merge_policy", None)
        if mp and not summary.merge_policy:
            summary.merge_policy = mp.value if hasattr(mp, "value") else str(mp)

        bp = getattr(mesh_session, "barrier_posture", None)
        if bp and not summary.barrier_posture:
            summary.barrier_posture = bp.value if hasattr(bp, "value") else str(bp)

        # Participants
        participants = getattr(mesh_session, "participants", []) or []
        for p in participants:
            did = getattr(p, "device_id", None)
            if not did:
                continue
            _merge_device_ids(summary, [did])
            roles = getattr(p, "roles", []) or []
            for role in roles:
                _merge_role(summary.roles_by_device, did, str(role))

    except Exception as exc:
        summary.reasons.append(f"mesh_session unavailable: {exc}")
        _logger.debug("mesh_session aggregation failed: %s", exc)


def _aggregate_from_mesh_membership(
    summary: "MeshParticipationSummary",
) -> None:
    """Populate *summary* from mesh memberships via the body mesh registry."""
    try:
        registry = get_body_mesh_registry()
        if not hasattr(registry, "get_mesh_memberships"):
            return

        memberships = registry.get_mesh_memberships()
        if not memberships:
            return

        source_data: List[Dict[str, Any]] = []
        for m in memberships:
            did = getattr(m, "member_device_id", None)
            if not did:
                continue
            _merge_device_ids(summary, [did])

            # Roles
            roles = getattr(m, "roles", []) or []
            for role in roles:
                role_str = role.value if hasattr(role, "value") else str(role)
                _merge_role(summary.roles_by_device, did, role_str)

            # Routing intent
            ri = getattr(m, "routing_intent", None)
            if ri:
                ri_str = ri.value if hasattr(ri, "value") else str(ri)
                summary.routing_intents[did] = ri_str

            source_data.append(
                {
                    "member_device_id": did,
                    "mesh_id": getattr(m, "mesh_id", None),
                    "roles": [
                        r.value if hasattr(r, "value") else str(r)
                        for r in (getattr(m, "roles", []) or [])
                    ],
                    "routing_intent": summary.routing_intents.get(did),
                }
            )

        if source_data:
            summary.sources["mesh_membership"] = source_data

    except Exception as exc:
        summary.reasons.append(f"mesh_membership unavailable: {exc}")
        _logger.debug("mesh_membership aggregation failed: %s", exc)


def _aggregate_from_mesh_session_coordinator(
    summary: "MeshParticipationSummary",
) -> None:
    """Populate *summary* from the mesh session coordinator state."""
    try:
        registry = get_body_mesh_registry()
        if not hasattr(registry, "get_mesh_session_coordinator"):
            return

        coordinator_state = registry.get_mesh_session_coordinator()
        if coordinator_state is None:
            return

        summary.sources["mesh_session_coordinator"] = (
            coordinator_state.to_dict()
            if hasattr(coordinator_state, "to_dict")
            else str(coordinator_state)
        )

        # Session ID from coordinator
        sid = getattr(coordinator_state, "session_id", None)
        if sid and not summary.session_id:
            summary.session_id = sid

        # Merge policy / barrier posture from coordinator
        mp = getattr(coordinator_state, "merge_policy", None)
        if mp and not summary.merge_policy:
            summary.merge_policy = mp.value if hasattr(mp, "value") else str(mp)

        bp = getattr(coordinator_state, "barrier_posture", None)
        if bp and not summary.barrier_posture:
            summary.barrier_posture = bp.value if hasattr(bp, "value") else str(bp)

    except Exception as exc:
        summary.reasons.append(f"mesh_session_coordinator unavailable: {exc}")
        _logger.debug("mesh_session_coordinator aggregation failed: %s", exc)


def _aggregate_from_cross_device_policy(
    summary: "MeshParticipationSummary",
) -> None:
    """Populate *summary* from the cross-device routing assignment."""
    try:
        from core.cross_device_policy import build_assignment_summary

        routing_summary = build_assignment_summary()
        if routing_summary is None:
            return

        summary.sources["cross_device_policy"] = (
            routing_summary.to_dict()
            if hasattr(routing_summary, "to_dict")
            else {}
        )

        # Device IDs
        assigned = getattr(routing_summary, "assigned_device_ids", []) or []
        _merge_device_ids(summary, assigned)

        # Primary / source
        primary = getattr(routing_summary, "primary_device_id", None)
        if primary and not summary.primary_device_id:
            summary.primary_device_id = primary

        source = getattr(routing_summary, "source_device_id", None)
        if source and not summary.source_device_id:
            summary.source_device_id = source

        # Routing intents (best-effort from routing posture)
        posture = getattr(routing_summary, "routing_posture", None)
        if posture:
            posture_str = posture.value if hasattr(posture, "value") else str(posture)
            for did in assigned:
                if did not in summary.routing_intents:
                    summary.routing_intents[did] = posture_str

    except Exception as exc:
        summary.reasons.append(f"cross_device_policy unavailable: {exc}")
        _logger.debug("cross_device_policy aggregation failed: %s", exc)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _merge_device_ids(
    summary: "MeshParticipationSummary",
    device_ids: List[str],
) -> None:
    """Add *device_ids* to *summary.device_ids* without duplicates."""
    existing = set(summary.device_ids)
    for did in device_ids:
        if did and did not in existing:
            summary.device_ids.append(did)
            existing.add(did)


def _merge_role(
    roles_by_device: Dict[str, List[str]],
    device_id: Optional[str],
    role: str,
) -> None:
    """Add *role* to *roles_by_device[device_id]* without duplicates."""
    if not device_id or not role:
        return
    if device_id not in roles_by_device:
        roles_by_device[device_id] = []
    if role not in roles_by_device[device_id]:
        roles_by_device[device_id].append(role)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_current_mesh_participation_summary() -> MeshParticipationSummary:
    """Build and return the current unified mesh/session/formation summary.

    Aggregates from all available subsystems:

    1. Device formation summary (PR-17)
    2. Body mesh registry (PR-4)
    3. Mesh session (via registry, PR-33)
    4. Mesh membership (via registry, PR-32)
    5. Mesh session coordinator (via registry, PR-37)
    6. Cross-device routing policy (PR-13/PR-14)

    Each subsystem is queried defensively.  If a subsystem is unavailable
    or raises, a reason is recorded in :attr:`MeshParticipationSummary.reasons`
    and aggregation continues from the remaining subsystems.

    Returns
    -------
    MeshParticipationSummary
        A populated summary.  Never raises.
    """
    summary = MeshParticipationSummary()

    _aggregate_from_formation_summary(summary)
    _aggregate_from_body_mesh_registry(summary)
    _aggregate_from_mesh_session(summary)
    _aggregate_from_mesh_membership(summary)
    _aggregate_from_mesh_session_coordinator(summary)
    _aggregate_from_cross_device_policy(summary)

    return summary


def get_device_mesh_summary(device_id: str) -> Dict[str, Any]:
    """Return a device-scoped view of the current mesh participation summary.

    Calls :func:`get_current_mesh_participation_summary` and extracts
    the fields most relevant to the given *device_id*.

    Parameters
    ----------
    device_id:
        The device ID to scope the view to.

    Returns
    -------
    dict
        A dict with keys:
        - ``"device_id"`` — the requested device ID.
        - ``"found"`` — whether the device appears in the current summary.
        - ``"roles"`` — list of roles for the device (empty if not found).
        - ``"routing_intent"`` — routing intent string or ``None``.
        - ``"is_primary"`` — ``True`` if this device is the primary device.
        - ``"is_source"`` — ``True`` if this device is the source device.
        - ``"session_id"`` — the session ID or ``None``.
        - ``"reasons"`` — list of diagnostic reasons from the summary.

    Never raises.
    """
    try:
        summary = get_current_mesh_participation_summary()
        found = device_id in summary.device_ids
        return {
            "device_id": device_id,
            "found": found,
            "roles": list(summary.roles_by_device.get(device_id, [])),
            "routing_intent": summary.routing_intents.get(device_id),
            "is_primary": summary.primary_device_id == device_id,
            "is_source": summary.source_device_id == device_id,
            "session_id": summary.session_id,
            "reasons": list(summary.reasons),
        }
    except Exception as exc:  # pragma: no cover – defensive
        _logger.warning("get_device_mesh_summary(%r) failed: %s", device_id, exc)
        return {
            "device_id": device_id,
            "found": False,
            "roles": [],
            "routing_intent": None,
            "is_primary": False,
            "is_source": False,
            "session_id": None,
            "reasons": [f"summary_error: {exc}"],
        }


# ---------------------------------------------------------------------------
# Pre-built empty sentinel
# ---------------------------------------------------------------------------

#: Pre-built empty summary for use when no active mesh/session/formation
#: context is present.
EMPTY_MESH_PARTICIPATION_SUMMARY = MeshParticipationSummary(
    session_id=None,
    device_ids=[],
    primary_device_id=None,
    source_device_id=None,
    roles_by_device={},
    merge_policy=None,
    barrier_posture=None,
    routing_intents={},
    reasons=["no active mesh/session/formation context"],
    sources={},
)
