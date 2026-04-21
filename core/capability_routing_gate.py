#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_routing_gate
=============================

PR-3 — Formation & Routing Hardening: Capability-Aware Routing Gate.

Background
----------
The existing ``galaxy_gateway/routing/device_selection.py`` uses
``required_capabilities`` from the routing analysis dict as a hint passed
to ``DevicePoolManager.select_device()``.  When the pool is unavailable the
check is skipped silently, and when no capability-filtered device is found
the code falls back to "all" rather than "none" — making capability
requirements advisory rather than enforced.

This module introduces a **hard capability routing gate** that is separate
from ``DeviceRouter`` policy logic and can be consumed by any routing or
formation layer.  It does not replace or modify ``DevicePoolManager`` or
the existing selection path; it is an additive constraint layer.

Design principles
-----------------
- **Additive only** — does not modify ``device_selection.py``,
  ``DevicePoolManager``, or any other existing module.
- **Stateless** — all gate functions are pure functions; they produce
  ``CapabilityGateResult`` objects without side effects.
- **Graceful degradation** — when capability information cannot be
  determined, the gate outcome is ``INSUFFICIENT_DATA`` rather than an
  exception.  Callers decide whether to accept or reject on incomplete data.
- **Layered authority** — the gate is the canonical place to evaluate
  *required* capabilities.  Advisory/optional capabilities should remain
  in the ``DevicePoolManager`` selection layer.

Sentinels
---------
:data:`CAPABILITY_ROUTING_GATE_IS_AUTHORITY`
    Identifies this module as the canonical hard-capability routing gate.
:data:`CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY`
    Affirms that this gate elevates ``required_capabilities`` from advisory
    to enforced where a hard gate is warranted.
:data:`CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY`
    Affirms that this gate is additive and does not replace or patch
    ``DevicePoolManager`` or ``device_selection.select_devices``.

Public API
----------
Enumerations:
    :class:`CapabilityGateVerdict`

Data classes:
    :class:`CapabilityGateResult`

Functions:
    :func:`evaluate_capability_gate`
    :func:`filter_by_required_capabilities`
    :func:`device_meets_capabilities`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    # Sentinels
    "CAPABILITY_ROUTING_GATE_IS_AUTHORITY",
    "CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY",
    "CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY",
    # Enumerations
    "CapabilityGateVerdict",
    # Data classes
    "CapabilityGateResult",
    # Functions
    "evaluate_capability_gate",
    "filter_by_required_capabilities",
    "device_meets_capabilities",
]

logger = logging.getLogger("Galaxy.CapabilityRoutingGate")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

CAPABILITY_ROUTING_GATE_IS_AUTHORITY: str = (
    "CAPABILITY_ROUTING_GATE_IS_AUTHORITY: "
    "core/capability_routing_gate.py is the canonical hard-capability "
    "routing gate layer.  It elevates required_capabilities from advisory "
    "to enforced constraints where a hard gate is warranted."
)

CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY: str = (
    "CAPABILITY_GATE_POLICY: This gate promotes required_capabilities from "
    "advisory metadata (passed as a hint to DevicePoolManager) to a "
    "hard routing constraint evaluated before dispatch.  Devices that do "
    "not satisfy all declared required capabilities are excluded from "
    "selection when this gate is active.  Resolves PR-3 routing-hardening "
    "requirement: 'elevate capability requirements from advisory metadata "
    "to meaningful routing constraints.'"
)

CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY: str = (
    "CAPABILITY_GATE_POLICY: This module is additive.  It does not modify "
    "DevicePoolManager, device_selection.select_devices, DeviceRouter, or "
    "any other existing routing module.  Policy decisions not related to "
    "capability hard-gating remain in their canonical layers."
)


# ---------------------------------------------------------------------------
# CapabilityGateVerdict
# ---------------------------------------------------------------------------


class CapabilityGateVerdict(str, Enum):
    """Outcome of a capability gate evaluation."""

    PASS = "pass"
    """Device satisfies all required capabilities."""

    FAIL = "fail"
    """Device is missing one or more required capabilities."""

    INSUFFICIENT_DATA = "insufficient_data"
    """Capability information was unavailable; verdict is indeterminate."""

    NOT_REQUIRED = "not_required"
    """No capability requirements were declared; gate is not active."""


