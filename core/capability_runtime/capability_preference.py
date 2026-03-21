#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_runtime.capability_preference
===============================================

PR-20 (V4) — Capability Runtime State

Defines :class:`CapabilityPreference` — a serialisable model that expresses
**routing preferences** for a capability at runtime.

Routing and planning components read these preferences to make better
decisions about *which* device or executor to use when a capability could
be satisfied by multiple providers.

Fields
------
preferred_device_ids : list[str]
    Ordered list of device ids to try first.  The first reachable, healthy
    device in this list wins.

preferred_executor : str
    Name of a preferred executor class or executor node id.  Empty string
    means "no preference".

weight : float
    Relative routing weight in the range ``[0.0, 1.0]``.  Higher weight
    means stronger preference.  Defaults to ``1.0`` (full weight).

sticky : bool
    If ``True``, routing should try to reuse the same device/executor for
    repeated invocations of this capability within a session.

notes : str
    Human-readable notes for observability (not used in routing logic).

Design notes
------------
* Frozen dataclass — preferences should be replaced atomically, not mutated.
* All fields have safe defaults so a "no preference" object is valid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# CapabilityPreference
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityPreference:
    """Routing preferences for a named capability.

    Attributes
    ----------
    preferred_device_ids : list[str]
        Ordered list of preferred device ids.
    preferred_executor : str
        Name/id of the preferred executor.  Empty = no preference.
    weight : float
        Routing weight in ``[0.0, 1.0]``.  Defaults to ``1.0``.
    sticky : bool
        Prefer reusing the same device/executor across a session.
    notes : str
        Free-text notes for observability.
    """

    preferred_device_ids: List[str] = field(default_factory=list)
    preferred_executor: str = ""
    weight: float = 1.0
    sticky: bool = False
    notes: str = ""

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "preferred_device_ids": list(self.preferred_device_ids),
            "preferred_executor": self.preferred_executor,
            "weight": self.weight,
            "sticky": self.sticky,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityPreference":
        """Deserialise from a plain dict; unknown keys are ignored."""
        raw_weight = data.get("weight", 1.0)
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 1.0
        weight = max(0.0, min(1.0, weight))
        return cls(
            preferred_device_ids=list(data.get("preferred_device_ids", [])),
            preferred_executor=str(data.get("preferred_executor", "")),
            weight=weight,
            sticky=bool(data.get("sticky", False)),
            notes=str(data.get("notes", "")),
        )

    def has_preference(self) -> bool:
        """Return ``True`` if any non-default preference is expressed."""
        return bool(self.preferred_device_ids) or bool(self.preferred_executor)


# ---------------------------------------------------------------------------
# Pre-built sentinels
# ---------------------------------------------------------------------------

NO_PREFERENCE = CapabilityPreference()
"""Sentinel: no routing preference expressed."""
