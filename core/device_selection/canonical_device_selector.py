#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_selection.canonical_device_selector
=================================================

PR-6 — Canonical Device Selection Helper.

Centralises device selection input for cross-device coordination and
multi-device orchestration.  All cross-device / orchestration device
selection consumes canonical projected device views
(``RegisteredRuntimeDevice``) as its base input, with router/runtime
state used only for routing-feasibility enrichment.

Participation Semantics
------------------------
Five participation properties are explicitly derived from canonical state
plus optional runtime enrichment:

registered
    The device is in the canonical registry.  A ``RegisteredRuntimeDevice``
    exists for this device (always ``True`` when one is passed in).

runtime_present
    The device is operationally present — its canonical status is ONLINE or
    BUSY.  Derived from ``RegisteredRuntimeDevice.online`` /
    ``RegisteredRuntimeDevice.status``.

routable
    A live transport connection exists, making the device reachable for
    dispatch.  Derived from the canonical connection state plus an optional
    ``router_liveness`` override supplied by the caller.

cross_device_eligible
    The device can participate in cross-device coordination.  True when
    ``registered``, ``runtime_present``, and ``routable`` are all True.

orchestration_eligible
    The device can be included in multi-device orchestration swarms.  True
    when ``cross_device_eligible`` is True and the device's autonomy hints
    indicate ``runtime_enabled`` or the caller passes an explicit override.

Architecture
------------
- ``RegisteredRuntimeDevice`` (from ``contracts.registered_runtime_device``)
  is the **base input contract**.  Its identity fields are canonical truth.
- Router/runtime liveness is accepted as *enrichment* (a ``dict`` of
  ``device_id → bool``), never as a replacement for canonical identity.
- Output is a ``CanonicalDeviceSelectionEntry`` pairing the canonical
  contract with the derived participation status.
- ``device_score_input_from_canonical`` bridges the canonical contract to
  the scoring engine (``DeviceScoreInput``) for use by
  ``SwarmCoordinator``.

Usage::

    from contracts.registered_runtime_device import RegisteredRuntimeDevice
    from core.device_selection import (
        assess_device_participation,
        select_cross_device_candidates,
        device_score_input_from_canonical,
    )

    devices: list[RegisteredRuntimeDevice] = ...

    # Assess a single device
    status = assess_device_participation(device)

    # Select eligible cross-device candidates, enriched with live routing info
    entries = select_cross_device_candidates(
        devices,
        router_liveness={"dev_01": True, "dev_02": False},
    )

    # Convert to scoring inputs for SwarmCoordinator
    score_inputs = [device_score_input_from_canonical(e) for e in entries]
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceSelection.CanonicalSelector")

__all__ = [
    "DeviceParticipationStatus",
    "CanonicalDeviceSelectionEntry",
    "assess_device_participation",
    "select_cross_device_candidates",
    "select_orchestration_candidates",
    "device_score_input_from_canonical",
]


# ---------------------------------------------------------------------------
# Participation status
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DeviceParticipationStatus:
    """Derived participation eligibility for a single canonical device.

    All five flags are derived from the canonical ``RegisteredRuntimeDevice``
    contract combined with optional runtime enrichment.  They must not be
    computed from router-local state alone.

    Attributes
    ----------
    registered:
        True when a canonical ``RegisteredRuntimeDevice`` exists for the
        device.  Always ``True`` when constructed by :func:`assess_device_participation`.
    runtime_present:
        True when the device is operationally present (status ONLINE or BUSY).
    routable:
        True when a live transport connection exists for dispatch.  Derives
        from the canonical connection state; may be overridden by a
        router-liveness signal passed as enrichment.
    cross_device_eligible:
        True when ``registered``, ``runtime_present``, and ``routable``
        are all ``True``.
    orchestration_eligible:
        True when ``cross_device_eligible`` is ``True`` and the device
        signals runtime-enabled capability.
    participation_reason:
        Human-readable explanation of the status derivation.
    """

    registered: bool = True
    runtime_present: bool = False
    routable: bool = False
    cross_device_eligible: bool = False
    orchestration_eligible: bool = False
    participation_reason: str = "not assessed"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Selection entry
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CanonicalDeviceSelectionEntry:
    """Pairs a canonical device view with its derived participation status.

    This is the standard input unit for cross-device and orchestration
    selection.  Callers must use ``device.device_id`` for identity — never
    raw router objects — to avoid semantic fragmentation.

    Attributes
    ----------
    device:
        The canonical ``RegisteredRuntimeDevice`` projection (identity truth).
    participation:
        The derived ``DeviceParticipationStatus`` for this device.
    """

    device: Any  # RegisteredRuntimeDevice — typed as Any to avoid circular import
    participation: DeviceParticipationStatus

    @property
    def device_id(self) -> str:
        """Convenience accessor for ``device.device_id``."""
        return str(getattr(self.device, "device_id", ""))

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device": (
                self.device.to_dict()
                if hasattr(self.device, "to_dict")
                else {"device_id": self.device_id}
            ),
            "participation": self.participation.to_dict(),
        }


