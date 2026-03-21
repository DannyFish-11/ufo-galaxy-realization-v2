#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.agent_governance
=======================

PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance

A focused additive package that formalises **agent responsibility semantics**,
**ownership transfer rules**, and **handoff governance** on top of the existing
agent dispatch and runtime handoff infrastructure.

This package answers:
  - Which agent role is responsible for a task at each lifecycle phase?
  - Which role holds current execution ownership?
  - Which role→role handoffs are valid?
  - What policy governs handoff depth and recovery behaviour?
  - Who produced the final outcome?
  - How can ownership and dispatch governance be attached to projection
    payloads for inspection and accountability?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~galaxy_gateway.agent_bridge.HandoffContract` — PR-5 runtime bridge
  (trace_id, task_id, bridge_source consumed as read-only inputs).
* :func:`~core.command_router.CommandRouter.dispatch_agent_remote` results
  (result dict keys consumed; never modified in-place).
* :class:`~core.control_plane.swarm_manifest.SwarmAgentManifest` — template /
  agent_id / task_id consumed as context hints.
* Projection dicts from :mod:`core.routes.projection` — enriched additively
  via :func:`~.dispatch_summary.attach_dispatch_summary_to_projection`.

What this package does NOT do
------------------------------
- It does **not** replace or modify :class:`~galaxy_gateway.agent_bridge.AgentBridge`
  or :class:`~galaxy_gateway.agent_bridge.HandoffContract`.
- It does **not** create a new agent runtime or coordinator.
- It does **not** introduce a new transport layer.
- It does **not** break existing dispatch paths (all integrations are additive).
- Recovery governance is advisory; actual fallback logic remains in AgentBridge.

Public API
----------
AgentRole
    Stable enum of agent responsibility roles:
    ``planner``, ``executor``, ``bridge``, ``recovery``, ``observer``,
    ``local_assistant``, ``remote_specialist``, ``unassigned``.

AGENT_ROLE_PRECEDENCE
    Ordered list of :class:`AgentRole` values from most to least authoritative.

agent_role_description(role) → str
    Human-readable description for an :class:`AgentRole`.

ROLE_CAN_INITIATE_HANDOFF
    ``frozenset`` of roles that may initiate a handoff.

ROLE_CAN_RECEIVE_HANDOFF
    ``frozenset`` of roles that may receive a handoff.

HANDOFF_GRAPH
    Dict from :class:`AgentRole` to ``FrozenSet[AgentRole]`` of valid targets.

is_valid_handoff(source, target) → bool
    Return ``True`` when the (source → target) edge is in the graph.

can_role_initiate_handoff(role) → bool
    Return ``True`` when *role* has valid outgoing edges.

can_role_receive_handoff(role) → bool
    Return ``True`` when any edge in the graph points to *role*.

describe_handoff_edge(source, target) → str
    Return a human-readable description of a handoff edge.

OwnershipRecord
    Mutable ownership record for a single dispatch lifecycle.

OwnershipTransferResult
    Result of an :func:`apply_ownership_transfer` call.

apply_ownership_transfer(record, target, reason) → OwnershipTransferResult
    Attempt to transfer ownership in *record*; returns result without raising.

HandoffPolicy
    Serialisable policy governing handoff depth, ack, and recovery.

DEFAULT_HANDOFF_POLICY
    Conservative default policy.

RECOVERY_HANDOFF_POLICY
    Recovery-focused policy (low depth, best-effort ack).

OBSERVER_HANDOFF_POLICY
    Observer policy (no handoffs permitted).

get_policy_for_role(role) → HandoffPolicy
    Return the default :class:`HandoffPolicy` for *role*.

OwnershipSummary
    Compact, public-safe summary of an ownership lifecycle.

IDLE_OWNERSHIP_SUMMARY
    Pre-built idle sentinel.

build_ownership_summary(record, policy) → OwnershipSummary
    Build a summary from a record + policy pair.

attach_ownership_to_projection(dict, summary) → dict
    Attach ownership summary to a projection dict additively.

get_ownership_hints(summary) → dict
    Compact boolean/scalar hints.

make_ownership_summary(…) → OwnershipSummary
    One-call builder from scalar inputs.

DispatchSummary
    Compact governance annotation for a dispatch event.

IDLE_DISPATCH_SUMMARY
    Pre-built idle sentinel.

build_dispatch_summary(…) → DispatchSummary
    Build from roles and dispatch context.

resolve_dispatch_summary(…) → DispatchSummary
    Derive from string role names; graceful degradation.

attach_dispatch_summary_to_result(result, summary) → dict
    Enrich an existing dispatch result dict with governance metadata.

attach_dispatch_summary_to_handoff_result(result, …) → dict
    Specialised enrichment for AgentBridge handoff results.

attach_dispatch_summary_to_projection(dict, summary) → dict
    Attach dispatch summary to a projection dict additively.

See Also
--------
docs/AGENT_RESPONSIBILITY_AND_DISPATCH_GOVERNANCE.md — design document.
galaxy_gateway/agent_bridge.py — AgentBridge / HandoffContract (upstream).
core/command_router.py — dispatch_agent_remote (upstream).
core/control_plane/swarm_manifest.py — SwarmAgentManifest (upstream).
core/device_formation/ — PR-17 device-formation (sibling package).
"""

from __future__ import annotations

from .agent_role import (
    AgentRole,
    AGENT_ROLE_PRECEDENCE,
    agent_role_description,
    ROLE_CAN_INITIATE_HANDOFF,
    ROLE_CAN_RECEIVE_HANDOFF,
)
from .responsibility_graph import (
    HANDOFF_GRAPH,
    is_valid_handoff,
    OwnershipRecord,
    OwnershipTransferResult,
    apply_ownership_transfer,
    can_role_initiate_handoff,
    can_role_receive_handoff,
    describe_handoff_edge,
)
from .handoff_policy import (
    HandoffPolicy,
    DEFAULT_HANDOFF_POLICY,
    RECOVERY_HANDOFF_POLICY,
    OBSERVER_HANDOFF_POLICY,
    get_policy_for_role,
)
from .ownership_summary import (
    OwnershipSummary,
    IDLE_OWNERSHIP_SUMMARY,
    build_ownership_summary,
    attach_ownership_to_projection,
    get_ownership_hints,
    make_ownership_summary,
)
from .dispatch_summary import (
    DispatchSummary,
    IDLE_DISPATCH_SUMMARY,
    build_dispatch_summary,
    resolve_dispatch_summary,
    attach_dispatch_summary_to_result,
    attach_dispatch_summary_to_handoff_result,
    attach_dispatch_summary_to_projection,
)

__all__ = [
    # Agent roles
    "AgentRole",
    "AGENT_ROLE_PRECEDENCE",
    "agent_role_description",
    "ROLE_CAN_INITIATE_HANDOFF",
    "ROLE_CAN_RECEIVE_HANDOFF",
    # Responsibility graph
    "HANDOFF_GRAPH",
    "is_valid_handoff",
    "can_role_initiate_handoff",
    "can_role_receive_handoff",
    "describe_handoff_edge",
    # Ownership record
    "OwnershipRecord",
    "OwnershipTransferResult",
    "apply_ownership_transfer",
    # Handoff policy
    "HandoffPolicy",
    "DEFAULT_HANDOFF_POLICY",
    "RECOVERY_HANDOFF_POLICY",
    "OBSERVER_HANDOFF_POLICY",
    "get_policy_for_role",
    # Ownership summary
    "OwnershipSummary",
    "IDLE_OWNERSHIP_SUMMARY",
    "build_ownership_summary",
    "attach_ownership_to_projection",
    "get_ownership_hints",
    "make_ownership_summary",
    # Dispatch summary
    "DispatchSummary",
    "IDLE_DISPATCH_SUMMARY",
    "build_dispatch_summary",
    "resolve_dispatch_summary",
    "attach_dispatch_summary_to_result",
    "attach_dispatch_summary_to_handoff_result",
    "attach_dispatch_summary_to_projection",
]
