#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.agent_governance.ownership_summary
==========================================

PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance

Provides :class:`OwnershipSummary` — a compact, public-safe, JSON-serialisable
summary of an agent ownership lifecycle.

Also provides helper functions:

* :func:`build_ownership_summary` — build summary from an
  :class:`~.responsibility_graph.OwnershipRecord` and optional
  :class:`~.handoff_policy.HandoffPolicy`.
* :func:`attach_ownership_to_projection` — attach to a projection dict
  additively (following the PR-13/PR-14/PR-17 pattern).
* :func:`get_ownership_hints` — compact boolean/scalar hints.
* :func:`make_ownership_summary` — one-call builder from scalar inputs.

:data:`IDLE_OWNERSHIP_SUMMARY`
    Pre-built idle sentinel for local/uninitialised state.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional

from .agent_role import AgentRole
from .handoff_policy import HandoffPolicy, DEFAULT_HANDOFF_POLICY
from .responsibility_graph import OwnershipRecord

__all__ = [
    "OwnershipSummary",
    "IDLE_OWNERSHIP_SUMMARY",
    "build_ownership_summary",
    "attach_ownership_to_projection",
    "get_ownership_hints",
    "make_ownership_summary",
]


# ---------------------------------------------------------------------------
# OwnershipSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class OwnershipSummary:
    """Compact, public-safe summary of an agent ownership lifecycle.

    This is the preferred type for API responses, projection payloads, and log
    records.  It flattens the most important fields from
    :class:`~.responsibility_graph.OwnershipRecord` and
    :class:`~.handoff_policy.HandoffPolicy` into a single serialisable object.

    Attributes
    ----------
    dispatch_owner:
        String value of the role that initiated the dispatch.
    current_owner:
        String value of the role currently holding execution responsibility.
    final_outcome_owner:
        String value of the role that produced the final outcome, or ``None``.
    handoff_count:
        Number of ownership transfers applied in this lifecycle.
    is_recovery_active:
        ``True`` when a RECOVERY agent holds current ownership.
    is_complete:
        ``True`` when the lifecycle is closed.
    max_handoff_depth:
        Policy-derived maximum permitted handoff depth.
    depth_exceeded:
        ``True`` when ``handoff_count >= max_handoff_depth``.
    recovery_permitted:
        ``True`` per the governing policy.
    trace_id:
        Optional distributed-trace identifier.
    task_id:
        Optional task identifier.
    last_handoff_reason:
        Human-readable reason for the most recent ownership transfer.
    policy_reason:
        Human-readable reason the governing policy was selected.
    schema_version:
        Schema version integer.
    """

    dispatch_owner: str = AgentRole.UNASSIGNED.value
    current_owner: str = AgentRole.UNASSIGNED.value
    final_outcome_owner: Optional[str] = None
    handoff_count: int = 0
    is_recovery_active: bool = False
    is_complete: bool = False
    max_handoff_depth: int = 5
    depth_exceeded: bool = False
    recovery_permitted: bool = True
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    last_handoff_reason: str = "initial"
    policy_reason: str = "default"
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "dispatch_owner": self.dispatch_owner,
            "current_owner": self.current_owner,
            "final_outcome_owner": self.final_outcome_owner,
            "handoff_count": self.handoff_count,
            "is_recovery_active": self.is_recovery_active,
            "is_complete": self.is_complete,
            "max_handoff_depth": self.max_handoff_depth,
            "depth_exceeded": self.depth_exceeded,
            "recovery_permitted": self.recovery_permitted,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "last_handoff_reason": self.last_handoff_reason,
            "policy_reason": self.policy_reason,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_ownership_summary(
    record: OwnershipRecord,
    policy: Optional[HandoffPolicy] = None,
) -> "OwnershipSummary":
    """Build an :class:`OwnershipSummary` from an ownership record and policy.

    Parameters
    ----------
    record:
        The :class:`~.responsibility_graph.OwnershipRecord` to summarise.
    policy:
        Optional :class:`~.handoff_policy.HandoffPolicy` to derive depth and
        recovery fields.  Falls back to :data:`~.handoff_policy.DEFAULT_HANDOFF_POLICY`
        when ``None``.

    Returns
    -------
    OwnershipSummary
        A compact, public-safe summary.
    """
    effective_policy = policy if policy is not None else DEFAULT_HANDOFF_POLICY

    depth_exceeded = effective_policy.is_depth_exceeded(record.handoff_count)

    final: Optional[str] = None
    if record.final_outcome_owner is not None:
        final = record.final_outcome_owner.value

    return OwnershipSummary(
        dispatch_owner=record.dispatch_owner.value,
        current_owner=record.current_owner.value,
        final_outcome_owner=final,
        handoff_count=record.handoff_count,
        is_recovery_active=record.is_recovery_active,
        is_complete=record.is_complete,
        max_handoff_depth=effective_policy.max_handoff_depth,
        depth_exceeded=depth_exceeded,
        recovery_permitted=effective_policy.recovery_permitted,
        trace_id=record.trace_id,
        task_id=record.task_id,
        last_handoff_reason=record.last_handoff_reason,
        policy_reason=effective_policy.policy_reason,
        schema_version=record.schema_version,
    )


