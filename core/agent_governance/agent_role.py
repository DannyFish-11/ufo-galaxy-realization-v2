#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.agent_governance.agent_role
==================================

PR-18 (V4) — Agent Responsibility Graph & Dispatch Governance

Defines the **agent role taxonomy** used across agent dispatch, runtime
handoff, and ownership governance.  Roles are aligned with the existing
dispatch infrastructure in :mod:`galaxy_gateway.agent_bridge`,
:mod:`core.command_router`, and :mod:`core.control_plane.swarm_manifest`.

Role Definitions
----------------
+-------------------+----------------------------------------------------------+
| Role              | Meaning                                                  |
+===================+==========================================================+
| PLANNER           | Decomposes goals into sub-tasks and dispatches agents.   |
|                   | Owns the initial dispatch ownership for a task tree.     |
+-------------------+----------------------------------------------------------+
| EXECUTOR          | Executes a specific task or sub-task.  Owns the outcome  |
|                   | of its assigned task slot.                               |
+-------------------+----------------------------------------------------------+
| BRIDGE            | Mediates runtime handoff between agents or devices       |
|                   | (maps to AgentBridge / HandoffContract in the gateway).  |
+-------------------+----------------------------------------------------------+
| RECOVERY          | Takes over ownership when the primary executor fails or  |
|                   | a handoff times out.  Responsible for fallback outcome.  |
+-------------------+----------------------------------------------------------+
| OBSERVER          | Monitors task progress without executing.  Receives      |
|                   | read-only projection of dispatch/ownership state.        |
+-------------------+----------------------------------------------------------+
| LOCAL_ASSISTANT   | Local-device assistant agent.  Executes on-device tasks. |
|                   | May escalate to REMOTE_SPECIALIST via handoff.           |
+-------------------+----------------------------------------------------------+
| REMOTE_SPECIALIST | Specialist agent on a remote device or runtime.          |
|                   | Accepts handoffs from LOCAL_ASSISTANT or BRIDGE.         |
+-------------------+----------------------------------------------------------+
| UNASSIGNED        | Role has not yet been determined.  Provisional state.    |
+-------------------+----------------------------------------------------------+

Relationship to existing dispatch paths
-----------------------------------------
These roles annotate — but do not replace — existing dispatch contracts:

* :class:`~galaxy_gateway.agent_bridge.HandoffContract` carries
  ``exec_mode`` / ``route_mode`` for transport semantics.
  :class:`AgentRole` adds *responsibility* semantics on top.
* :class:`~core.control_plane.swarm_manifest.SwarmAgentManifest` carries a
  ``template`` field for agent type hints.  :class:`AgentRole` formalises the
  governance taxonomy that ``template`` values can map to.
* :func:`~core.command_router.CommandRouter.dispatch_agent_remote` performs
  ``agent_deploy`` + ``agent_execute`` for physical devices.
  :class:`AgentRole` expresses *who owns the outcome* of that dispatch.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

__all__ = [
    "AgentRole",
    "AGENT_ROLE_PRECEDENCE",
    "agent_role_description",
    "ROLE_CAN_INITIATE_HANDOFF",
    "ROLE_CAN_RECEIVE_HANDOFF",
]


# ---------------------------------------------------------------------------
# Agent role enum
# ---------------------------------------------------------------------------


class AgentRole(str, Enum):
    """Taxonomy of agent responsibility roles within a dispatch/handoff lifecycle.

    String values are stable identifiers safe for serialisation, logging, and
    API responses.
    """

    PLANNER = "planner"
    """Decomposes goals and dispatches sub-tasks.  Initial ownership holder."""

    EXECUTOR = "executor"
    """Executes a specific task or sub-task.  Owns its assigned task slot."""

    BRIDGE = "bridge"
    """Mediates runtime handoff (maps to AgentBridge / HandoffContract)."""

    RECOVERY = "recovery"
    """Takes over when a primary executor fails or a handoff times out."""

    OBSERVER = "observer"
    """Monitors progress.  No execution responsibility."""

    LOCAL_ASSISTANT = "local_assistant"
    """Local-device assistant.  May escalate via handoff to REMOTE_SPECIALIST."""

    REMOTE_SPECIALIST = "remote_specialist"
    """Specialist on a remote device/runtime.  Accepts handoffs from bridge."""

    UNASSIGNED = "unassigned"
    """Role not yet determined.  Provisional state."""


