#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — SwarmCoordinator
=========================================

PR-8: Multi-Device Orchestration Layer
---------------------------------------
:class:`SwarmCoordinator` is the **multi-device orchestration layer** — a
higher-level coordination/planning component that operates *above* the unified
cross-device execution substrate.

Architectural position
~~~~~~~~~~~~~~~~~~~~~~
::

    ┌─────────────────────────────────────────────────────────────┐
    │  OpenClawd (decision core)                                  │
    │    └─ _delegate_multi_device_orchestration()                │
    │         │                                                   │
    │         ▼  (orchestration layer — selects & coordinates)   │
    │  SwarmCoordinator  ◄── this module                         │
    │    1. build_orchestration_plan() — device assignment        │
    │       decisions produced BEFORE any dispatch               │
    │    2. _dispatch_one() — delegates each manifest to          │
    │       ──────────────────────────────────────────────────── │
    │       CommandRouter.dispatch_agent_remote()                 │
    │         │  (substrate — transport/execution)               │
    │         └─ route_envelope()  ← single substrate root       │
    └─────────────────────────────────────────────────────────────┘

Key responsibilities of the orchestration layer (this module)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* **Select** target devices for each agent/member (using
  :class:`~core.control_plane.smart_scheduler.DeviceScoringEngine`).
* **Record** device-assignment decisions as first-class
  :class:`~core.orchestration.multi_device_plan.OrchestrationPlan` objects
  *before* any dispatch call reaches the substrate.
* **Coordinate** parallel dispatch of multiple members concurrently.
* **Aggregate** raw substrate results into a synthesised
  :class:`~core.agent_team.TeamResult`.

What the orchestration layer is NOT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* It does **not** handle transport routing or bus-level substrate logic.
* It does **not** implement the ``route_envelope`` protocol.
* It is **not** the same thing as the substrate; it merely *delegates to* the
  substrate (:class:`~core.command_router.CommandRouter`) once its planning
  decisions are made.

Implements **Control Plane Phase 3**: distributed Agent Swarm / Team dispatch.

The :class:`SwarmCoordinator` bridges the logical :class:`~core.agent_team.AgentTeam`
execution model with the physical device layer exposed by
:class:`~core.command_router.CommandRouter`.  For each team member it:

1. Builds an :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
   capturing device-assignment decisions (orchestration layer).
2. Serialises each member's execution context into a :class:`SwarmAgentManifest`.
3. Uses :class:`~core.control_plane.smart_scheduler.DeviceScoringEngine` to
   select the most suitable target device when one is not already specified.
4. Dispatches the manifest via ``CommandRouter.dispatch_agent_remote`` so the
   existing ``agent_execute`` gateway protocol is reused end-to-end (substrate).
5. Emits structured audit events (``AGENT_DISPATCHED``, ``AGENT_EXECUTED``,
   ``AGENT_RESULT_RECEIVED``) into the global :class:`~core.control_plane.audit_ledger.AuditLedger`.