# ---------------------------------------------------------------------------
# One-call builder from scalar inputs
# ---------------------------------------------------------------------------


def make_ownership_summary(
    *,
    dispatch_owner: str = AgentRole.UNASSIGNED.value,
    current_owner: str = AgentRole.UNASSIGNED.value,
    final_outcome_owner: Optional[str] = None,
    handoff_count: int = 0,
    is_recovery_active: bool = False,
    is_complete: bool = False,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    last_handoff_reason: str = "initial",
    policy: Optional[HandoffPolicy] = None,
) -> "OwnershipSummary":
    """Build an :class:`OwnershipSummary` directly from scalar inputs.

    This is useful when integrating with existing dispatch paths that do not
    yet carry a full :class:`~.responsibility_graph.OwnershipRecord`.

    All inputs are optional and default to idle/unassigned values.

    Returns
    -------
    OwnershipSummary
        Always returns a valid summary.
    """
    def _parse(raw: str) -> AgentRole:
        try:
            return AgentRole(raw)
        except (ValueError, KeyError):
            return AgentRole.UNASSIGNED

    dispatch_role = _parse(dispatch_owner)
    current_role = _parse(current_owner)

    final_role: Optional[AgentRole] = None
    if final_outcome_owner is not None:
        final_role = _parse(final_outcome_owner)

    record = OwnershipRecord(
        dispatch_owner=dispatch_role,
        current_owner=current_role,
        final_outcome_owner=final_role,
        handoff_count=handoff_count,
        is_recovery_active=is_recovery_active,
        is_complete=is_complete,
        trace_id=trace_id,
        task_id=task_id,
        last_handoff_reason=last_handoff_reason,
    )
    return build_ownership_summary(record, policy)


# ---------------------------------------------------------------------------
# Projection attachment
# ---------------------------------------------------------------------------


def attach_ownership_to_projection(
    projection_dict: Dict[str, Any],
    summary: "OwnershipSummary",
) -> Dict[str, Any]:
    """Attach an :class:`OwnershipSummary` to a projection dict additively.

    Follows the same additive pattern used by PR-13, PR-14, PR-17.  The
    original ``projection_dict`` is not mutated — a new dict is returned with
    the ``"agent_ownership"`` key added.

    Parameters
    ----------
    projection_dict:
        The projection dict to enrich.  Non-dict values are treated as empty.
    summary:
        The :class:`OwnershipSummary` to attach.

    Returns
    -------
    dict
        A new dict containing all original keys plus ``"agent_ownership"``.
    """
    if not isinstance(projection_dict, dict):
        projection_dict = {}

    result = dict(projection_dict)
    result["agent_ownership"] = summary.to_dict()
    return result


# ---------------------------------------------------------------------------
# Hints helper
# ---------------------------------------------------------------------------


def get_ownership_hints(summary: "OwnershipSummary") -> Dict[str, Any]:
    """Return compact scalar hints for quick downstream checks.

    Parameters
    ----------
    summary:
        An :class:`OwnershipSummary` to extract hints from.

    Returns
    -------
    dict
        A small dict with boolean and scalar fields.
    """
    return {
        "dispatch_owner": summary.dispatch_owner,
        "current_owner": summary.current_owner,
        "is_recovery_active": summary.is_recovery_active,
        "is_complete": summary.is_complete,
        "depth_exceeded": summary.depth_exceeded,
        "handoff_count": summary.handoff_count,
        "has_final_owner": summary.final_outcome_owner is not None,
        "recovery_permitted": summary.recovery_permitted,
    }


# ---------------------------------------------------------------------------
# Pre-built idle sentinel
# ---------------------------------------------------------------------------

#: Pre-built idle summary for use when no active dispatch context is present.
IDLE_OWNERSHIP_SUMMARY = OwnershipSummary(
    dispatch_owner=AgentRole.UNASSIGNED.value,
    current_owner=AgentRole.UNASSIGNED.value,
    final_outcome_owner=None,
    handoff_count=0,
    is_recovery_active=False,
    is_complete=False,
    max_handoff_depth=5,
    depth_exceeded=False,
    recovery_permitted=True,
    trace_id=None,
    task_id=None,
    last_handoff_reason="idle",
    policy_reason="idle default",
    schema_version=1,
)
