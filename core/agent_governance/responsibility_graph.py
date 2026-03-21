#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.agent_governance.responsibility_graph
============================================

PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance

Defines the **responsibility graph** — the formal model expressing which
agent roles may hand off to which other roles, what ownership rules apply
at each stage of a dispatch lifecycle, and how the graph degrades when
partial or unknown role information is present.

Design constraints
-------------------
- **Additive, read-only** — this module never modifies existing dispatch
  objects such as :class:`~galaxy_gateway.agent_bridge.HandoffContract` or
  :class:`~core.control_plane.swarm_manifest.SwarmAgentManifest`.
- **Serialisable** — all structures produce ``dict`` representations safe for
  JSON, logging, and projection payloads.
- **Graceful degradation** — every public function returns a valid result even
  when inputs are ``None`` or contain unknown role strings.

Ownership semantics
--------------------
A task dispatch event moves through three ownership phases:

1. **dispatch_owner** — the agent role that initiated the dispatch
   (``PLANNER`` or ``LOCAL_ASSISTANT`` in most cases).
2. **current_owner** — the agent role currently holding execution
   responsibility.  This transitions via valid handoffs.
3. **final_outcome_owner** — the agent role that produced the final result
   (successful executor, or RECOVERY agent on fallback).

Handoff validity
-----------------
The graph defines which (source_role → target_role) transitions are
*valid*.  Transitions outside this set are flagged as invalid but never
raise exceptions so that existing dispatch paths are not disrupted.

Valid edges::

    PLANNER         → EXECUTOR, BRIDGE, LOCAL_ASSISTANT, REMOTE_SPECIALIST
    EXECUTOR        → BRIDGE, REMOTE_SPECIALIST, RECOVERY
    LOCAL_ASSISTANT → BRIDGE, REMOTE_SPECIALIST, RECOVERY
    BRIDGE          → EXECUTOR, REMOTE_SPECIALIST, RECOVERY
    RECOVERY        → EXECUTOR   (re-try after recovery)
    OBSERVER        → (none — observer never initiates handoffs)
    REMOTE_SPECIALIST → RECOVERY
    UNASSIGNED      → (none — unresolved role; no valid handoffs)

Recovery semantics
-------------------
Any handoff edge that targets ``RECOVERY`` transfers ownership to the
recovery agent.  The recovery agent may then re-attempt via ``EXECUTOR``
(recovery retry) or report a terminal failure.

Fallback (via AgentBridge ``local_fallback``) maps to RECOVERY taking
ownership from BRIDGE when the remote runtime is unreachable.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, FrozenSet, Optional, Set, Tuple

from .agent_role import AgentRole

__all__ = [
    "HANDOFF_GRAPH",
    "is_valid_handoff",
    "OwnershipRecord",
    "OwnershipTransferResult",
    "apply_ownership_transfer",
    "can_role_initiate_handoff",
    "can_role_receive_handoff",
    "describe_handoff_edge",
]


# ---------------------------------------------------------------------------
# Handoff graph
# ---------------------------------------------------------------------------

#: Valid (source_role, target_role) handoff edges.
#:
#: Stored as a dict from ``AgentRole`` to ``FrozenSet[AgentRole]`` of valid
#: targets.  Missing keys mean no outgoing edges (role cannot initiate).
HANDOFF_GRAPH: Dict[AgentRole, FrozenSet[AgentRole]] = {
    AgentRole.PLANNER: frozenset({
        AgentRole.EXECUTOR,
        AgentRole.BRIDGE,
        AgentRole.LOCAL_ASSISTANT,
        AgentRole.REMOTE_SPECIALIST,
    }),
    AgentRole.EXECUTOR: frozenset({
        AgentRole.BRIDGE,
        AgentRole.REMOTE_SPECIALIST,
        AgentRole.RECOVERY,
    }),
    AgentRole.LOCAL_ASSISTANT: frozenset({
        AgentRole.BRIDGE,
        AgentRole.REMOTE_SPECIALIST,
        AgentRole.RECOVERY,
    }),
    AgentRole.BRIDGE: frozenset({
        AgentRole.EXECUTOR,
        AgentRole.REMOTE_SPECIALIST,
        AgentRole.RECOVERY,
    }),
    AgentRole.RECOVERY: frozenset({
        AgentRole.EXECUTOR,
    }),
    AgentRole.REMOTE_SPECIALIST: frozenset({
        AgentRole.RECOVERY,
    }),
    # OBSERVER and UNASSIGNED: no outgoing handoff edges
    AgentRole.OBSERVER: frozenset(),
    AgentRole.UNASSIGNED: frozenset(),
}


