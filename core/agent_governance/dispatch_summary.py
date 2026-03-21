#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.agent_governance.dispatch_summary
==========================================

PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance

Provides :class:`DispatchSummary` — a compact, public-safe, JSON-serialisable
summary that enriches existing dispatch results with agent-governance metadata.

Also provides helper functions:

* :func:`build_dispatch_summary` — build from a dispatch result dict and
  optional ownership/role context.
* :func:`attach_dispatch_summary_to_result` — enrich an existing dispatch
  result dict with governance metadata (non-breaking, additive).
* :func:`attach_dispatch_summary_to_handoff_result` — specialised helper for
  enriching :class:`~galaxy_gateway.agent_bridge.AgentBridge` handoff results.
* :func:`attach_dispatch_summary_to_projection` — attach to a projection dict
  (follows PR-13/PR-14/PR-17 pattern).
* :func:`resolve_dispatch_summary` — derive a :class:`DispatchSummary` from
  minimal available context.

:data:`IDLE_DISPATCH_SUMMARY`
    Pre-built idle sentinel.

Integration targets (non-breaking)
------------------------------------
These helpers are designed for optional integration with existing paths:

1. **AgentBridge handoff results** — call
   :func:`attach_dispatch_summary_to_handoff_result` on the dict returned by
   :meth:`~galaxy_gateway.agent_bridge.AgentBridge.handoff` to annotate it
   with governance metadata.  The original result dict keys are preserved.

2. **CommandRouter dispatch_agent_remote results** — call
   :func:`attach_dispatch_summary_to_result` on the returned dict.

3. **SwarmAgentManifest wrapper summaries** — pass manifest fields to
   :func:`resolve_dispatch_summary` to produce a governance annotation.

4. **RuntimeProjection payloads** — call
   :func:`attach_dispatch_summary_to_projection` to add the
   ``"agent_dispatch"`` key to any projection dict.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, Optional

from .agent_role import AgentRole
from .handoff_policy import HandoffPolicy, DEFAULT_HANDOFF_POLICY, get_policy_for_role
from .ownership_summary import (
    OwnershipSummary,
    IDLE_OWNERSHIP_SUMMARY,
    build_ownership_summary,
    make_ownership_summary,
)
from .responsibility_graph import OwnershipRecord

__all__ = [
    "DispatchSummary",
    "IDLE_DISPATCH_SUMMARY",
    "build_dispatch_summary",
    "attach_dispatch_summary_to_result",
    "attach_dispatch_summary_to_handoff_result",
    "attach_dispatch_summary_to_projection",
    "resolve_dispatch_summary",
]