6. Aggregates per-member results into a :class:`~core.agent_team.TeamResult`.

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

        PR-8: This method represents the orchestration layer's primary
        coordination entry point.  It:

        1. **Plans** — builds an
           :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
           (device-assignment decisions) *before* any substrate dispatch.
        2. **Delegates** — passes each manifest to the substrate
           (:meth:`_dispatch_one` → ``CommandRouter.dispatch_agent_remote``).
        3. **Aggregates** — collects raw substrate results and synthesises them.

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
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            build_orchestration_plan,
        )

        effective_timeout = timeout if timeout is not None else self.default_timeout
        root_task_id = task_id or f"swarm_{uuid.uuid4().hex[:12]}"
        root_trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"

        # ── ORCHESTRATION LAYER: Build manifests and orchestration plan ──────
        # All device-assignment decisions are made here (orchestration) BEFORE
        # any dispatch call reaches the substrate (CommandRouter).
        manifests: List[SwarmAgentManifest] = []
        orch_decisions: List[OrchestrationDecision] = []
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
            resolved_mode: Optional[str] = None
            device_score: float = 0.0
            assignment_source: str = ""
            assigned_device_id: Optional[str] = None
            if device_candidates:
                scoring_engine = self._get_scoring_engine()
                best = scoring_engine.select_best_device(
                    device_candidates,
                    manifest.required_capabilities or None,
                )
                if best:
                    assigned_device_id = best.device_id
                    manifest.target_device_id = assigned_device_id
                    device_score = best.total
                    assignment_source = "scoring_engine"

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
                        resolved_mode = _mode_result.mode
                        logger.info(
                            "SwarmCoordinator[orch]: member=%s assigned device=%s score=%.3f mode=%s (source=%s)",
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
                            "SwarmCoordinator[orch]: member=%s assigned device=%s score=%.3f",
                            member.agent_name if hasattr(member, "agent_name") else member.agent_id,
                            best.device_id,
                            best.total,
                        )
                else:
                    logger.warning(
                        "SwarmCoordinator[orch]: no eligible device for member=%s",
                        getattr(member, "agent_name", member.agent_id),
                    )

            # Record orchestration decision (before substrate dispatch)
            orch_decisions.append(OrchestrationDecision(
                agent_id=getattr(member, "agent_id", str(idx)),
                agent_name=getattr(member, "agent_name", ""),
                target_device_id=assigned_device_id,
                score=device_score,
                resolved_execution_mode=resolved_mode,
                assignment_source=assignment_source,
                manifest_id=getattr(manifest, "manifest_id", ""),
            ))
            manifests.append(manifest)

        # Build the orchestration plan — captures all planning decisions
        # as a first-class object BEFORE the substrate is invoked.
        orch_plan = build_orchestration_plan(
            task=task,
            decisions=orch_decisions,
            session_id=session_id,
            trace_id=root_trace_id,
            task_id=root_task_id,
        )
        logger.debug(
            "SwarmCoordinator[orch]: plan built %s",
            orch_plan.to_summary_dict(),
        )

        # ── SUBSTRATE DELEGATION: Dispatch all members concurrently ──────────
        # From this point we hand control to the substrate (CommandRouter).
        # The orchestration layer does not perform any routing itself.
        t0 = time.monotonic()
        dispatch_coros = [self._dispatch_one(manifest) for manifest in manifests]
        raw_results = await asyncio.gather(*dispatch_coros, return_exceptions=True)

        # ── ORCHESTRATION LAYER: Aggregate results ───────────────────────────
        total_ms = (time.monotonic() - t0) * 1000
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
    # Orchestration plan helper (PR-8)
    # ------------------------------------------------------------------

    def build_orchestration_plan(
        self,
        members: List[Any],
        task: str,
        device_candidates: Optional[List[Any]] = None,
        *,
        session_id: str = "",
        trace_id: str = "",
        task_id: str = "",
        required_capabilities: Optional[List[str]] = None,
    ):
        """Build an :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
        for a set of team members *without* dispatching to the substrate.

        This is a **planning-only** operation: it produces the set of
        device-assignment decisions that the orchestration layer would make,
        as a first-class :class:`~core.orchestration.multi_device_plan.OrchestrationPlan`
        object.

        Callers can inspect the plan before committing to substrate dispatch,
        which makes the orchestration-above-substrate boundary observable and
        testable.

        Parameters
        ----------
        members:
            List of ``core.agent_team.TeamMember`` instances.
        task:
            Task description.
        device_candidates:
            Candidate devices for scoring.
        session_id / trace_id / task_id:
            Correlation identifiers.
        required_capabilities:
            Capability filter for device selection.

        Returns
        -------
        core.orchestration.multi_device_plan.OrchestrationPlan
        """
        from core.orchestration.multi_device_plan import OrchestrationDecision, build_orchestration_plan

        root_task_id = task_id or f"swarm_{uuid.uuid4().hex[:12]}"
        root_trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"

        decisions: List[OrchestrationDecision] = []
        for idx, member in enumerate(members):
            agent_id = getattr(member, "agent_id", str(idx))
            agent_name = getattr(member, "agent_name", "")
            target_device_id = None
            device_score = 0.0
            resolved_mode = None
            assignment_source = ""

            if device_candidates:
                scoring_engine = self._get_scoring_engine()
                best = scoring_engine.select_best_device(
                    device_candidates,
                    list(required_capabilities) if required_capabilities else None,
                )
                if best:
                    target_device_id = best.device_id
                    device_score = best.total
                    assignment_source = "scoring_engine"
                    # Try to resolve execution mode (non-fatal)
                    try:
                        from core.device_execution_profile import build_profile_from_device_info
                        from core.remote_execution_mode_resolver import resolve_mode
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
                        resolved_mode = _mode_result.mode
                    except Exception:
                        pass

            decisions.append(OrchestrationDecision(
                agent_id=agent_id,
                agent_name=agent_name,
                target_device_id=target_device_id,
                score=device_score,
                resolved_execution_mode=resolved_mode,
                assignment_source=assignment_source,
            ))

        return build_orchestration_plan(
            task=task,
            decisions=decisions,
            session_id=session_id,
            trace_id=root_trace_id,
            task_id=root_task_id,
        )

    def build_execution_plan_for_orchestration(
        self,
        members: List[Any],
        task: str,
        device_candidates: Optional[List[Any]] = None,
        *,
        session_id: str = "",
        trace_id: str = "",
        task_id: str = "",
        required_capabilities: Optional[List[str]] = None,
    ):
        """PR-11: Build a canonical :class:`~core.schemas.execution_plan.ExecutionPlan`
        for a multi-device orchestration intent.

        This is a **planning-only** wrapper that:

        1. Calls :meth:`build_orchestration_plan` to get the per-member
           device-assignment decisions.
        2. Converts those decisions into a first-class
           :class:`~core.schemas.execution_plan.ExecutionPlan` using
           :func:`~core.schemas.execution_plan.plan_from_orchestration_decisions`.

        The returned plan makes the orchestration intent inspectable before
        any substrate dispatch occurs.  Existing dispatch paths are unaffected.

        Parameters
        ----------
        members / task / device_candidates / session_id / trace_id / task_id /
        required_capabilities:
            Same as :meth:`build_orchestration_plan`.

        Returns
        -------
        core.schemas.execution_plan.ExecutionPlan or None
            ``None`` when the execution plan schema is unavailable.
        """
        try:
            from core.schemas.execution_plan import plan_from_orchestration_decisions

            orch_plan = self.build_orchestration_plan(
                members=members,
                task=task,
                device_candidates=device_candidates,
                session_id=session_id,
                trace_id=trace_id,
                task_id=task_id,
                required_capabilities=required_capabilities,
            )
            decisions_raw = [
                {
                    "agent_id": d.agent_id,
                    "target_device_id": d.target_device_id,
                    "resolved_execution_mode": d.resolved_execution_mode,
                }
                for d in orch_plan.decisions
            ]
            return plan_from_orchestration_decisions(
                decisions=decisions_raw,
                task=task,
                trace_id=trace_id or orch_plan.trace_id,
                session_id=session_id or orch_plan.session_id,
                orchestration_plan_id=orch_plan.plan_id,
            )
        except Exception as _e:
            logger.debug(
                "SwarmCoordinator.build_execution_plan_for_orchestration failed: %s", _e
            )
            return None

    # ------------------------------------------------------------------
    # PR-6: Canonical device candidate resolution
    # ------------------------------------------------------------------

    @staticmethod
    def device_candidates_from_canonical(
        canonical_devices: List[Any],
        router_liveness: Optional[Dict[str, bool]] = None,
        required_capabilities: Optional[List[str]] = None,
        latency_map: Optional[Dict[str, float]] = None,
        load_map: Optional[Dict[str, float]] = None,
    ) -> List[Any]:
        """Build a ``DeviceScoreInput`` list from canonical device projections.

        PR-6: This is the canonical → scoring-engine bridge.  Callers that
        have a list of ``RegisteredRuntimeDevice`` projections should use this
        helper to produce device candidates for :meth:`dispatch_team` or
        :meth:`build_orchestration_plan`, rather than building
        ``DeviceScoreInput`` objects from private device tables.

        Only devices assessed as ``orchestration_eligible`` are included.
        If *required_capabilities* is provided, devices missing any required
        capability are filtered out before scoring.

        Parameters
        ----------
        canonical_devices:
            List of ``RegisteredRuntimeDevice`` canonical projections.
            These are the **base truth source** for device identity.
        router_liveness:
            Optional ``device_id → bool`` routing-feasibility enrichment.
            Used by :func:`~core.device_selection.assess_device_participation`
            to determine routability; does not replace canonical identity.
        required_capabilities:
            Optional list of capability strings used for capability-filter
            pre-screening.  Passed through to
            :func:`~core.device_selection.select_orchestration_candidates`.
        latency_map:
            Optional ``device_id → ping_latency_ms`` override for scoring.
        load_map:
            Optional ``device_id → load_pct`` override for scoring.

        Returns
        -------
        list of DeviceScoreInput
            Ready for use with :meth:`dispatch_team` or
            :meth:`build_orchestration_plan`.  Returns ``[]`` on error
            (never raises).
        """
        try:
            from core.device_selection import (
                select_orchestration_candidates,
                device_score_input_from_canonical,
            )

            entries = select_orchestration_candidates(
                canonical_devices,
                router_liveness=router_liveness,
                required_capabilities=required_capabilities,
            )

            score_inputs = []
            for entry in entries:
                device_id = entry.device_id
                score_input = device_score_input_from_canonical(
                    entry,
                    ping_latency_ms=(latency_map or {}).get(device_id, 0.0),
                    load_pct=(load_map or {}).get(device_id, 0.0),
                )
                if score_input is not None:
                    score_inputs.append(score_input)

            return score_inputs
        except Exception as exc:
            logger.warning(
                "SwarmCoordinator.device_candidates_from_canonical: error: %s", exc
            )
            return []


    async def _dispatch_one(self, manifest) -> Dict[str, Any]:
        """Delegate a single :class:`SwarmAgentManifest` to the substrate.

        PR-8: This is the **substrate delegation boundary** within the
        orchestration layer.  The orchestration layer (SwarmCoordinator) has
        already made its planning decisions (device assignment, mode resolution)
        before calling this method.  From here, control passes to the substrate:
        ``CommandRouter.dispatch_agent_remote`` → ``route_envelope``.

        Emits ``AGENT_DISPATCHED`` before substrate delegation and either
        ``AGENT_RESULT_RECEIVED`` on success or ``TASK_FAILED`` on error.

        Parameters
        ----------
        manifest:
            The :class:`SwarmAgentManifest` to dispatch to the substrate.

        Returns
        -------
        dict
            The raw result dict from the substrate (``dispatch_agent_remote``).
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
            return {"success": False, "error": "no_target_device", "agent_id": manifest.agent_id,
                    "failure_domain": "remote_device_unavailable"}

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
            return {"success": False, "error": "command_router_unavailable",
                    "failure_domain": "substrate_dispatch_failure"}

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
            return {"success": False, "error": str(exc), "agent_id": manifest.agent_id,
                    "failure_domain": "gateway_transport_failure"}

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
