#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — SwarmAgentManifest
==========================================

Pydantic model that captures everything a remote device needs to execute a
single swarm-member Agent autonomously.  Designed for JSON serialisation so
it can be carried inside a standard ``agent_execute`` CommandRouter payload.

Key design decisions
---------------------
* **Pydantic v2** — all fields are fully typed and validated; the model can
  be serialised to/from JSON with ``model_dump(mode="json")`` / ``model_validate``.
* **State-only** — no socket handles, no live objects.  Only plain Python
  types (str, dict, list) so the manifest is safely picklable and
  JSON-encodable across the wire.
* **Backward compatible** — existing ``agent_execute`` payloads (PR155) are a
  strict subset; devices that only understand the PR155 format will still work.

Usage
-----
    from core.control_plane.swarm_manifest import SwarmAgentManifest

    manifest = SwarmAgentManifest(
        agent_id="agent_abc",
        template="research",
        system_prompt="You are a research agent.",
        task="Summarise Q3 sales data",
        session_id="sess_xyz",
        trace_id="trace_abc",
        task_id="task_001",
    )

    payload = manifest.to_agent_execute_payload()
    json_str = manifest.model_dump_json()
    restored = SwarmAgentManifest.model_validate_json(json_str)
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SwarmAgentManifest(BaseModel):
    """Serialisable manifest for a single swarm-member Agent dispatched remotely.

    Fields
    ------
    manifest_id
        Globally unique identifier for this manifest instance.
    agent_id
        Identifier of the logical agent (preserved in all result messages).
    template
        Agent role / template name (``"research"``, ``"analyst"``, etc.).
    system_prompt
        Full system prompt injected into the remote agent's context.  May be
        empty when the device supplies its own default prompt.
    tool_schemas
        List of JSON-serialisable tool-declaration dicts (OpenAI function-call
        format).  The remote runtime uses these to decide which local tools to
        expose to the agent.
    memory_snapshot
        Key/value snapshot of the agent's memory at dispatch time.  Can be
        used to seed the remote context without a full state transfer.
    task
        Main task instruction for the swarm execution.
    subtask
        Optional specialised sub-instruction assigned to this specific member
        (SPECIALIZED / SWARM strategies).  When set, the remote agent executes
        ``subtask`` instead of ``task``.
    session_id
        Session identifier shared across all members of the same swarm run.
    trace_id
        Distributed trace identifier for end-to-end audit correlation.
    task_id
        Unique task identifier for this member's execution slot.
    target_device_id
        Device ID selected by the :class:`SwarmCoordinator`.  ``None`` means
        the coordinator has not yet assigned a device.
    required_capabilities
        Capabilities that the target device must provide (used by
        :class:`DeviceScoringEngine` for eligibility checks).
    timeout_seconds
        Maximum seconds the remote agent is allowed to run before the
        coordinator treats the dispatch as timed-out.
    member_name
        Human-readable name of the team member (for logging / audit).
    """

    manifest_id: str = Field(
        default_factory=lambda: f"swm_{uuid.uuid4().hex}",
        description="Globally unique manifest identifier.",
    )
    agent_id: str = Field(..., description="Unique agent identifier.")
    template: str = Field(
        default="research",
        description="Agent template / role name.",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt for the remote agent.",
    )
    tool_schemas: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Tool declarations in OpenAI function-call format.",
    )
    memory_snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Serialised memory snapshot to seed remote context.",
    )

    # Task fields
    task: str = Field(default="", description="Main task instruction.")
    subtask: Optional[str] = Field(
        None,
        description="Specialised sub-instruction for this member (overrides task when set).",
    )

    # Correlation / tracing
    session_id: str = Field(default="", description="Session identifier.")
    trace_id: str = Field(default="", description="Distributed trace ID.")
    task_id: str = Field(default="", description="Task slot identifier.")

    # Routing
    target_device_id: Optional[str] = Field(
        None,
        description="Device selected by SwarmCoordinator; None = unassigned.",
    )
    required_capabilities: List[str] = Field(
        default_factory=list,
        description="Capabilities the target device must support.",
    )
    timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="Execution timeout in seconds.",
    )

    # Metadata
    member_name: str = Field(
        default="",
        description="Human-readable team-member name (for logging).",
    )

    model_config = {"frozen": False}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_agent_execute_payload(self) -> Dict[str, Any]:
        """Convert to an ``agent_execute`` command payload dict.

        The returned dict is compatible with the existing PR155
        ``dispatch_agent_remote`` signature and carries the extra manifest
        fields inside the ``context`` sub-key so legacy device handlers
        continue to work without modification.

        Returns
        -------
        dict
            Ready to pass as ``payload`` / ``params`` of an
            ``agent_execute`` command.
        """
        return {
            "agent_id": self.agent_id,
            "agent_template": self.template,
            "task": self.subtask if self.subtask else self.task,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "context": {
                "system_prompt": self.system_prompt,
                "tool_schemas": self.tool_schemas,
                "memory_snapshot": self.memory_snapshot,
                "manifest_id": self.manifest_id,
                "member_name": self.member_name,
            },
        }

    @classmethod
    def from_team_member(
        cls,
        member,  # core.agent_team.TeamMember
        *,
        task: str,
        session_id: str = "",
        trace_id: str = "",
        task_id: str = "",
        subtask: Optional[str] = None,
        system_prompt: str = "",
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        memory_snapshot: Optional[Dict[str, Any]] = None,
        required_capabilities: Optional[List[str]] = None,
        timeout_seconds: float = 60.0,
    ) -> "SwarmAgentManifest":
        """Build a manifest from a :class:`~core.agent_team.TeamMember`.

        Convenience factory used by :class:`~core.swarm_coordinator.SwarmCoordinator`
        to serialise each member before dispatching.

        Parameters
        ----------
        member:
            A ``core.agent_team.TeamMember`` dataclass instance.
        task:
            Main swarm task description.
        subtask:
            Member-specific sub-instruction.
        **kwargs:
            Forwarded directly to the manifest constructor.
        """
        return cls(
            agent_id=member.agent_id,
            template=member.template or "research",
            system_prompt=system_prompt or (
                f"You are {member.agent_name}, a specialised {member.role_in_team} agent. "
                f"Execute your assigned task carefully and return a structured result."
            ),
            tool_schemas=tool_schemas or [],
            memory_snapshot=memory_snapshot or {},
            task=task,
            subtask=subtask,
            session_id=session_id,
            trace_id=trace_id,
            task_id=task_id,
            required_capabilities=required_capabilities or [],
            timeout_seconds=timeout_seconds,
            member_name=member.agent_name,
        )