# ---------------------------------------------------------------------------
# DispatchSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DispatchSummary:
    """Compact, public-safe governance annotation for a dispatch event.

    Attributes
    ----------
    dispatch_role:
        String value of the role that initiated the dispatch.
    target_role:
        String value of the intended recipient role.
    handoff_valid:
        ``True`` when the (dispatch_role → target_role) edge is valid.
    ownership:
        Nested :class:`~.ownership_summary.OwnershipSummary` for the lifecycle.
    trace_id:
        Optional distributed-trace identifier.
    task_id:
        Optional task identifier.
    bridge_source:
        When derived from an AgentBridge result: ``"runtime"``,
        ``"local_fallback"``, or ``None``.
    dispatch_success:
        ``True`` when the underlying dispatch succeeded.
    failure_reason:
        Human-readable reason when ``dispatch_success=False``.
    policy_reason:
        Human-readable reason the governing policy was selected.
    schema_version:
        Schema version integer.
    """

    dispatch_role: str = AgentRole.UNASSIGNED.value
    target_role: str = AgentRole.UNASSIGNED.value
    handoff_valid: bool = False
    ownership: OwnershipSummary = dataclasses.field(
        default_factory=lambda: IDLE_OWNERSHIP_SUMMARY
    )
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    bridge_source: Optional[str] = None
    dispatch_success: bool = False
    failure_reason: str = ""
    policy_reason: str = "default"
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "dispatch_role": self.dispatch_role,
            "target_role": self.target_role,
            "handoff_valid": self.handoff_valid,
            "ownership": self.ownership.to_dict(),
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "bridge_source": self.bridge_source,
            "dispatch_success": self.dispatch_success,
            "failure_reason": self.failure_reason,
            "policy_reason": self.policy_reason,
        }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_dispatch_summary(
    dispatch_role: AgentRole,
    target_role: AgentRole,
    *,
    dispatch_success: bool = False,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    bridge_source: Optional[str] = None,
    failure_reason: str = "",
    policy: Optional[HandoffPolicy] = None,
) -> DispatchSummary:
    """Build a :class:`DispatchSummary` from role and dispatch context.

    Parameters
    ----------
    dispatch_role:
        The role initiating the dispatch.
    target_role:
        The intended recipient role.
    dispatch_success:
        Whether the dispatch succeeded.
    trace_id:
        Optional distributed-trace identifier.
    task_id:
        Optional task identifier.
    bridge_source:
        AgentBridge source tag (``"runtime"`` / ``"local_fallback"``).
    failure_reason:
        Reason for failure when ``dispatch_success=False``.
    policy:
        Governing :class:`~.handoff_policy.HandoffPolicy`.  Falls back to the
        role-specific default when ``None``.

    Returns
    -------
    DispatchSummary
        Always returns a valid summary.
    """
    from .responsibility_graph import is_valid_handoff

    effective_policy = policy if policy is not None else get_policy_for_role(dispatch_role)
    valid_edge = is_valid_handoff(dispatch_role, target_role)

    # Determine current owner: on success the target took ownership; on
    # failure with recovery permitted the RECOVERY role is current owner;
    # otherwise the dispatch_role retains ownership.
    if dispatch_success:
        current_owner = target_role
        last_reason = f"handoff to {target_role.value} succeeded"
    elif effective_policy.recovery_permitted:
        current_owner = AgentRole.RECOVERY
        last_reason = f"handoff failed, recovery active: {failure_reason}"
    else:
        current_owner = dispatch_role
        last_reason = f"handoff failed, no recovery: {failure_reason}"

    record = OwnershipRecord(
        dispatch_owner=dispatch_role,
        current_owner=current_owner,
        final_outcome_owner=target_role if dispatch_success else None,
        handoff_count=1 if dispatch_success else 0,
        is_recovery_active=(current_owner == AgentRole.RECOVERY),
        is_complete=dispatch_success,
        trace_id=trace_id,
        task_id=task_id,
        last_handoff_reason=last_reason,
    )
    ownership = build_ownership_summary(record, effective_policy)

    return DispatchSummary(
        dispatch_role=dispatch_role.value,
        target_role=target_role.value,
        handoff_valid=valid_edge,
        ownership=ownership,
        trace_id=trace_id,
        task_id=task_id,
        bridge_source=bridge_source,
        dispatch_success=dispatch_success,
        failure_reason=failure_reason,
        policy_reason=effective_policy.policy_reason,
        schema_version=1,
    )


def resolve_dispatch_summary(
    *,
    dispatch_role_str: str = AgentRole.UNASSIGNED.value,
    target_role_str: str = AgentRole.UNASSIGNED.value,
    dispatch_success: bool = False,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    bridge_source: Optional[str] = None,
    failure_reason: str = "",
    policy: Optional[HandoffPolicy] = None,
) -> DispatchSummary:
    """Derive a :class:`DispatchSummary` from string role names.

    This is the recommended entry point when integrating with existing dispatch
    paths that carry role names as plain strings (or when role information is
    absent).

    Unknown role strings are silently mapped to :attr:`~AgentRole.UNASSIGNED`.
    Always returns a valid :class:`DispatchSummary`.

    Parameters
    ----------
    dispatch_role_str:
        String role name of the dispatching agent.
    target_role_str:
        String role name of the intended recipient.
    dispatch_success:
        Whether the dispatch succeeded.
    trace_id / task_id / bridge_source / failure_reason / policy:
        See :func:`build_dispatch_summary`.

    Returns
    -------
    DispatchSummary
        Always returns a valid summary.
    """
    def _parse(raw: str) -> AgentRole:
        try:
            return AgentRole(raw)
        except (ValueError, KeyError):
            return AgentRole.UNASSIGNED

    try:
        return build_dispatch_summary(
            dispatch_role=_parse(dispatch_role_str),
            target_role=_parse(target_role_str),
            dispatch_success=dispatch_success,
            trace_id=trace_id,
            task_id=task_id,
            bridge_source=bridge_source,
            failure_reason=failure_reason,
            policy=policy,
        )
    except Exception:
        import logging as _logging
        _logging.getLogger("Galaxy.AgentGovernance.DispatchSummary").warning(
            "resolve_dispatch_summary failed, returning idle summary",
        )
        return IDLE_DISPATCH_SUMMARY


# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------


