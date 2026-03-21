#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.agent_governance.handoff_policy
========================================

PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance

Defines :class:`HandoffPolicy` — a serialisable policy contract that governs
*how* ownership transitions between agents are handled, including:

* Whether the handoff must be acknowledged by the receiving agent.
* Maximum handoff depth (number of sequential ownership transfers before
  the lifecycle is considered stale).
* Whether recovery is permitted on handoff failure.
* Timeout semantics (advisory; not enforced here).
* A human-readable policy reason.

Design
-------
:class:`HandoffPolicy` is intentionally **advisory** — it describes the
intended governance rules for a dispatch chain.  Enforcement is the
responsibility of the dispatch layer (``AgentBridge``, ``CommandRouter``).
This separation keeps the governance layer additive and non-breaking.

Pre-built policies
-------------------
:data:`DEFAULT_HANDOFF_POLICY`
    Conservative default: recovery permitted, ack required, max depth 5.

:data:`RECOVERY_HANDOFF_POLICY`
    Recovery-focused: slightly relaxed ack requirement (best-effort), max
    depth 2 (recovery should resolve quickly).

:data:`OBSERVER_HANDOFF_POLICY`
    Read-only observer: no handoffs permitted (max_depth=0).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional

from .agent_role import AgentRole

__all__ = [
    "HandoffPolicy",
    "DEFAULT_HANDOFF_POLICY",
    "RECOVERY_HANDOFF_POLICY",
    "OBSERVER_HANDOFF_POLICY",
    "get_policy_for_role",
]


# ---------------------------------------------------------------------------
# HandoffPolicy dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class HandoffPolicy:
    """Serialisable policy governing ownership handoff behaviour.

    Attributes
    ----------
    ack_required:
        When ``True``, the receiving agent must acknowledge the handoff before
        the sending agent releases ownership.  Advisory — actual enforcement
        lives in the dispatch layer.
    recovery_permitted:
        When ``True``, a RECOVERY agent may inherit ownership if the handoff
        fails or the primary executor is unavailable.
    max_handoff_depth:
        Maximum number of sequential ownership transfers allowed before the
        chain is considered stale.  ``0`` means no handoffs permitted.
    handoff_timeout_hint_ms:
        Advisory timeout in milliseconds for the handoff window.  The dispatch
        layer (AgentBridge) may use this as a basis for its own timeout, but
        is not required to.
    allow_recovery_retry:
        When ``True``, RECOVERY may attempt a single retry via EXECUTOR after
        taking ownership.
    policy_reason:
        Human-readable explanation of why this policy was selected.
    schema_version:
        Schema version integer.
    """

    ack_required: bool = True
    recovery_permitted: bool = True
    max_handoff_depth: int = 5
    handoff_timeout_hint_ms: int = 10_000
    allow_recovery_retry: bool = True
    policy_reason: str = "default"
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "ack_required": self.ack_required,
            "recovery_permitted": self.recovery_permitted,
            "max_handoff_depth": self.max_handoff_depth,
            "handoff_timeout_hint_ms": self.handoff_timeout_hint_ms,
            "allow_recovery_retry": self.allow_recovery_retry,
            "policy_reason": self.policy_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HandoffPolicy":
        """Reconstruct a :class:`HandoffPolicy` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        return cls(
            ack_required=bool(data.get("ack_required", True)),
            recovery_permitted=bool(data.get("recovery_permitted", True)),
            max_handoff_depth=int(data.get("max_handoff_depth", 5)),
            handoff_timeout_hint_ms=int(data.get("handoff_timeout_hint_ms", 10_000)),
            allow_recovery_retry=bool(data.get("allow_recovery_retry", True)),
            policy_reason=str(data.get("policy_reason", "reconstructed from dict")),
            schema_version=int(data.get("schema_version", 1)),
        )

    def is_depth_exceeded(self, current_handoff_count: int) -> bool:
        """Return ``True`` if *current_handoff_count* meets or exceeds the policy limit.

        When ``max_handoff_depth`` is ``0`` any count (including 0) is considered
        to have exceeded the limit, enforcing the "no handoffs permitted" semantics
        used by :data:`OBSERVER_HANDOFF_POLICY`.
        """
        return current_handoff_count >= self.max_handoff_depth


# ---------------------------------------------------------------------------
# Pre-built policy sentinels
# ---------------------------------------------------------------------------

#: Conservative default policy: recovery permitted, ack required, depth ≤ 5.
DEFAULT_HANDOFF_POLICY = HandoffPolicy(
    ack_required=True,
    recovery_permitted=True,
    max_handoff_depth=5,
    handoff_timeout_hint_ms=10_000,
    allow_recovery_retry=True,
    policy_reason="default conservative policy",
    schema_version=1,
)

#: Recovery-focused policy: best-effort ack, depth ≤ 2, retry allowed.
RECOVERY_HANDOFF_POLICY = HandoffPolicy(
    ack_required=False,
    recovery_permitted=True,
    max_handoff_depth=2,
    handoff_timeout_hint_ms=5_000,
    allow_recovery_retry=True,
    policy_reason="recovery-focused: best-effort ack, low depth limit",
    schema_version=1,
)

#: Observer policy: no handoffs permitted (read-only role).
OBSERVER_HANDOFF_POLICY = HandoffPolicy(
    ack_required=False,
    recovery_permitted=False,
    max_handoff_depth=0,
    handoff_timeout_hint_ms=0,
    allow_recovery_retry=False,
    policy_reason="observer role: no handoffs permitted",
    schema_version=1,
)


# ---------------------------------------------------------------------------
# Role → policy selector
# ---------------------------------------------------------------------------

_ROLE_POLICY_MAP: Dict[AgentRole, HandoffPolicy] = {
    AgentRole.PLANNER: DEFAULT_HANDOFF_POLICY,
    AgentRole.EXECUTOR: DEFAULT_HANDOFF_POLICY,
    AgentRole.BRIDGE: DEFAULT_HANDOFF_POLICY,
    AgentRole.RECOVERY: RECOVERY_HANDOFF_POLICY,
    AgentRole.OBSERVER: OBSERVER_HANDOFF_POLICY,
    AgentRole.LOCAL_ASSISTANT: DEFAULT_HANDOFF_POLICY,
    AgentRole.REMOTE_SPECIALIST: DEFAULT_HANDOFF_POLICY,
    AgentRole.UNASSIGNED: DEFAULT_HANDOFF_POLICY,
}


def get_policy_for_role(role: AgentRole) -> HandoffPolicy:
    """Return the :class:`HandoffPolicy` appropriate for *role*.

    Falls back to :data:`DEFAULT_HANDOFF_POLICY` for unknown roles.

    Parameters
    ----------
    role:
        The :class:`AgentRole` to look up.

    Returns
    -------
    HandoffPolicy
        The policy for *role*.
    """
    return _ROLE_POLICY_MAP.get(role, DEFAULT_HANDOFF_POLICY)
