#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_runtime.capability_summary
============================================

PR-20 (V4) — Capability Runtime State

Provides :class:`CapabilityRuntimeSummary` — a compact, read-friendly,
JSON-serialisable summary of the runtime state for a single named capability.

Summaries are the *public face* of the capability runtime state layer: they
are returned by read-only endpoints, attached to projection enrichments, and
consumed by routing decision helpers.

Also provides:

* :data:`UNKNOWN_CAPABILITY_SUMMARY` — a safe sentinel for unknown/missing
  capabilities.
* :func:`make_capability_summary` — one-call builder from scalar inputs.
* :func:`get_capability_runtime_snapshot` — return all known summaries as a
  JSON-serialisable dict, with graceful degradation.
* :func:`attach_runtime_summary_to_projection` — additive enrichment helper
  for projection dicts.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, List, Optional

from .capability_state import CapabilityAvailability

__all__ = [
    "CapabilityRuntimeSummary",
    "UNKNOWN_CAPABILITY_SUMMARY",
    "make_capability_summary",
    "get_capability_runtime_snapshot",
    "attach_runtime_summary_to_projection",
]

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# CapabilityRuntimeSummary
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CapabilityRuntimeSummary:
    """Public-safe, read-only summary of a capability's runtime state.

    Attributes
    ----------
    capability_name : str
        Unique capability identifier.
    availability : str
        Availability posture value (``"available"``, ``"degraded"``, etc.).
    preferred_device_ids : list[str]
        Routing-hint device ids.
    constraint_flags : list[str]
        Active constraint flag names (empty list when no constraints).
    reliability_notes : str
        Human-readable reliability/health notes.
    device_bindings : list[str]
        Device ids currently bound to this capability.
    last_updated : float
        Unix timestamp of the last runtime state write.
    metadata : dict
        Arbitrary extension metadata.
    schema_version : int
        Fixed at ``1`` for this PR.
    """

    capability_name: str
    availability: str = CapabilityAvailability.UNKNOWN.value
    preferred_device_ids: List[str] = dataclasses.field(default_factory=list)
    constraint_flags: List[str] = dataclasses.field(default_factory=list)
    reliability_notes: str = ""
    device_bindings: List[str] = dataclasses.field(default_factory=list)
    last_updated: float = dataclasses.field(default_factory=time.time)
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "capability_name": self.capability_name,
            "availability": self.availability,
            "preferred_device_ids": list(self.preferred_device_ids),
            "constraint_flags": list(self.constraint_flags),
            "reliability_notes": self.reliability_notes,
            "device_bindings": list(self.device_bindings),
            "last_updated": self.last_updated,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityRuntimeSummary":
        """Deserialise from a plain dict; unknown values degrade gracefully."""
        avail_raw = data.get("availability", "unknown")
        known_values = {a.value for a in CapabilityAvailability}
        avail = avail_raw if avail_raw in known_values else CapabilityAvailability.UNKNOWN.value
        return cls(
            capability_name=str(data.get("capability_name", "")),
            availability=avail,
            preferred_device_ids=list(data.get("preferred_device_ids", [])),
            constraint_flags=list(data.get("constraint_flags", [])),
            reliability_notes=str(data.get("reliability_notes", "")),
            device_bindings=list(data.get("device_bindings", [])),
            last_updated=float(data.get("last_updated", time.time())),
            metadata=dict(data.get("metadata", {})),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

UNKNOWN_CAPABILITY_SUMMARY = CapabilityRuntimeSummary(
    capability_name="__unknown__",
    availability=CapabilityAvailability.UNKNOWN.value,
    reliability_notes="No runtime state recorded for this capability.",
)
"""Safe sentinel returned when a capability has no recorded runtime state."""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_capability_summary(
    capability_name: str,
    availability: str = "unknown",
    preferred_device_ids: Optional[List[str]] = None,
    constraint_flags: Optional[List[str]] = None,
    reliability_notes: str = "",
    device_bindings: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CapabilityRuntimeSummary:
    """Build a :class:`CapabilityRuntimeSummary` from scalar inputs.

    Unknown *availability* values are silently coerced to ``"unknown"``.

    Parameters
    ----------
    capability_name:
        Unique capability identifier.
    availability:
        Posture string (``"available"``, ``"degraded"``, ``"unavailable"``,
        or ``"unknown"``).
    preferred_device_ids:
        Routing-hint device ids (``None`` → empty list).
    constraint_flags:
        Active flag names (``None`` → empty list).
    reliability_notes:
        Human-readable health/reliability notes.
    device_bindings:
        Device ids currently providing this capability.
    metadata:
        Arbitrary extension metadata.
    """
    known_values = {a.value for a in CapabilityAvailability}
    safe_avail = availability if availability in known_values else CapabilityAvailability.UNKNOWN.value
    return CapabilityRuntimeSummary(
        capability_name=capability_name,
        availability=safe_avail,
        preferred_device_ids=list(preferred_device_ids or []),
        constraint_flags=list(constraint_flags or []),
        reliability_notes=reliability_notes,
        device_bindings=list(device_bindings or []),
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def get_capability_runtime_snapshot() -> Dict[str, Any]:
    """Return all known capability runtime summaries as a JSON-serialisable dict.

    Pulls data from :class:`~core.capability_runtime.capability_registry_runtime.CapabilityRuntimeRegistry`
    (singleton).  Degrades gracefully when the registry is empty or
    unavailable.

    Response shape
    --------------
    ::

        {
          "capabilities": {
            "<capability_name>": { ...summary fields... },
            ...
          },
          "total_capabilities": <int>,
          "schema_version": 1
        }
    """
    try:
        from .capability_registry_runtime import CapabilityRuntimeRegistry
        registry = CapabilityRuntimeRegistry.get_instance()
        summaries = registry.list_summaries()
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        summaries = []

    caps_dict: Dict[str, Any] = {}
    for s in summaries:
        caps_dict[s.capability_name] = s.to_dict()

    return {
        "capabilities": caps_dict,
        "total_capabilities": len(caps_dict),
        "schema_version": SCHEMA_VERSION,
    }


def attach_runtime_summary_to_projection(
    projection: Dict[str, Any],
    capability_name: str,
) -> Dict[str, Any]:
    """Attach runtime summary for *capability_name* to *projection* additively.

    The original dict is **not** mutated; a shallow copy is returned with a
    new ``"capability_runtime"`` key.

    Parameters
    ----------
    projection:
        Any dict (e.g. a presence projection or task result dict).
    capability_name:
        The capability to look up.

    Returns
    -------
    dict
        A new dict equal to *projection* plus ``"capability_runtime"``.
    """
    try:
        from .capability_registry_runtime import CapabilityRuntimeRegistry
        registry = CapabilityRuntimeRegistry.get_instance()
        summary = registry.get_summary(capability_name)
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        summary = UNKNOWN_CAPABILITY_SUMMARY

    result = dict(projection)
    result["capability_runtime"] = summary.to_dict() if summary else UNKNOWN_CAPABILITY_SUMMARY.to_dict()
    return result
