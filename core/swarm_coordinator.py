#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — SwarmCoordinator
=========================================

Implements **Control Plane Phase 3**: distributed Agent Swarm / Team dispatch.

The :class:`SwarmCoordinator` bridges the logical :class:`~core.agent_team.AgentTeam`
execution model with the physical device layer exposed by
:class:`~core.command_router.CommandRouter`.  For each team member it:

1. Serialises the member's execution context into a :class:`SwarmAgentManifest`.
2. Uses :class:`~core.control_plane.smart_scheduler.DeviceScoringEngine` to
   select the most suitable target device when one is not already specified.
3. Dispatches the manifest via ``CommandRouter.dispatch_agent_remote`` so the
   existing ``agent_execute`` gateway protocol is reused end-to-end.
4. Emits structured audit events (``AGENT_DISPATCHED``, ``AGENT_EXECUTED``,
   ``AGENT_RESULT_RECEIVED``) into the global :class:`~core.control_plane.audit_ledger.AuditLedger`.
5. Aggregates per-member results into a :class:`~core.agent_team.TeamResult`.

Usage
-----
    import asyncio
    from core.swarm_coordinator import SwarmCoordinator
    from core.agent_team import TeamMember
    from core.control_plane.smart_scheduler import DeviceScoreInput, SandboxLevel

    coordinator = SwarmCoordinator()

    members = [
        TeamMember(agent_id="a1", agent_name="Analyst", provider="openai",
                   model="gpt-4", role_in_team="analyst", template="data_analyst"),
    ]
    device_candidates = [
        DeviceScoreInput(device_id="win_host_01", ping_latency_ms=20.0,
                         load_pct=10.0, capabilities=["screen", "keyboard"]),
    ]

    result = asyncio.run(coordinator.dispatch_team(
        members=members,
        task="Analyse Q3 sales data",
        session_id="sess_abc",
        trace_id="trace_xyz",
        task_id="task_001",
        device_candidates=device_candidates,
    ))
    print(result.synthesized)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SwarmCoordinator")


