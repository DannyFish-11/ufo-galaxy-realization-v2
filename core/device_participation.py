#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/device_participation.py
=============================
Canonical Participation and Orchestration Readiness Summary Layer.

Unifies device participation assessment across the existing selector, mesh,
session, and related participation structures without changing current
orchestration behaviour.

This module is **additive only** — it does not modify any existing module
and degrades gracefully when optional subsystems are unavailable.

Public API
----------
Models:
    ParticipationSummary

Helpers:
    get_device_participation(device_id) -> ParticipationSummary
    get_orchestration_ready_devices() -> list[ParticipationSummary]
    is_device_orchestration_ready(device_id) -> bool

Authority sentinel:
    DEVICE_PARTICIPATION_AUTHORITY
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceParticipation")

__all__ = [
    "ParticipationSummary",
    "get_device_participation",
    "get_orchestration_ready_devices",
    "is_device_orchestration_ready",
    "DEVICE_PARTICIPATION_AUTHORITY",
]

# Sentinel that identifies this module as the canonical authority.
DEVICE_PARTICIPATION_AUTHORITY: str = "DEVICE_PARTICIPATION_LAYER_V1"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class ParticipationSummary:
    """Aggregated participation and orchestration readiness for a single device.

    All fields beyond ``device_id`` are optional / default-False so that
    callers can build partial summaries incrementally or when subsystems are
    unavailable.
    """

    device_id: str
    assessed: bool = False
    registered: bool = False
    runtime_present: bool = False
    routable: bool = False
    orchestration_eligible: bool = False
    mesh_member: bool = False
    session_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    authority_scope: Optional[str] = None
    routing_intent: Optional[str] = None
    is_primary: bool = False
    is_source: bool = False
    is_support: bool = False
    is_relay: bool = False
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device_id": self.device_id,
            "assessed": self.assessed,
            "registered": self.registered,
            "runtime_present": self.runtime_present,
            "routable": self.routable,
            "orchestration_eligible": self.orchestration_eligible,
            "mesh_member": self.mesh_member,
            "session_id": self.session_id,
            "roles": list(self.roles),
            "authority_scope": self.authority_scope,
            "routing_intent": self.routing_intent,
            "is_primary": self.is_primary,
            "is_source": self.is_source,
            "is_support": self.is_support,
            "is_relay": self.is_relay,
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }


# ---------------------------------------------------------------------------
# Internal helpers — defensive subsystem accessors
# ---------------------------------------------------------------------------


def _get_udm() -> Any:
    """Return the UnifiedDeviceManager singleton, or None on failure."""
    try:
        from core.unified_device_manager import UnifiedDeviceManager
        return UnifiedDeviceManager.get_instance()
    except Exception as exc:
        logger.debug("_get_udm: UnifiedDeviceManager unavailable: %s", exc)
    try:
        from core.device_registry import get_device_registry
        return get_device_registry()
    except Exception as exc:
        logger.debug("_get_udm: device_registry unavailable: %s", exc)
        return None


def _get_selector_status(device_id: str) -> Optional[Any]:
    """Return a DeviceParticipationStatus from the canonical selector, or None."""
    try:
        from core.device_selection.canonical_device_selector import (
            assess_device_participation,
        )

        udm = _get_udm()
        if udm is None:
            return None

        device = None
        for fn in ("get_device", "get"):
            if hasattr(udm, fn):
                try:
                    device = getattr(udm, fn)(device_id)
                    break
                except Exception:
                    pass

        if device is None:
            # Try list_devices and filter
            list_fn = getattr(udm, "list_devices", None)
            if callable(list_fn):
                for d in list_fn() or []:
                    if str(getattr(d, "device_id", "")) == device_id:
                        device = d
                        break

        if device is None:
            return None

        return assess_device_participation(device)

    except Exception as exc:
        logger.debug("_get_selector_status(%s): %s", device_id, exc)
        return None


def _get_mesh_membership(device_id: str) -> Optional[Any]:
    """Return a MeshMembership for the device, or None."""
    try:
        from contracts.mesh_membership import MeshMembership  # noqa: F401 – existence check

        # Try body mesh registry first
        try:
            from core.mesh.body_mesh_registry import BodyMeshRegistry
            registry = BodyMeshRegistry.get_instance()
            if registry is not None:
                entry = registry.get(device_id)
                if entry is not None:
                    from contracts.mesh_membership import from_body_mesh_entry
                    return from_body_mesh_entry(entry)
        except Exception:
            pass

        # Try device formation summary
        try:
            from core.device_formation import resolve_formation_summary
            from contracts.mesh_membership import from_device_formation_summary
            summary = resolve_formation_summary()
            memberships = from_device_formation_summary(summary)
            for m in memberships or []:
                if str(getattr(m, "member_device_id", "")) == device_id:
                    return m
        except Exception:
            pass

    except Exception as exc:
        logger.debug("_get_mesh_membership(%s): %s", device_id, exc)

    return None


