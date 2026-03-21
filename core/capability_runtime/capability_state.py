#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_runtime.capability_state
==========================================

PR-20 (V4) — Capability Runtime State

Defines the core availability posture enum and the serialisable
:class:`CapabilityRuntimeState` dataclass.

A :class:`CapabilityRuntimeState` represents the **live, runtime truth** of a
single named capability:

* **availability** — is it currently accessible, degraded, or down?
* **device_bindings** — which device ids currently provide this capability?
* **preferred_device_ids** — routing hint: prefer these devices first.
* **constraint_flags** — CapabilityConstraintFlags (see capability_constraint.py).
* **reliability_flags** — free-form dict of health/reliability signal keys.
* **last_updated** — Unix timestamp of last state write (for staleness checks).
* **metadata** — arbitrary extension metadata.

Design notes
------------
* The dataclass is **frozen=False** so routing helpers can update individual
  fields; callers must go through :class:`CapabilityRuntimeRegistry` to
  ensure thread-safe writes.
* Serialisation is fully JSON-compatible (all field types are str/bool/float/
  dict/list).
* Unknown or missing values are represented by the ``UNKNOWN`` availability
  posture, so callers can always distinguish "explicitly unavailable" from
  "not yet reported".
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# CapabilityAvailability
# ---------------------------------------------------------------------------


class CapabilityAvailability(str, Enum):
    """Runtime availability posture of a capability.

    Values are stable lowercase strings to ensure JSON serialisation
    round-trips without ambiguity.
    """

    AVAILABLE = "available"
    """Capability is fully operational."""

    DEGRADED = "degraded"
    """Capability is partially operational (e.g., slow, intermittent, or
    health-gated)."""

    UNAVAILABLE = "unavailable"
    """Capability is explicitly offline or blocked."""

    UNKNOWN = "unknown"
    """Availability has not yet been reported or cannot be determined."""


AVAILABILITY_DESCRIPTIONS: Dict[str, str] = {
    CapabilityAvailability.AVAILABLE.value: (
        "Capability is fully operational and may be dispatched."
    ),
    CapabilityAvailability.DEGRADED.value: (
        "Capability is partially operational; routing should prefer healthy alternatives."
    ),
    CapabilityAvailability.UNAVAILABLE.value: (
        "Capability is explicitly offline or blocked; dispatch should be skipped."
    ),
    CapabilityAvailability.UNKNOWN.value: (
        "Availability has not yet been reported; treat as degraded for safety."
    ),
}


def availability_description(posture: CapabilityAvailability) -> str:
    """Return a human-readable description for *posture*."""
    return AVAILABILITY_DESCRIPTIONS.get(
        posture.value if isinstance(posture, CapabilityAvailability) else str(posture),
        "No description available.",
    )


# ---------------------------------------------------------------------------
# CapabilityRuntimeState
# ---------------------------------------------------------------------------


@dataclass
class CapabilityRuntimeState:
    """Runtime state snapshot for a single named capability.

    Attributes
    ----------
    name : str
        Unique capability identifier (matches CapabilityContract.name).
    availability : CapabilityAvailability
        Current availability posture.
    device_bindings : list[str]
        Device ids that currently provide this capability.
    preferred_device_ids : list[str]
        Routing hint — prefer these device ids when dispatching.
    constraint_flags : dict
        Serialised :class:`~core.capability_runtime.capability_constraint.CapabilityConstraintFlags`.
        Stored as a plain dict so this module has no circular imports.
    reliability_flags : dict
        Free-form health/reliability signals
        (e.g. ``{"health_score": 0.87, "error_rate": 0.03}``).
    last_updated : float
        Unix timestamp of the last state write.
    state_id : str
        Auto-generated unique id for this state record.
    metadata : dict
        Arbitrary extension metadata for observability.
    """

    name: str
    availability: CapabilityAvailability = CapabilityAvailability.UNKNOWN
    device_bindings: List[str] = field(default_factory=list)
    preferred_device_ids: List[str] = field(default_factory=list)
    constraint_flags: Dict[str, Any] = field(default_factory=dict)
    reliability_flags: Dict[str, Any] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)
    state_id: str = field(default_factory=lambda: f"crs_{uuid.uuid4().hex[:12]}")
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "state_id": self.state_id,
            "name": self.name,
            "availability": (
                self.availability.value
                if isinstance(self.availability, CapabilityAvailability)
                else self.availability
            ),
            "device_bindings": list(self.device_bindings),
            "preferred_device_ids": list(self.preferred_device_ids),
            "constraint_flags": dict(self.constraint_flags),
            "reliability_flags": dict(self.reliability_flags),
            "last_updated": self.last_updated,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityRuntimeState":
        """Deserialise from a plain dict, degrading gracefully on unknown values."""
        avail_raw = data.get("availability", "unknown")
        try:
            avail = CapabilityAvailability(avail_raw)
        except ValueError:
            avail = CapabilityAvailability.UNKNOWN
        return cls(
            name=data.get("name", ""),
            availability=avail,
            device_bindings=list(data.get("device_bindings", [])),
            preferred_device_ids=list(data.get("preferred_device_ids", [])),
            constraint_flags=dict(data.get("constraint_flags", {})),
            reliability_flags=dict(data.get("reliability_flags", {})),
            last_updated=float(data.get("last_updated", time.time())),
            state_id=data.get("state_id", f"crs_{uuid.uuid4().hex[:12]}"),
            metadata=dict(data.get("metadata", {})),
        )

    def is_routable(self) -> bool:
        """Return ``True`` if availability is AVAILABLE or DEGRADED."""
        return self.availability in (
            CapabilityAvailability.AVAILABLE,
            CapabilityAvailability.DEGRADED,
        )

    def is_healthy(self) -> bool:
        """Return ``True`` only if availability is AVAILABLE."""
        return self.availability == CapabilityAvailability.AVAILABLE
