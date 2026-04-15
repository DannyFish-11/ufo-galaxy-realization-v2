"""Canonical participant-tier definitions and compatibility-safe resolution."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

__all__ = [
    "ParticipantTier",
    "PARTICIPANT_TIER_IS_AUTHORITY",
    "resolve_participant_tier",
    "tier_allows_runtime_dispatch",
]


PARTICIPANT_TIER_IS_AUTHORITY: str = (
    "PARTICIPANT_TIER_IS_AUTHORITY::core.participant_tier defines canonical "
    "participant-tier semantics for runtime-host, partial-node, command-endpoint, "
    "and observer-endpoint participation."
)
"""Authority sentinel used by projection/diagnostic surfaces to report PR-3 tier alignment."""


class ParticipantTier(str, Enum):
    FULL_RUNTIME_HOST = "FULL_RUNTIME_HOST"
    PARTIAL_RUNTIME_NODE = "PARTIAL_RUNTIME_NODE"
    COMMAND_ENDPOINT = "COMMAND_ENDPOINT"
    OBSERVER_ENDPOINT = "OBSERVER_ENDPOINT"

    @classmethod
    def from_value(cls, value: Any) -> Optional["ParticipantTier"]:
        """Parse explicit participant-tier value, returning None on unknown."""
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        normalized = text.upper()
        try:
            return cls(normalized)
        except ValueError:
            return None


def resolve_participant_tier(
    *,
    explicit_tier: Any = None,
    capability_tier: Any = None,
    source_runtime_posture: Any = None,
    coordination_role: Any = None,
    orchestration_eligible: Optional[bool] = None,
) -> ParticipantTier:
    """Resolve a canonical participant tier from explicit tier + legacy signals.

    Accepted legacy capability_tier strings: ``full_runtime``,
    ``partial_runtime``, ``command_only``.
    Accepted explicit tier strings: enum names/values like
    ``FULL_RUNTIME_HOST`` and ``COMMAND_ENDPOINT``.

    Precedence
    ----------
    explicit_tier → coordination_role → capability_tier →
    source_runtime_posture → orchestration_eligible/default.
    """
    explicit = ParticipantTier.from_value(explicit_tier)
    if explicit is not None:
        return explicit

    role = str(coordination_role or "").strip().lower()
    if role == "observer_only":
        return ParticipantTier.OBSERVER_ENDPOINT

    cap = str(capability_tier or "").strip().lower()
    if cap == "full_runtime":
        return ParticipantTier.FULL_RUNTIME_HOST
    if cap == "partial_runtime":
        return ParticipantTier.PARTIAL_RUNTIME_NODE
    if cap == "command_only":
        return ParticipantTier.COMMAND_ENDPOINT

    posture = str(source_runtime_posture or "").strip().lower()
    if posture == "control_only":
        return ParticipantTier.COMMAND_ENDPOINT
    if posture == "join_runtime":
        return ParticipantTier.PARTIAL_RUNTIME_NODE

    if orchestration_eligible is False:
        return ParticipantTier.COMMAND_ENDPOINT
    return ParticipantTier.PARTIAL_RUNTIME_NODE


def tier_allows_runtime_dispatch(tier: ParticipantTier) -> bool:
    """Return True when runtime-dispatch semantics are allowed for *tier*."""
    return tier in {
        ParticipantTier.FULL_RUNTIME_HOST,
        ParticipantTier.PARTIAL_RUNTIME_NODE,
    }