class SwarmCoordinator:
    """Dispatch Team/Swarm members to remote devices and aggregate results.

    Parameters
    ----------
    command_router:
        A :class:`~core.command_router.CommandRouter` instance.  When ``None``,
        the process-level singleton returned by
        ``core.command_router.get_command_router`` is used lazily on first
        dispatch.
    scoring_engine:
        A :class:`~core.control_plane.smart_scheduler.DeviceScoringEngine`
        instance.  Defaults to the process-level singleton.
    audit_ledger:
        A :class:`~core.control_plane.audit_ledger.AuditLedger` instance.
        Defaults to the process-level singleton.
    default_timeout:
        Default per-member dispatch timeout in seconds.
    """

    def __init__(
        self,
        command_router=None,
        scoring_engine=None,
        audit_ledger=None,
        default_timeout: float = 60.0,
    ) -> None:
        self._router = command_router
        self._scoring_engine = scoring_engine
        self._ledger = audit_ledger
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------
    # Lazy singleton accessors
    # ------------------------------------------------------------------

    def _get_router(self):
        if self._router is not None:
            return self._router
        try:
            from core.command_router import get_command_router
            return get_command_router()
        except Exception as exc:
            logger.warning("CommandRouter unavailable: %s", exc)
            return None

    def _get_scoring_engine(self):
        if self._scoring_engine is not None:
            return self._scoring_engine
        from core.control_plane._globals import get_scoring_engine
        return get_scoring_engine()

    def _get_ledger(self):
        if self._ledger is not None:
            return self._ledger
        from core.control_plane._globals import get_audit_ledger
        return get_audit_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch_team(
        self,
        members: List[Any],  # List[core.agent_team.TeamMember]
        task: str,
        *,
        session_id: str = "",
        trace_id: str = "",
        task_id: str = "",
        device_candidates: Optional[List[Any]] = None,  # List[DeviceScoreInput]
        system_prompt_template: str = "",
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        memory_snapshot: Optional[Dict[str, Any]] = None,
        required_capabilities: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ):
        """Dispatch all team members as remote ``agent_execute`` commands.

        Each member is serialised into a :class:`SwarmAgentManifest`.  If
        *device_candidates* is provided the :class:`DeviceScoringEngine`
        selects the best device for each member; otherwise
        ``manifest.target_device_id`` remains ``None`` and the dispatch is
        skipped (the member result will carry ``success=False``).

        Parameters
        ----------
        members:
            List of ``core.agent_team.TeamMember`` instances.
        task:
            Main task description shared across the swarm.
        session_id / trace_id / task_id:
            Correlation identifiers propagated to every manifest.
        device_candidates:
            Observable metrics for candidate devices.  Passed to the
            :class:`DeviceScoringEngine` for automatic device assignment.
        system_prompt_template:
            Jinja-free template string for the system prompt.  If empty,
            :meth:`SwarmAgentManifest.from_team_member` generates a default.
        tool_schemas:
            Tool declarations shared across all members.
        memory_snapshot:
            Shared memory snapshot seeded into every member's context.
        required_capabilities:
            Capability constraints forwarded to :meth:`DeviceScoringEngine.select_best_device`.
        timeout:
            Per-member dispatch timeout (defaults to :attr:`default_timeout`).

        Returns
        -------
        core.agent_team.TeamResult
        """
        from core.control_plane.swarm_manifest import SwarmAgentManifest
        from core.agent_team import MemberResult, TeamResult

        effective_timeout = timeout if timeout is not None else self.default_timeout
        root_task_id = task_id or f"swarm_{uuid.uuid4().hex[:12]}"
        root_trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"

        # Build manifests
        manifests: List[SwarmAgentManifest] = []
        for idx, member in enumerate(members):
            member_task_id = f"{root_task_id}_{getattr(member, 'agent_id', str(idx))}"
            prompt = system_prompt_template or ""
            manifest = SwarmAgentManifest.from_team_member(
                member,
                task=task,
                session_id=session_id,
                trace_id=root_trace_id,
                task_id=member_task_id,
                system_prompt=prompt,
                tool_schemas=list(tool_schemas or []),
                memory_snapshot=dict(memory_snapshot or {}),
                required_capabilities=list(required_capabilities or []),
                timeout_seconds=effective_timeout,
            )

            # Assign device
            # PR-6: use execution profile + RemoteExecutionModeResolver when available
            # to prefer devices that support the required execution mode.
            if device_candidates:
                scoring_engine = self._get_scoring_engine()
                best = scoring_engine.select_best_device(
                    device_candidates,
                    manifest.required_capabilities or None,
                )
                if best:
                    manifest.target_device_id = best.device_id

                    # Resolve and log the execution mode for the selected device.
                    try:
                        from core.device_execution_profile import build_profile_from_device_info
                        from core.remote_execution_mode_resolver import resolve_mode

                        # Prefer the pre-attached execution_profile when available.
                        _candidate_input = next(
                            (c for c in device_candidates if c.device_id == best.device_id),
                            None,
                        )
                        _exec_profile = (
                            getattr(_candidate_input, "execution_profile", None)
                            or build_profile_from_device_info(
                                {"capabilities": list(getattr(_candidate_input, "capabilities", []))},
                                device_id=best.device_id,
                            )
                        )
                        _mode_result = resolve_mode(profile=_exec_profile, task_intent="agent_execute")
                        logger.info(
                            "SwarmCoordinator: member=%s assigned device=%s score=%.3f mode=%s (source=%s)",
                            member.agent_name if hasattr(member, "agent_name") else member.agent_id,
                            best.device_id,
                            best.total,
                            _mode_result.mode,
                            _mode_result.resolution_source,
                        )
                        # Store resolved mode in manifest metadata for downstream use.
                        if hasattr(manifest, "metadata") and isinstance(manifest.metadata, dict):
                            manifest.metadata["resolved_execution_mode"] = _mode_result.mode
                            manifest.metadata["execution_mode_source"] = _mode_result.resolution_source
                    except Exception as _pr6_err:
                        logger.debug(
                            "SwarmCoordinator: PR-6 mode resolution non-fatal: %s", _pr6_err
                        )
                        logger.info(
                            "SwarmCoordinator: member=%s assigned device=%s score=%.3f",
                            member.agent_name if hasattr(member, "agent_name") else member.agent_id,
                            best.device_id,
                            best.total,
                        )
                else:
                    logger.warning(
                        "SwarmCoordinator: no eligible device for member=%s",
                        getattr(member, "agent_name", member.agent_id),
                    )

            manifests.append(manifest)

        # Dispatch all members concurrently
        t0 = time.monotonic()
        dispatch_coros = [self._dispatch_one(manifest) for manifest in manifests]
        raw_results = await asyncio.gather(*dispatch_coros, return_exceptions=True)

        # Aggregate
        member_results: List[MemberResult] = []
        for member, result in zip(members, raw_results):
            if isinstance(result, Exception):
                member_results.append(MemberResult(
                    member=member,
                    result="",
                    success=False,
                    error=str(result),
                ))
            else:
                member_results.append(MemberResult(
                    member=member,
                    result=result.get("output", result.get("result", "")),
                    latency_ms=float(result.get("latency_ms", 0.0)),
                    success=result.get("success", True),
                    error=result.get("error") if not result.get("success", True) else None,
                ))

        total_ms = (time.monotonic() - t0) * 1000
        synthesized = self._synthesize(member_results)

        return TeamResult(
            team_id=root_task_id,
            strategy="swarm_remote",
            task=task,
            member_results=member_results,
            synthesized=synthesized,
            total_latency_ms=total_ms,
            total_tokens=0,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch_one(self, manifest) -> Dict[str, Any]:
        """Dispatch a single :class:`SwarmAgentManifest` via CommandRouter.

        Emits ``AGENT_DISPATCHED`` before dispatch and either
        ``AGENT_RESULT_RECEIVED`` on success or ``TASK_FAILED`` on error.

        Parameters
        ----------
        manifest:
            The :class:`SwarmAgentManifest` to dispatch.

        Returns
        -------
        dict
            The raw result dict from ``dispatch_agent_remote``.
        """
        from core.control_plane.audit_ledger import EventType, Severity

        ledger = self._get_ledger()

        device_id = manifest.target_device_id
        if not device_id:
            logger.warning(
                "SwarmCoordinator: skipping agent_id=%s — no target device assigned",
                manifest.agent_id,
            )
            ledger.append(
                EventType.TASK_FAILED,
                severity=Severity.WARNING,
                source="swarm_coordinator",
                message=f"No target device for agent {manifest.agent_id}",
                agent_id=manifest.agent_id,
                trace_id=manifest.trace_id,
                task_id=manifest.task_id,
                session_id=manifest.session_id,
                payload={"manifest_id": manifest.manifest_id},
            )
            return {"success": False, "error": "no_target_device", "agent_id": manifest.agent_id}

        # Emit AGENT_DISPATCHED
        dispatch_event_id = ledger.append(
            EventType.AGENT_DISPATCHED,
            source="swarm_coordinator",
            message=f"Dispatching agent {manifest.agent_id!r} to device {device_id!r}",
            agent_id=manifest.agent_id,
            device_id=device_id,
            trace_id=manifest.trace_id,
            task_id=manifest.task_id,
            session_id=manifest.session_id,
            payload={
                "manifest_id": manifest.manifest_id,
                "template": manifest.template,
                "task": (manifest.subtask or manifest.task)[:200],
                "member_name": manifest.member_name,
            },
        )

        router = self._get_router()
        if router is None:
            ledger.append(
                EventType.TASK_FAILED,
                severity=Severity.ERROR,
                source="swarm_coordinator",
                message="CommandRouter unavailable",
                agent_id=manifest.agent_id,
                trace_id=manifest.trace_id,
                task_id=manifest.task_id,
                session_id=manifest.session_id,
                parent_ids=[dispatch_event_id],
            )
            return {"success": False, "error": "command_router_unavailable"}

        try:
            t_dispatch = time.monotonic()
            result = await router.dispatch_agent_remote(
                device_id=device_id,
                agent_id=manifest.agent_id,
                agent_template=manifest.template,
                task=manifest.subtask if manifest.subtask else manifest.task,
                session_id=manifest.session_id,
                trace_id=manifest.trace_id,
                task_id=manifest.task_id,
                context={
                    "system_prompt": manifest.system_prompt,
                    "tool_schemas": manifest.tool_schemas,
                    "memory_snapshot": manifest.memory_snapshot,
                    "manifest_id": manifest.manifest_id,
                    "member_name": manifest.member_name,
                },
                timeout=manifest.timeout_seconds,
            )
            latency_ms = (time.monotonic() - t_dispatch) * 1000

            # Emit AGENT_EXECUTED (device acknowledged execution)
            ledger.append(
                EventType.AGENT_EXECUTED,
                source="swarm_coordinator",
                message=f"Agent {manifest.agent_id!r} executed on {device_id!r}",
                agent_id=manifest.agent_id,
                device_id=device_id,
                trace_id=manifest.trace_id,
                task_id=manifest.task_id,
                session_id=manifest.session_id,
                parent_ids=[dispatch_event_id],
                payload={
                    "manifest_id": manifest.manifest_id,
                    "latency_ms": round(latency_ms, 1),
                    "success": result.get("success", True),
                },
            )

            # Emit AGENT_RESULT_RECEIVED
            ledger.append(
                EventType.AGENT_RESULT_RECEIVED,
                source="swarm_coordinator",
                message=f"Result received from {device_id!r} for agent {manifest.agent_id!r}",
                agent_id=manifest.agent_id,
                device_id=device_id,
                trace_id=manifest.trace_id,
                task_id=manifest.task_id,
                session_id=manifest.session_id,
                parent_ids=[dispatch_event_id],
                payload={
                    "manifest_id": manifest.manifest_id,
                    "success": result.get("success", True),
                    "output_preview": str(result.get("output", ""))[:200],
                },
            )

            result.setdefault("latency_ms", round(latency_ms, 1))
            return result

        except Exception as exc:
            logger.error(
                "SwarmCoordinator: dispatch failed agent_id=%s device=%s error=%s",
                manifest.agent_id, device_id, exc,
            )
            ledger.append(
                EventType.TASK_FAILED,
                severity=Severity.ERROR,
                source="swarm_coordinator",
                message=f"Dispatch failed: {exc}",
                agent_id=manifest.agent_id,
                device_id=device_id,
                trace_id=manifest.trace_id,
                task_id=manifest.task_id,
                session_id=manifest.session_id,
                parent_ids=[dispatch_event_id],
                payload={"error": str(exc), "manifest_id": manifest.manifest_id},
            )
            return {"success": False, "error": str(exc), "agent_id": manifest.agent_id}

    @staticmethod
    def _synthesize(member_results: List[Any]) -> str:
        """Produce a simple text synthesis of all member results.

        In Phase 3 this is a lightweight concatenation.  The full LLM-based
        synthesis (Phase 2 / :meth:`AgentTeam._synthesize_results`) can be
        triggered by passing the result to an :class:`AgentTeam` instance.
        """
        successful = [
            mr for mr in member_results
            if getattr(mr, "success", True) and getattr(mr, "result", "")
        ]
        if not successful:
            return "All remote members failed to execute."
        if len(successful) == 1:
            return successful[0].result
        parts = []
        for mr in successful:
            name = getattr(getattr(mr, "member", None), "agent_name", "agent")
            parts.append(f"[{name}]\n{mr.result}")
        return "\n\n".join(parts)