def is_valid_handoff(
    source_role: AgentRole,
    target_role: AgentRole,
) -> bool:
    """Return ``True`` if a handoff from *source_role* to *target_role* is valid.

    Parameters
    ----------
    source_role:
        The role initiating the handoff.
    target_role:
        The role receiving the handoff.

    Returns
    -------
    bool
        ``True`` when the edge is in :data:`HANDOFF_GRAPH`.
    """
    targets: FrozenSet[AgentRole] = HANDOFF_GRAPH.get(source_role, frozenset())
    return target_role in targets


def can_role_initiate_handoff(role: AgentRole) -> bool:
    """Return ``True`` if *role* is allowed to initiate a handoff."""
    return bool(HANDOFF_GRAPH.get(role))


def can_role_receive_handoff(role: AgentRole) -> bool:
    """Return ``True`` if any valid edge in the graph points *to* *role*."""
    for targets in HANDOFF_GRAPH.values():
        if role in targets:
            return True
    return False


def describe_handoff_edge(
    source_role: AgentRole,
    target_role: AgentRole,
) -> str:
    """Return a human-readable description of a (source → target) handoff edge.

    Parameters
    ----------
    source_role:
        The originating role.
    target_role:
        The receiving role.

    Returns
    -------
    str
        A description string suitable for logging or API payloads.
    """
    valid = is_valid_handoff(source_role, target_role)
    status = "valid" if valid else "invalid"
    is_recovery = target_role == AgentRole.RECOVERY
    suffix = " [recovery path]" if is_recovery else ""
    return (
        f"{source_role.value} → {target_role.value} [{status}]{suffix}"
    )