def _get_mesh_session(device_id: str) -> Optional[Any]:
    """Return the active MeshSession that the device participates in, or None."""
    try:
        # Try mesh session coordinator
        try:
            from contracts.mesh_session_coordinator import get_active_session_for_device
            return get_active_session_for_device(device_id)
        except Exception:
            pass

        try:
            from core.runtime.source_dispatch_orchestrator import (
                get_active_mesh_session,
            )
            session = get_active_mesh_session()
            if session is not None:
                participants = getattr(session, "participants", []) or []
                for p in participants:
                    if str(getattr(p, "device_id", "")) == device_id:
                        return session
        except Exception:
            pass

    except Exception as exc:
        logger.debug("_get_mesh_session(%s): %s", device_id, exc)

    return None


def _roles_from_membership(membership: Any) -> List[str]:
    """Extract role strings from a MeshMembership object."""
    roles_raw = getattr(membership, "roles", []) or []
    result: List[str] = []
    for r in roles_raw:
        if hasattr(r, "value"):
            result.append(str(r.value))
        else:
            result.append(str(r))
    return result


def _roles_from_session_participant(session: Any, device_id: str) -> List[str]:
    """Extract role strings for a device from a MeshSession."""
    participants = getattr(session, "participants", []) or []
    for p in participants:
        if str(getattr(p, "device_id", "")) == device_id:
            roles_raw = getattr(p, "roles", []) or []
            return [str(r) for r in roles_raw]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_device_participation(device_id: str) -> ParticipationSummary:
    """Return a :class:`ParticipationSummary` for *device_id*.

    Aggregates from:
    1. ``core.device_selection.canonical_device_selector`` for registered /
       runtime_present / routable / orchestration_eligible flags.
    2. ``contracts.mesh_membership`` / body mesh registry for mesh membership
       and role information.
    3. ``contracts.mesh_session`` / session coordinator for active session
       context.

    All source lookups are wrapped in try/except blocks.  If a subsystem is
    unavailable the corresponding fields remain at their defaults and a reason
    string is appended to ``summary.reasons``.  The summary is *never* None
    and never raises.

    Parameters
    ----------
    device_id:
        The canonical device identifier.

    Returns
    -------
    ParticipationSummary
        Always a valid :class:`ParticipationSummary`.  ``assessed=True``
        when the canonical selector was consulted; ``assessed=False``
        otherwise.
    """
    if not device_id:
        return ParticipationSummary(
            device_id=device_id or "",
            assessed=False,
            reasons=["empty-device-id"],
        )

    summary = ParticipationSummary(device_id=device_id)
    sources: Dict[str, Any] = {}
    reasons: List[str] = []

    # ------------------------------------------------------------------
    # 1. Canonical selector participation
    # ------------------------------------------------------------------
    try:
        sel_status = _get_selector_status(device_id)
        if sel_status is not None:
            summary.assessed = True
            summary.registered = bool(getattr(sel_status, "registered", False))
            summary.runtime_present = bool(getattr(sel_status, "runtime_present", False))
            summary.routable = bool(getattr(sel_status, "routable", False))
            summary.orchestration_eligible = bool(
                getattr(sel_status, "orchestration_eligible", False)
            )
            sources["selector"] = (
                sel_status.to_dict()
                if hasattr(sel_status, "to_dict")
                else {"status": str(sel_status)}
            )
        else:
            reasons.append("selector-unavailable")
    except Exception as exc:
        logger.warning("get_device_participation: selector error for %s: %s", device_id, exc)
        reasons.append(f"selector-error: {exc}")

    # ------------------------------------------------------------------
    # 2. Mesh membership
    # ------------------------------------------------------------------
    try:
        membership = _get_mesh_membership(device_id)
        if membership is not None:
            summary.mesh_member = True
            roles = _roles_from_membership(membership)
            # Merge roles without duplicates
            for r in roles:
                if r not in summary.roles:
                    summary.roles.append(r)

            if summary.authority_scope is None:
                scope_raw = getattr(membership, "authority_scope", None)
                if scope_raw is not None:
                    summary.authority_scope = (
                        scope_raw.value if hasattr(scope_raw, "value") else str(scope_raw)
                    )

            if summary.routing_intent is None:
                intent_raw = getattr(membership, "routing_intent", None)
                if intent_raw is not None:
                    summary.routing_intent = (
                        intent_raw.value if hasattr(intent_raw, "value") else str(intent_raw)
                    )

            # Derive boolean flags from role strings
            role_set = {r.lower() for r in summary.roles}
            summary.is_primary = summary.is_primary or "primary" in role_set
            summary.is_source = summary.is_source or "source" in role_set
            summary.is_support = summary.is_support or "support" in role_set
            summary.is_relay = summary.is_relay or "relay" in role_set

            sources["mesh_membership"] = (
                membership.to_dict()
                if hasattr(membership, "to_dict")
                else {"member_device_id": device_id}
            )
        else:
            reasons.append("mesh-membership-unavailable")
    except Exception as exc:
        logger.warning("get_device_participation: mesh error for %s: %s", device_id, exc)
        reasons.append(f"mesh-error: {exc}")

    # ------------------------------------------------------------------
    # 3. Mesh session
    # ------------------------------------------------------------------
    try:
        session = _get_mesh_session(device_id)
        if session is not None:
            session_id = str(getattr(session, "session_id", "") or "")
            if session_id:
                summary.session_id = session_id

            session_roles = _roles_from_session_participant(session, device_id)
            for r in session_roles:
                if r not in summary.roles:
                    summary.roles.append(r)

            # Derive primary / source flags from session fields
            primary_id = str(getattr(session, "primary_device_id", "") or "")
            source_id = str(getattr(session, "source_device_id", "") or "")
            if primary_id == device_id:
                summary.is_primary = True
            if source_id == device_id:
                summary.is_source = True

            role_set = {r.lower() for r in summary.roles}
            summary.is_support = summary.is_support or "support" in role_set
            summary.is_relay = summary.is_relay or "relay" in role_set

            sources["mesh_session"] = {
                "session_id": session_id,
                "roles": session_roles,
            }
        else:
            reasons.append("mesh-session-unavailable")
    except Exception as exc:
        logger.warning("get_device_participation: session error for %s: %s", device_id, exc)
        reasons.append(f"session-error: {exc}")

    summary.reasons = reasons
    summary.sources = sources
    return summary