# ---------------------------------------------------------------------------
# Participation assessment
# ---------------------------------------------------------------------------


def assess_device_participation(
    device: Any,
    router_liveness: Optional[Dict[str, bool]] = None,
    orchestration_override: Optional[bool] = None,
) -> DeviceParticipationStatus:
    """Derive participation status from a canonical ``RegisteredRuntimeDevice``.

    Parameters
    ----------
    device:
        A ``RegisteredRuntimeDevice`` instance (or any object that exposes
        the same field surface).  This is the **canonical truth source** for
        identity and registration state.
    router_liveness:
        Optional mapping of ``device_id → bool`` from the router or session
        layer.  Used to *enrich* the ``routable`` flag (live connection
        detected).  This is enrichment only — it never overrides identity or
        canonical registration truth.
    orchestration_override:
        If ``True`` or ``False``, override the ``orchestration_eligible``
        derivation.  Useful for callers that have policy-level knowledge
        (e.g. capability requirements) that should take precedence over
        the default autonomy-hint derivation.

    Returns
    -------
    DeviceParticipationStatus
        Derived participation flags with a human-readable ``participation_reason``.
    """
    try:
        device_id = str(getattr(device, "device_id", "") or "")

        # --- registered ---
        # True whenever a canonical view exists (i.e. we have a RegisteredRuntimeDevice).
        registered = bool(device_id)

        # --- runtime_present ---
        # Derived from canonical status / online flag.
        online_flag = bool(getattr(device, "online", False))
        status_val = str(getattr(device, "status", "offline")).lower()
        runtime_present = online_flag or status_val in ("online", "busy")

        # --- routable ---
        # Primary source: canonical connection state.
        connection = getattr(device, "connection", None)
        conn_state_val = ""
        if connection is not None:
            conn_state_val = str(
                getattr(connection, "state", "disconnected")
            ).lower()
        canonical_routable = conn_state_val in ("connected", "reconnecting")

        # Enrich with router liveness signal (additive enrichment only).
        router_live: Optional[bool] = None
        if router_liveness is not None and device_id:
            router_live = router_liveness.get(device_id)

        if router_live is not None:
            # Router liveness can affirm or deny routability, but does not
            # override canonical identity.
            routable = router_live
        else:
            routable = canonical_routable

        # --- cross_device_eligible ---
        cross_device_eligible = registered and runtime_present and routable

        # --- orchestration_eligible ---
        if orchestration_override is not None:
            orchestration_eligible = cross_device_eligible and orchestration_override
        else:
            autonomy = getattr(device, "autonomy", None)
            runtime_enabled = bool(
                getattr(autonomy, "runtime_enabled", False) if autonomy is not None else False
            )
            # A device is orchestration-eligible when it is cross-device-eligible
            # OR runtime-enabled (runtime_enabled indicates the device can run
            # the Galaxy runtime client autonomously, which is sufficient for
            # orchestration participation even without an active session).
            orchestration_eligible = cross_device_eligible and (runtime_enabled or runtime_present)

        # Build reason string
        reason_parts: List[str] = []
        if not registered:
            reason_parts.append("not-registered")
        if not runtime_present:
            reason_parts.append("not-runtime-present")
        if not routable:
            src = "router-liveness" if router_live is not None else "canonical-connection"
            reason_parts.append(f"not-routable({src})")
        if not reason_parts:
            reason_parts.append("all-eligible")

        return DeviceParticipationStatus(
            registered=registered,
            runtime_present=runtime_present,
            routable=routable,
            cross_device_eligible=cross_device_eligible,
            orchestration_eligible=orchestration_eligible,
            participation_reason="; ".join(reason_parts),
        )

    except Exception as exc:
        logger.warning(
            "assess_device_participation: error for device %s: %s",
            getattr(device, "device_id", "?"),
            exc,
        )
        return DeviceParticipationStatus(
            registered=False,
            runtime_present=False,
            routable=False,
            cross_device_eligible=False,
            orchestration_eligible=False,
            participation_reason=f"assessment-error: {exc}",
        )


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------


