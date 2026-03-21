#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation.formation_policy
=========================================

PR-17 (V4) — Device Formation & Multi-Device Group Model

Defines the **BarrierPosture** enum and the **FormationPolicy** dataclass.

``FormationPolicy`` captures the intent and gate conditions for a device
formation group — it is a higher-level description than
:class:`~core.cross_device_policy.RoutingPolicy` (which governs *dispatch*)
and sits alongside the existing PR-11 execution policy (which governs *risk and
budget*).

A ``FormationPolicy`` answers:
  - What barrier/completion posture does the formation intend?
  - Is multi-device participation required or optional?
  - Is merge confirmation required before the formation closes?
  - Which devices are the minimum required set for a valid formation?
  - What is the fallback intent if the primary device is unavailable?
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "BarrierPosture",
    "BARRIER_POSTURE_DESCRIPTIONS",
    "FormationPolicy",
    "DEFAULT_LOCAL_FORMATION_POLICY",
]


# ---------------------------------------------------------------------------
# BarrierPosture enum
# ---------------------------------------------------------------------------


class BarrierPosture(str, Enum):
    """Stable enum of barrier/completion posture values for a formation group.

    The posture controls when the formation is considered *complete* and what
    conditions must be satisfied before results are merged and returned.
    """

    WAIT_ALL = "wait_all"
    """Block until all participating devices have reported results."""

    WAIT_PRIMARY = "wait_primary"
    """Block only until the PRIMARY_EXECUTION device reports a result."""

    BEST_EFFORT = "best_effort"
    """Complete as soon as a usable result is available; do not block."""

    WAIT_MERGE_OWNER = "wait_merge_owner"
    """Block until the MERGE_OWNER device has assembled the merged result."""


#: Human-readable descriptions for each :class:`BarrierPosture`.
BARRIER_POSTURE_DESCRIPTIONS: Dict[str, str] = {
    BarrierPosture.WAIT_ALL.value: (
        "Block formation completion until every participating device has "
        "reported its result.  Use when all device outputs are required for "
        "correctness."
    ),
    BarrierPosture.WAIT_PRIMARY.value: (
        "Block formation completion only until the PRIMARY_EXECUTION device "
        "reports a result.  Support and observer devices may still be in "
        "flight.  Default posture for most cross-device tasks."
    ),
    BarrierPosture.BEST_EFFORT.value: (
        "Do not block — complete as soon as a usable result is available from "
        "any device.  Suitable for fire-and-forget or low-criticality "
        "formations where partial results are acceptable."
    ),
    BarrierPosture.WAIT_MERGE_OWNER.value: (
        "Block formation completion until the device assigned the MERGE_OWNER "
        "role has assembled and returned the merged result.  Use when "
        "result-assembly logic must run on a specific device."
    ),
}


# ---------------------------------------------------------------------------
# FormationPolicy dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FormationPolicy:
    """Immutable, serialisable policy contract for a device formation group.

    Attributes
    ----------
    barrier_posture:
        The :class:`BarrierPosture` that governs when the formation is
        considered complete.  Defaults to ``WAIT_PRIMARY``.
    multi_device_required:
        ``True`` if at least two devices are required for the formation to
        proceed.  ``False`` means a single-device formation is acceptable.
    merge_confirmation_required:
        ``True`` if the merge-owner must receive explicit confirmation before
        the formation closes and results are published.
    minimum_required_device_ids:
        Optional list of device IDs that *must* be present in the formation.
        If any are absent the formation is considered degraded.
    fallback_intent:
        Human-readable string describing the fallback intent when the primary
        device is unavailable (e.g. ``"promote_fallback_device"``,
        ``"abort"``).
    policy_reason:
        Human-readable explanation of why this policy was derived.
    """

    barrier_posture: BarrierPosture = BarrierPosture.WAIT_PRIMARY
    multi_device_required: bool = False
    merge_confirmation_required: bool = False
    minimum_required_device_ids: List[str] = dataclasses.field(
        default_factory=list
    )
    fallback_intent: str = "promote_fallback_device"
    policy_reason: str = "default"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "barrier_posture": self.barrier_posture.value,
            "multi_device_required": self.multi_device_required,
            "merge_confirmation_required": self.merge_confirmation_required,
            "minimum_required_device_ids": list(self.minimum_required_device_ids),
            "fallback_intent": self.fallback_intent,
            "policy_reason": self.policy_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormationPolicy":
        """Reconstruct a :class:`FormationPolicy` from a serialised dict."""
        raw_posture = data.get("barrier_posture", BarrierPosture.WAIT_PRIMARY.value)
        try:
            posture = BarrierPosture(raw_posture)
        except (ValueError, KeyError):
            posture = BarrierPosture.WAIT_PRIMARY

        return cls(
            barrier_posture=posture,
            multi_device_required=bool(data.get("multi_device_required", False)),
            merge_confirmation_required=bool(
                data.get("merge_confirmation_required", False)
            ),
            minimum_required_device_ids=list(
                data.get("minimum_required_device_ids", [])
            ),
            fallback_intent=str(data.get("fallback_intent", "promote_fallback_device")),
            policy_reason=str(data.get("policy_reason", "reconstructed from dict")),
        )

    def __repr__(self) -> str:
        return (
            f"<FormationPolicy "
            f"posture={self.barrier_posture.value} "
            f"multi_required={self.multi_device_required}>"
        )


# ---------------------------------------------------------------------------
# Pre-built safe defaults
# ---------------------------------------------------------------------------

#: Conservative local-only formation policy for use when no cross-device
#: context is active.  Safe to use as a default in all paths.
DEFAULT_LOCAL_FORMATION_POLICY = FormationPolicy(
    barrier_posture=BarrierPosture.WAIT_PRIMARY,
    multi_device_required=False,
    merge_confirmation_required=False,
    minimum_required_device_ids=[],
    fallback_intent="abort",
    policy_reason="local default — no cross-device context",
)