def get_orchestration_ready_devices() -> List[ParticipationSummary]:
    """Return participation summaries for all orchestration-ready devices.

    A device is considered orchestration-ready when its
    :class:`ParticipationSummary` has ``orchestration_eligible == True``.

    This function queries all devices from the UDM / device registry and
    evaluates each via :func:`get_device_participation`.  Per-device errors
    are caught and logged; they do not abort the overall scan.

    Returns
    -------
    list[ParticipationSummary]
        Summaries whose ``orchestration_eligible`` is ``True``.  Empty list
        on error or when no device qualifies.  Never raises.
    """
    try:
        udm = _get_udm()
        if udm is None:
            logger.debug("get_orchestration_ready_devices: UDM unavailable")
            return []

        list_fn = getattr(udm, "list_devices", None)
        if not callable(list_fn):
            logger.debug("get_orchestration_ready_devices: UDM has no list_devices()")
            return []

        devices = list_fn() or []
        ready: List[ParticipationSummary] = []
        for device in devices:
            device_id = str(getattr(device, "device_id", "") or "")
            if not device_id:
                continue
            try:
                ps = get_device_participation(device_id)
                if ps.orchestration_eligible:
                    ready.append(ps)
            except Exception as exc:
                logger.warning(
                    "get_orchestration_ready_devices: error for %s: %s", device_id, exc
                )
        return ready

    except Exception as exc:
        logger.warning("get_orchestration_ready_devices: error: %s", exc)
        return []


def is_device_orchestration_ready(device_id: str) -> bool:
    """Return ``True`` if *device_id* is orchestration-eligible.

    Thin wrapper around :func:`get_device_participation`.  Catches all
    exceptions and returns ``False`` on failure.

    Parameters
    ----------
    device_id:
        The canonical device identifier.

    Returns
    -------
    bool
        ``True`` when the device is orchestration-eligible; ``False``
        otherwise (including on error).
    """
    try:
        ps = get_device_participation(device_id)
        return ps.orchestration_eligible
    except Exception as exc:
        logger.warning("is_device_orchestration_ready(%s): %s", device_id, exc)
        return False