# ---------------------------------------------------------------------------
# Ownership record
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OwnershipRecord:
    """Mutable ownership record for a single dispatch/handoff lifecycle.

    This record tracks ownership through the phases of a task dispatch:

    1. ``dispatch_owner`` — set at dispatch start; does not change.
    2. ``current_owner`` — updated on each valid handoff.
    3. ``final_outcome_owner`` — set when the outcome is produced.
    4. ``handoff_count`` — incremented on each ownership transfer.
    5. ``is_recovery_active`` — ``True`` when RECOVERY holds ownership.
    6. ``is_complete`` — ``True`` when the lifecycle is closed.
    7. ``trace_id`` / ``task_id`` — optional identity fields for correlation.

    Attributes
    ----------
    dispatch_owner:
        Role that initiated the dispatch.  Immutable after creation.
    current_owner:
        Role currently holding execution responsibility.
    final_outcome_owner:
        Role that produced the final outcome.  ``None`` until the lifecycle
        ends.
    handoff_count:
        Number of ownership transfers applied.
    is_recovery_active:
        ``True`` when a RECOVERY agent currently holds ownership.
    is_complete:
        ``True`` when the lifecycle is closed (success or terminal failure).
    trace_id:
        Optional distributed-trace identifier.
    task_id:
        Optional task identifier.
    last_handoff_reason:
        Human-readable reason for the most recent handoff.
    schema_version:
        Schema version integer.
    """

    dispatch_owner: AgentRole = AgentRole.UNASSIGNED
    current_owner: AgentRole = AgentRole.UNASSIGNED
    final_outcome_owner: Optional[AgentRole] = None
    handoff_count: int = 0
    is_recovery_active: bool = False
    is_complete: bool = False
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    last_handoff_reason: str = "initial"
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "dispatch_owner": self.dispatch_owner.value,
            "current_owner": self.current_owner.value,
            "final_outcome_owner": (
                self.final_outcome_owner.value
                if self.final_outcome_owner is not None
                else None
            ),
            "handoff_count": self.handoff_count,
            "is_recovery_active": self.is_recovery_active,
            "is_complete": self.is_complete,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "last_handoff_reason": self.last_handoff_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OwnershipRecord":
        """Reconstruct an :class:`OwnershipRecord` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        def _parse_role(key: str, default: AgentRole = AgentRole.UNASSIGNED) -> AgentRole:
            raw = data.get(key)
            if raw is None:
                return default
            try:
                return AgentRole(raw)
            except (ValueError, KeyError):
                return AgentRole.UNASSIGNED

        def _safe_int(value: Any, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        final_raw = data.get("final_outcome_owner")
        final: Optional[AgentRole] = None
        if final_raw is not None:
            try:
                final = AgentRole(final_raw)
            except (ValueError, KeyError):
                final = AgentRole.UNASSIGNED

        return cls(
            dispatch_owner=_parse_role("dispatch_owner"),
            current_owner=_parse_role("current_owner"),
            final_outcome_owner=final,
            handoff_count=_safe_int(data.get("handoff_count", 0)),
            is_recovery_active=bool(data.get("is_recovery_active", False)),
            is_complete=bool(data.get("is_complete", False)),
            trace_id=data.get("trace_id"),
            task_id=data.get("task_id"),
            last_handoff_reason=str(data.get("last_handoff_reason", "reconstructed")),
            schema_version=int(data.get("schema_version", 1)),
        )


# ---------------------------------------------------------------------------
# Ownership transfer
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class OwnershipTransferResult:
    """Result of an :func:`apply_ownership_transfer` call.

    Attributes
    ----------
    success:
        ``True`` when the transfer was applied; ``False`` when it was rejected
        (invalid edge, lifecycle already complete, or invalid role values).
    previous_owner:
        The :class:`AgentRole` that held ownership before this call.
    new_owner:
        The :class:`AgentRole` that holds ownership after this call.
    is_valid_edge:
        ``True`` when the (previous → new) edge is in :data:`HANDOFF_GRAPH`.
    is_recovery_transition:
        ``True`` when *new_owner* is :attr:`~AgentRole.RECOVERY`.
    rejection_reason:
        Human-readable reason when ``success=False``.
    """

    success: bool = False
    previous_owner: AgentRole = AgentRole.UNASSIGNED
    new_owner: AgentRole = AgentRole.UNASSIGNED
    is_valid_edge: bool = False
    is_recovery_transition: bool = False
    rejection_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "success": self.success,
            "previous_owner": self.previous_owner.value,
            "new_owner": self.new_owner.value,
            "is_valid_edge": self.is_valid_edge,
            "is_recovery_transition": self.is_recovery_transition,
            "rejection_reason": self.rejection_reason,
        }


def apply_ownership_transfer(
    record: OwnershipRecord,
    target_role: AgentRole,
    reason: str = "",
) -> OwnershipTransferResult:
    """Attempt to transfer ownership in *record* to *target_role*.

    The function always returns an :class:`OwnershipTransferResult` and never
    raises.  When the transfer is invalid the record is **not modified**.

    Parameters
    ----------
    record:
        The mutable :class:`OwnershipRecord` to update.
    target_role:
        The role to transfer ownership to.
    reason:
        Optional human-readable reason for the transfer.

    Returns
    -------
    OwnershipTransferResult
        Describes whether the transfer was applied and why.
    """
    previous = record.current_owner
    valid_edge = is_valid_handoff(previous, target_role)
    is_recovery = target_role == AgentRole.RECOVERY

    if record.is_complete:
        return OwnershipTransferResult(
            success=False,
            previous_owner=previous,
            new_owner=previous,
            is_valid_edge=valid_edge,
            is_recovery_transition=is_recovery,
            rejection_reason="lifecycle is already complete",
        )

    if not valid_edge:
        return OwnershipTransferResult(
            success=False,
            previous_owner=previous,
            new_owner=previous,
            is_valid_edge=False,
            is_recovery_transition=is_recovery,
            rejection_reason=(
                f"invalid handoff edge: {previous.value} → {target_role.value}"
            ),
        )

    # Apply transfer
    record.current_owner = target_role
    record.handoff_count += 1
    record.is_recovery_active = is_recovery
    record.last_handoff_reason = reason or f"handoff to {target_role.value}"

    return OwnershipTransferResult(
        success=True,
        previous_owner=previous,
        new_owner=target_role,
        is_valid_edge=True,
        is_recovery_transition=is_recovery,
        rejection_reason="",
    )