def attach_dispatch_summary_to_result(
    result_dict: Dict[str, Any],
    summary: DispatchSummary,
) -> Dict[str, Any]:
    """Attach a :class:`DispatchSummary` to an existing dispatch result dict.

    The original ``result_dict`` is **not mutated** — a new dict is returned.
    Existing keys are preserved.  If ``result_dict`` is not a dict it is
    treated as empty.

    This helper is intended for optional enrichment of results returned by
    :meth:`~core.command_router.CommandRouter.dispatch_agent_remote` or
    similar callers.

    Parameters
    ----------
    result_dict:
        The existing dispatch result to enrich.
    summary:
        The :class:`DispatchSummary` to attach under ``"agent_governance"``.

    Returns
    -------
    dict
        New dict with all original keys plus ``"agent_governance"``.
    """
    if not isinstance(result_dict, dict):
        result_dict = {}
    enriched = dict(result_dict)
    enriched["agent_governance"] = summary.to_dict()
    return enriched


def attach_dispatch_summary_to_handoff_result(
    handoff_result: Dict[str, Any],
    *,
    dispatch_role_str: str = AgentRole.LOCAL_ASSISTANT.value,
    target_role_str: str = AgentRole.REMOTE_SPECIALIST.value,
    policy: Optional[HandoffPolicy] = None,
) -> Dict[str, Any]:
    """Enrich an AgentBridge handoff result with agent-governance metadata.

    Reads ``"success"``, ``"trace_id"``, ``"task_id"``, and ``"bridge_source"``
    from *handoff_result*, derives a :class:`DispatchSummary`, and returns a
    new dict with ``"agent_governance"`` added.

    This is the recommended entry point for callers that want to annotate the
    dict returned by :meth:`~galaxy_gateway.agent_bridge.AgentBridge.handoff`
    or :meth:`~galaxy_gateway.agent_bridge.AgentBridge.handoff_from_envelope`.

    Parameters
    ----------
    handoff_result:
        The dict returned by the AgentBridge handoff method.
    dispatch_role_str:
        String role of the dispatching agent.  Defaults to
        ``"local_assistant"`` (typical AgentBridge initiator).
    target_role_str:
        String role of the target agent.  Defaults to
        ``"remote_specialist"`` (typical AgentBridge recipient).
    policy:
        Optional governing :class:`~.handoff_policy.HandoffPolicy`.

    Returns
    -------
    dict
        New dict with all original keys plus ``"agent_governance"``.
    """
    if not isinstance(handoff_result, dict):
        handoff_result = {}

    success = bool(handoff_result.get("success", False))
    trace_id = handoff_result.get("trace_id")
    task_id = handoff_result.get("task_id")
    bridge_source = handoff_result.get("bridge_source")
    failure_reason = ""
    if not success:
        failure_reason = str(
            handoff_result.get("error", handoff_result.get("reason", "handoff failed"))
        )

    summary = resolve_dispatch_summary(
        dispatch_role_str=dispatch_role_str,
        target_role_str=target_role_str,
        dispatch_success=success,
        trace_id=trace_id,
        task_id=task_id,
        bridge_source=bridge_source,
        failure_reason=failure_reason,
        policy=policy,
    )
    return attach_dispatch_summary_to_result(handoff_result, summary)


def attach_dispatch_summary_to_projection(
    projection_dict: Dict[str, Any],
    summary: DispatchSummary,
) -> Dict[str, Any]:
    """Attach a :class:`DispatchSummary` to a projection dict additively.

    Follows the same additive pattern used by PR-13/PR-14/PR-17.  The
    original dict is not mutated.

    Parameters
    ----------
    projection_dict:
        The projection dict to enrich.
    summary:
        The :class:`DispatchSummary` to attach under ``"agent_dispatch"``.

    Returns
    -------
    dict
        New dict containing all original keys plus ``"agent_dispatch"``.
    """
    if not isinstance(projection_dict, dict):
        projection_dict = {}
    result = dict(projection_dict)
    result["agent_dispatch"] = summary.to_dict()
    return result


# ---------------------------------------------------------------------------
# Pre-built idle sentinel
# ---------------------------------------------------------------------------

#: Pre-built idle sentinel for use when no active dispatch context is present.
IDLE_DISPATCH_SUMMARY = DispatchSummary(
    dispatch_role=AgentRole.UNASSIGNED.value,
    target_role=AgentRole.UNASSIGNED.value,
    handoff_valid=False,
    ownership=IDLE_OWNERSHIP_SUMMARY,
    trace_id=None,
    task_id=None,
    bridge_source=None,
    dispatch_success=False,
    failure_reason="",
    policy_reason="idle default",
    schema_version=1,
)