def select_cross_device_candidates(
    devices: List[Any],
    router_liveness: Optional[Dict[str, bool]] = None,
) -> List[CanonicalDeviceSelectionEntry]:
    """Select devices eligible for cross-device coordination.

    Filters a list of canonical ``RegisteredRuntimeDevice`` projections and
    returns only those whose derived :class:`DeviceParticipationStatus` has
    ``cross_device_eligible == True``.

    Parameters
    ----------
    devices:
        List of ``RegisteredRuntimeDevice`` instances.  These are the
        canonical truth source; no parallel device tables should be used.
    router_liveness:
        Optional ``device_id → bool`` mapping for routing-feasibility
        enrichment.  Router state may *enrich* the ``routable`` flag but
        must not replace canonical identity or registration truth.

    Returns
    -------
    list[CanonicalDeviceSelectionEntry]
        Entries whose ``participation.cross_device_eligible`` is ``True``.
        Returns an empty list on error (never raises).
    """
    try:
        entries: List[CanonicalDeviceSelectionEntry] = []
        for device in devices or []:
            status = assess_device_participation(device, router_liveness=router_liveness)
            if status.cross_device_eligible:
                entries.append(CanonicalDeviceSelectionEntry(device=device, participation=status))
        return entries
    except Exception as exc:
        logger.warning("select_cross_device_candidates: error: %s", exc)
        return []


def select_orchestration_candidates(
    devices: List[Any],
    router_liveness: Optional[Dict[str, bool]] = None,
    required_capabilities: Optional[List[str]] = None,
) -> List[CanonicalDeviceSelectionEntry]:
    """Select devices eligible for multi-device orchestration.

    A stricter filter than :func:`select_cross_device_candidates`: returns
    only devices with ``orchestration_eligible == True``.  An optional
    capability filter narrows the results further.

    Parameters
    ----------
    devices:
        List of ``RegisteredRuntimeDevice`` canonical projections.
    router_liveness:
        Optional routing-feasibility enrichment (``device_id → bool``).
    required_capabilities:
        Optional list of capability strings.  A device is included only
        if it declares all required capabilities.  When ``None`` or empty,
        capability filtering is skipped.

    Returns
    -------
    list[CanonicalDeviceSelectionEntry]
        Entries whose ``participation.orchestration_eligible`` is ``True``
        and that satisfy any capability filter.  Never raises.
    """
    try:
        entries: List[CanonicalDeviceSelectionEntry] = []
        for device in devices or []:
            status = assess_device_participation(device, router_liveness=router_liveness)
            if not status.orchestration_eligible:
                continue

            # Capability filter (additive; only when required_capabilities given)
            if required_capabilities:
                cap_profile = getattr(device, "capabilities", None)
                device_caps: List[str] = (
                    list(getattr(cap_profile, "capabilities", []))
                    if cap_profile is not None
                    else []
                )
                if not all(c in device_caps for c in required_capabilities):
                    continue

            entries.append(CanonicalDeviceSelectionEntry(device=device, participation=status))
        return entries
    except Exception as exc:
        logger.warning("select_orchestration_candidates: error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Scoring bridge
# ---------------------------------------------------------------------------


def device_score_input_from_canonical(
    entry: CanonicalDeviceSelectionEntry,
    ping_latency_ms: float = 0.0,
    load_pct: float = 0.0,
    sandbox_level: Optional[int] = None,
) -> Any:
    """Convert a :class:`CanonicalDeviceSelectionEntry` to a ``DeviceScoreInput``.

    Bridges the canonical device contract to the scoring engine used by
    :class:`~core.swarm_coordinator.SwarmCoordinator`.  Identity is always
    sourced from the canonical device; latency/load/sandbox values are
    runtime signals that may be supplied by the caller.

    Parameters
    ----------
    entry:
        A :class:`CanonicalDeviceSelectionEntry` — canonical device + participation.
    ping_latency_ms:
        Optional observed ping latency for scoring (default ``0.0``).
    load_pct:
        Optional load percentage for scoring (default ``0.0``).
    sandbox_level:
        Optional :class:`~core.control_plane.smart_scheduler.SandboxLevel`
        integer value.  When ``None``, ``SandboxLevel.STANDARD`` (2) is used.

    Returns
    -------
    core.control_plane.smart_scheduler.DeviceScoreInput
        Ready for use with :class:`DeviceScoringEngine`.  Returns ``None``
        on import error (never raises).
    """
    try:
        from core.control_plane.smart_scheduler import DeviceScoreInput, SandboxLevel

        device = entry.device
        cap_profile = getattr(device, "capabilities", None)
        caps: List[str] = (
            list(getattr(cap_profile, "capabilities", []))
            if cap_profile is not None
            else []
        )

        level = SandboxLevel(sandbox_level) if sandbox_level is not None else SandboxLevel.STANDARD

        return DeviceScoreInput(
            device_id=entry.device_id,
            ping_latency_ms=ping_latency_ms,
            load_pct=load_pct,
            sandbox_level=level,
            capabilities=caps,
        )
    except Exception as exc:
        logger.warning(
            "device_score_input_from_canonical: error for %s: %s",
            entry.device_id,
            exc,
        )
        return None