# ---------------------------------------------------------------------------
# Role metadata
# ---------------------------------------------------------------------------

_ROLE_DESCRIPTIONS: Dict[str, str] = {
    AgentRole.PLANNER.value: (
        "Decomposes high-level goals into concrete sub-tasks and dispatches "
        "child agents.  Holds initial ownership of the overall task tree.  "
        "Ownership transfers to the EXECUTOR once the sub-task is dispatched "
        "and accepted."
    ),
    AgentRole.EXECUTOR.value: (
        "Executes a specific task or sub-task.  Owns the final outcome of its "
        "assigned execution slot.  Responsible for reporting success/failure "
        "back to the dispatcher.  May hand off to REMOTE_SPECIALIST via BRIDGE "
        "when local capability is insufficient."
    ),
    AgentRole.BRIDGE.value: (
        "Mediates runtime handoff between agents or across device boundaries.  "
        "Corresponds to the AgentBridge / HandoffContract path in the gateway.  "
        "Holds transient ownership during the handoff window; ownership "
        "transfers to the receiving agent on successful handoff or to RECOVERY "
        "on failure."
    ),
    AgentRole.RECOVERY.value: (
        "Activated when the primary executor fails or a handoff exceeds its "
        "timeout.  Inherits ownership from the failed executor or bridge and "
        "is responsible for producing a fallback outcome or escalating the "
        "failure.  Corresponds to the local_fallback path in AgentBridge."
    ),
    AgentRole.OBSERVER.value: (
        "Receives a read-only view of dispatch and ownership state.  Does not "
        "execute tasks or hold execution ownership.  Suitable for status "
        "boards, audit consumers, and monitoring agents."
    ),
    AgentRole.LOCAL_ASSISTANT.value: (
        "Local-device assistant agent that handles on-device tasks.  May "
        "escalate via a BRIDGE handoff to a REMOTE_SPECIALIST when the "
        "required capability is not available locally."
    ),
    AgentRole.REMOTE_SPECIALIST.value: (
        "Specialist agent running on a remote device or runtime endpoint.  "
        "Accepts handoffs from LOCAL_ASSISTANT or BRIDGE agents.  Takes "
        "ownership on successful handoff and is responsible for the remote "
        "execution outcome."
    ),
    AgentRole.UNASSIGNED.value: (
        "Role has not yet been determined.  Provisional state used when a "
        "dispatch or governance event arrives before role resolution is "
        "complete."
    ),
}

#: Precedence order from most authoritative to least.
#: Used when a single dispatch event is associated with multiple candidate
#: roles and a single representative role must be chosen.
AGENT_ROLE_PRECEDENCE: List[AgentRole] = [
    AgentRole.PLANNER,
    AgentRole.RECOVERY,
    AgentRole.EXECUTOR,
    AgentRole.BRIDGE,
    AgentRole.LOCAL_ASSISTANT,
    AgentRole.REMOTE_SPECIALIST,
    AgentRole.OBSERVER,
    AgentRole.UNASSIGNED,
]

#: Roles that are permitted to initiate a handoff (outgoing side).
ROLE_CAN_INITIATE_HANDOFF: frozenset = frozenset({
    AgentRole.PLANNER,
    AgentRole.EXECUTOR,
    AgentRole.LOCAL_ASSISTANT,
    AgentRole.BRIDGE,
})

#: Roles that are permitted to receive a handoff (incoming side).
ROLE_CAN_RECEIVE_HANDOFF: frozenset = frozenset({
    AgentRole.EXECUTOR,
    AgentRole.REMOTE_SPECIALIST,
    AgentRole.BRIDGE,
    AgentRole.RECOVERY,
})


def agent_role_description(role: AgentRole) -> str:
    """Return the human-readable description for *role*."""
    return _ROLE_DESCRIPTIONS.get(role.value, "Unknown agent role.")
