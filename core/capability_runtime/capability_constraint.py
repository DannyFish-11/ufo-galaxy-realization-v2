#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_runtime.capability_constraint
===============================================

PR-20 (V4) — Capability Runtime State

Defines :class:`CapabilityConstraintFlags` — a compact, serialisable set of
boolean flags that describe **usage constraints** for a capability at runtime.

These flags are consumed by routing and dispatch logic to make safe decisions:

* ``requires_confirmation`` — the capability must not be invoked without
  human-in-the-loop (HITL) confirmation.
* ``cross_device_restricted`` — the capability may not be dispatched to a
  remote/cross-device executor.
* ``latency_sensitive`` — the capability has strict timing requirements;
  routing should prefer low-latency paths.
* ``device_exclusive`` — only one device may hold this capability active at
  a time (mutual exclusion).
* ``requires_elevated_privilege`` — the capability requires elevated
  permissions before invocation.

Design notes
------------
* All flags default to ``False`` so an "empty" flags set is safe.
* Serialisation round-trips cleanly through ``to_dict`` / ``from_dict``.
* The frozen dataclass prevents accidental mutation after construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


# ---------------------------------------------------------------------------
# CapabilityConstraintFlags
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityConstraintFlags:
    """Immutable constraint flags for a single capability.

    Attributes
    ----------
    requires_confirmation : bool
        Capability must be confirmed by a human operator before dispatch.
    cross_device_restricted : bool
        Capability may not be dispatched cross-device (local only).
    latency_sensitive : bool
        Routing should prefer low-latency execution paths.
    device_exclusive : bool
        Only one device may hold this capability active simultaneously.
    requires_elevated_privilege : bool
        Invocation requires elevated permission grants.
    """

    requires_confirmation: bool = False
    cross_device_restricted: bool = False
    latency_sensitive: bool = False
    device_exclusive: bool = False
    requires_elevated_privilege: bool = False

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "requires_confirmation": self.requires_confirmation,
            "cross_device_restricted": self.cross_device_restricted,
            "latency_sensitive": self.latency_sensitive,
            "device_exclusive": self.device_exclusive,
            "requires_elevated_privilege": self.requires_elevated_privilege,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityConstraintFlags":
        """Deserialise from a plain dict; unknown keys are ignored."""
        return cls(
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            cross_device_restricted=bool(data.get("cross_device_restricted", False)),
            latency_sensitive=bool(data.get("latency_sensitive", False)),
            device_exclusive=bool(data.get("device_exclusive", False)),
            requires_elevated_privilege=bool(
                data.get("requires_elevated_privilege", False)
            ),
        )

    def has_any_constraint(self) -> bool:
        """Return ``True`` if at least one flag is set."""
        return any(
            [
                self.requires_confirmation,
                self.cross_device_restricted,
                self.latency_sensitive,
                self.device_exclusive,
                self.requires_elevated_privilege,
            ]
        )

    def active_constraints(self) -> list:
        """Return a list of flag names that are currently ``True``."""
        result = []
        if self.requires_confirmation:
            result.append("requires_confirmation")
        if self.cross_device_restricted:
            result.append("cross_device_restricted")
        if self.latency_sensitive:
            result.append("latency_sensitive")
        if self.device_exclusive:
            result.append("device_exclusive")
        if self.requires_elevated_privilege:
            result.append("requires_elevated_privilege")
        return result


# ---------------------------------------------------------------------------
# Pre-built sentinels
# ---------------------------------------------------------------------------

NO_CONSTRAINTS = CapabilityConstraintFlags()
"""Sentinel: no constraint flags set — safe for unrestricted dispatch."""

CONFIRMATION_REQUIRED = CapabilityConstraintFlags(requires_confirmation=True)
"""Sentinel: requires human-in-the-loop confirmation."""

LOCAL_ONLY = CapabilityConstraintFlags(cross_device_restricted=True)
"""Sentinel: must not leave the local device."""

LATENCY_CRITICAL = CapabilityConstraintFlags(latency_sensitive=True)
"""Sentinel: route via low-latency path only."""

EXCLUSIVE_LOCAL = CapabilityConstraintFlags(
    cross_device_restricted=True, device_exclusive=True
)
"""Sentinel: local-only, mutually exclusive."""