# ---------------------------------------------------------------------------
# CapabilityGateResult
# ---------------------------------------------------------------------------


@dataclass
class CapabilityGateResult:
    """Result of a capability gate evaluation for a single device.

    Attributes
    ----------
    device_id:
        The device this result applies to.
    verdict:
        Overall :class:`CapabilityGateVerdict`.
    required_capabilities:
        The full list of capabilities that were required.
    matched_capabilities:
        Required capabilities that the device was confirmed to hold.
    missing_capabilities:
        Required capabilities that the device could not satisfy.
    reason:
        Human-readable explanation for the verdict.
    """

    device_id: str
    verdict: CapabilityGateVerdict = CapabilityGateVerdict.NOT_REQUIRED
    required_capabilities: List[str] = field(default_factory=list)
    matched_capabilities: List[str] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        """Return True when the device passed the gate or no gate was active."""
        return self.verdict in (
            CapabilityGateVerdict.PASS,
            CapabilityGateVerdict.NOT_REQUIRED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "verdict": self.verdict.value,
            "required_capabilities": list(self.required_capabilities),
            "matched_capabilities": list(self.matched_capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "reason": self.reason,
            "passed": self.passed,
        }


# ---------------------------------------------------------------------------
# Core gate functions
# ---------------------------------------------------------------------------


def device_meets_capabilities(
    device_id: str,
    device_capabilities: Sequence[str],
    required_capabilities: Sequence[str],
) -> CapabilityGateResult:
    """Evaluate whether *device_id* satisfies *required_capabilities*.

    This is a pure function — it accepts the device's capability list
    directly rather than querying any registry.  The caller is responsible
    for obtaining the capability list from the appropriate source
    (e.g. ``GatewayCapabilityRegistry``, device metadata, or a
    ``FormationMember.capabilities`` field).

    Parameters
    ----------
    device_id:
        Identifier of the device being evaluated.
    device_capabilities:
        Capabilities the device is known to hold (strings).
    required_capabilities:
        Capabilities the routing context requires.

    Returns
    -------
    CapabilityGateResult
        A result with ``verdict == PASS`` when all requirements are met,
        ``FAIL`` when one or more are missing, or ``NOT_REQUIRED`` when
        the requirements list is empty.
    """
    required = list(required_capabilities)

    if not required:
        return CapabilityGateResult(
            device_id=device_id,
            verdict=CapabilityGateVerdict.NOT_REQUIRED,
            reason="no capability requirements declared",
        )

    device_caps_set = set(device_capabilities)
    matched = [c for c in required if c in device_caps_set]
    missing = [c for c in required if c not in device_caps_set]

    if missing:
        return CapabilityGateResult(
            device_id=device_id,
            verdict=CapabilityGateVerdict.FAIL,
            required_capabilities=required,
            matched_capabilities=matched,
            missing_capabilities=missing,
            reason=(
                f"device {device_id!r} is missing required capabilities: "
                f"{missing!r}"
            ),
        )

    return CapabilityGateResult(
        device_id=device_id,
        verdict=CapabilityGateVerdict.PASS,
        required_capabilities=required,
        matched_capabilities=matched,
        missing_capabilities=[],
        reason=(
            f"device {device_id!r} satisfies all required capabilities: "
            f"{required!r}"
        ),
    )


def evaluate_capability_gate(
    device: Any,
    required_capabilities: Sequence[str],
    *,
    capability_attr: str = "capabilities",
    device_id_attr: str = "device_id",
) -> CapabilityGateResult:
    """Evaluate the capability gate for *device* against *required_capabilities*.

    This function reads the device's capability list from the attribute named
    by *capability_attr* (default: ``"capabilities"``).  When the attribute
    is absent or not iterable the verdict is ``INSUFFICIENT_DATA``.

    Parameters
    ----------
    device:
        Any object representing a device.  Should expose *device_id_attr*
        and *capability_attr* attributes.
    required_capabilities:
        Capabilities the routing context requires.
    capability_attr:
        Name of the attribute on *device* that holds the capability list.
        Defaults to ``"capabilities"``.
    device_id_attr:
        Name of the attribute on *device* that holds the device identifier.
        Defaults to ``"device_id"``.

    Returns
    -------
    CapabilityGateResult
    """
    device_id: str = str(getattr(device, device_id_attr, "<unknown>"))
    required = list(required_capabilities)

    if not required:
        return CapabilityGateResult(
            device_id=device_id,
            verdict=CapabilityGateVerdict.NOT_REQUIRED,
            reason="no capability requirements declared",
        )

    try:
        raw_caps = getattr(device, capability_attr, None)
        if raw_caps is None:
            raise AttributeError(f"attribute {capability_attr!r} is None")
        device_caps: List[str] = list(raw_caps)
    except Exception as exc:
        logger.debug(
            "evaluate_capability_gate: cannot read capabilities for %s: %s",
            device_id,
            exc,
        )
        return CapabilityGateResult(
            device_id=device_id,
            verdict=CapabilityGateVerdict.INSUFFICIENT_DATA,
            required_capabilities=required,
            reason=(
                f"capability information unavailable for device {device_id!r}: "
                f"{exc}"
            ),
        )

    return device_meets_capabilities(
        device_id=device_id,
        device_capabilities=device_caps,
        required_capabilities=required,
    )


def filter_by_required_capabilities(
    devices: Sequence[Any],
    required_capabilities: Sequence[str],
    *,
    capability_attr: str = "capabilities",
    device_id_attr: str = "device_id",
    allow_insufficient_data: bool = True,
) -> List[Any]:
    """Filter *devices* to only those that satisfy *required_capabilities*.

    This is the primary entry point for **hard** capability-aware routing.
    Unlike the advisory path in ``device_selection.select_devices`` (which
    falls back to all devices when no match is found), this function returns
    an empty list when no device meets the requirements.

    Parameters
    ----------
    devices:
        List of device objects to filter.
    required_capabilities:
        Capabilities the routing context requires.
    capability_attr:
        Device attribute name for capability list.
    device_id_attr:
        Device attribute name for device identifier.
    allow_insufficient_data:
        When ``True`` (default), devices with
        :attr:`CapabilityGateVerdict.INSUFFICIENT_DATA` are **kept** in the
        result (conservative — prefer dispatch over silent exclusion when
        capability data is missing).  When ``False``, they are excluded.

    Returns
    -------
    List[Any]
        Filtered list.  Empty when no device satisfies all requirements.
        When *required_capabilities* is empty, the original list is returned
        unchanged (gate is not active).
    """
    required = list(required_capabilities)

    if not required:
        # Gate is not active — pass all devices through unchanged.
        return list(devices)

    accepted: List[Any] = []
    rejected_count = 0

    for device in devices:
        result = evaluate_capability_gate(
            device=device,
            required_capabilities=required,
            capability_attr=capability_attr,
            device_id_attr=device_id_attr,
        )

        if result.passed:
            accepted.append(device)
        elif result.verdict == CapabilityGateVerdict.INSUFFICIENT_DATA:
            if allow_insufficient_data:
                accepted.append(device)
                logger.debug(
                    "filter_by_required_capabilities: keeping device %s "
                    "(insufficient data, allow_insufficient_data=True)",
                    result.device_id,
                )
            else:
                rejected_count += 1
                logger.debug(
                    "filter_by_required_capabilities: excluding device %s "
                    "(insufficient data, allow_insufficient_data=False)",
                    result.device_id,
                )
        else:
            # FAIL verdict — hard exclude
            rejected_count += 1
            logger.debug(
                "filter_by_required_capabilities: excluding device %s "
                "— missing: %s",
                result.device_id,
                result.missing_capabilities,
            )

    if not accepted and rejected_count > 0:
        logger.warning(
            "filter_by_required_capabilities: no devices satisfy "
            "required_capabilities=%r; %d device(s) excluded",
            required,
            rejected_count,
        )

    return accepted
