#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — Swarm Auto-Scaler
==========================================

Implements dynamic scale-up / scale-down of Swarm worker agents based on
task complexity and runtime load.  The scaler integrates with the existing
``AgentFactory`` / ``AgentTeam`` / ``TeamManager`` machinery and emits
audit events for every scaling decision.

Design
------
* **ScalingPolicy** – a configurable dataclass that defines the min/max
  worker count, the complexity and load thresholds that trigger scale-up,
  and the idle threshold that triggers scale-down.
* **SwarmScaler** – the main class.  It evaluates current team size against
  the policy, spawns new workers (via AgentFactory) or retires excess ones,
  and logs every action to the shared :class:`AuditLedger`.

Complexity scoring
------------------
A float in ``[0.0, 1.0]``:
  * ``< policy.scale_down_complexity`` → simple task, scale down.
  * ``> policy.scale_up_complexity``   → complex task, scale up.
  * in between                         → maintain current size.

Load scoring
------------
A float in ``[0.0, 1.0]`` representing the fraction of workers that are
currently busy.  Values above ``policy.scale_up_load`` trigger scale-up
regardless of complexity.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SwarmScaler")


# ---------------------------------------------------------------------------
# Policy model
# ---------------------------------------------------------------------------

@dataclass
class ScalingPolicy:
    """Configuration for the Swarm auto-scaler.

    Attributes
    ----------
    min_workers:
        Minimum number of active Swarm workers.  The scaler will never
        retire workers below this floor.
    max_workers:
        Maximum number of active Swarm workers.  The scaler will never
        spawn more workers than this ceiling.
    scale_up_complexity:
        Complexity score (0–1) above which scale-up is triggered.
    scale_down_complexity:
        Complexity score (0–1) below which scale-down is triggered.
    scale_up_load:
        Load ratio (0–1, fraction of busy workers) above which scale-up
        is triggered independently of complexity.
    scale_step:
        Number of workers to add or remove per scaling event.
    """

    min_workers: int = 2
    max_workers: int = 10
    scale_up_complexity: float = 0.65
    scale_down_complexity: float = 0.30
    scale_up_load: float = 0.80
    scale_step: int = 2

    def __post_init__(self) -> None:
        if self.min_workers < 1:
            raise ValueError("min_workers must be >= 1")
        if self.max_workers < self.min_workers:
            raise ValueError("max_workers must be >= min_workers")
        if not (0.0 <= self.scale_down_complexity < self.scale_up_complexity <= 1.0):
            raise ValueError(
                "Need 0 <= scale_down_complexity < scale_up_complexity <= 1"
            )


# ---------------------------------------------------------------------------
# Scaling decision enum
# ---------------------------------------------------------------------------

class ScalingAction(str):
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NO_CHANGE = "no_change"


# ---------------------------------------------------------------------------
# SwarmScaler
# ---------------------------------------------------------------------------

class SwarmScaler:
    """Dynamic worker scaler for Swarm-mode Agent teams.

    Parameters
    ----------
    policy:
        :class:`ScalingPolicy` governing thresholds.  A default policy is
        used when *policy* is ``None``.
    audit_ledger:
        Optional :class:`AuditLedger` instance.  When provided, all
        scale-up / scale-down events are recorded.  The shared singleton
        is used when *audit_ledger* is ``None``.
    """

    def __init__(
        self,
        policy: Optional[ScalingPolicy] = None,
        audit_ledger=None,
    ) -> None:
        self.policy = policy or ScalingPolicy()
        self._ledger = audit_ledger
        # team_id → list of worker agent_ids currently managed by the scaler
        self._managed_workers: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_ledger(self):
        if self._ledger is not None:
            return self._ledger
        try:
            from core.control_plane._globals import get_audit_ledger
            return get_audit_ledger()
        except Exception:
            return None

    def _emit(
        self,
        event_type_str: str,
        team_id: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """Append a scaling audit event to the ledger (best-effort)."""
        ledger = self._get_ledger()
        if ledger is None:
            return
        try:
            from core.control_plane.audit_ledger import EventType, Severity
            # Map string → enum, fallback to SCHEDULER_DECISION
            try:
                et = EventType(event_type_str)
            except ValueError:
                et = EventType.SCHEDULER_DECISION
            ledger.append(
                event_type=et,
                severity=Severity.INFO,
                source="swarm_scaler",
                message=message,
                payload=payload or {},
                trace_id=trace_id,
                task_id=team_id,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("SwarmScaler: failed to emit audit event: %s", exc)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        team_id: str,
        current_worker_count: int,
        complexity: float,
        load: float,
    ) -> str:
        """Decide whether to scale up, scale down, or do nothing.

        Parameters
        ----------
        team_id:
            Identifier of the Swarm team being evaluated.
        current_worker_count:
            How many workers the team currently has.
        complexity:
            Task complexity score in ``[0.0, 1.0]``.
        load:
            Current load ratio in ``[0.0, 1.0]`` (fraction of workers busy).

        Returns
        -------
        str
            One of ``"scale_up"``, ``"scale_down"``, or ``"no_change"``.
        """
        if (complexity > self.policy.scale_up_complexity or load > self.policy.scale_up_load) \
                and current_worker_count < self.policy.max_workers:
            return ScalingAction.SCALE_UP
        if complexity < self.policy.scale_down_complexity \
                and load < self.policy.scale_up_load \
                and current_worker_count > self.policy.min_workers:
            return ScalingAction.SCALE_DOWN
        return ScalingAction.NO_CHANGE

    # ------------------------------------------------------------------
    # Scale-up / scale-down
    # ------------------------------------------------------------------

    def scale_up(
        self,
        team_id: str,
        current_workers: List[str],
        agent_factory=None,
        n: Optional[int] = None,
        trace_id: Optional[str] = None,
        complexity: float = 0.0,
        load: float = 0.0,
    ) -> List[str]:
        """Spawn additional Swarm workers.

        Parameters
        ----------
        team_id:
            Identifier of the team to scale.
        current_workers:
            List of agent IDs currently in the team.
        agent_factory:
            Optional :class:`AgentFactory` instance.  When provided,
            workers are created via ``create_from_template("research")``.
        n:
            Number of workers to add.  Defaults to ``policy.scale_step``.
        trace_id:
            Optional trace identifier for audit correlation.
        complexity, load:
            Scores that triggered the scale-up (recorded in audit payload).

        Returns
        -------
        list[str]
            Agent IDs of the newly spawned workers.
        """
        cap = self.policy.max_workers - len(current_workers)
        add_count = min(n or self.policy.scale_step, cap)
        if add_count <= 0:
            logger.debug("scale_up: already at max_workers for team %s", team_id)
            return []

        new_workers: List[str] = []
        for _ in range(add_count):
            if agent_factory is not None:
                try:
                    agent = agent_factory.create_from_template("research")
                    new_workers.append(agent.id)
                    continue
                except Exception as exc:
                    logger.debug("factory.create_from_template failed: %s", exc)
            # fallback: synthetic ID
            new_workers.append(f"swarm_worker_{uuid.uuid4().hex[:8]}")

        tracked = self._managed_workers.setdefault(team_id, [])
        tracked.extend(new_workers)

        msg = (
            f"scale_up: +{add_count} workers for team {team_id} "
            f"(complexity={complexity:.2f}, load={load:.2f})"
        )
        logger.info(msg)
        self._emit(
            "scheduler_decision",
            team_id,
            msg,
            payload={
                "action": ScalingAction.SCALE_UP,
                "added": new_workers,
                "complexity": complexity,
                "load": load,
                "team_size_after": len(current_workers) + add_count,
            },
            trace_id=trace_id,
        )
        return new_workers

    def scale_down(
        self,
        team_id: str,
        current_workers: List[str],
        agent_factory=None,
        n: Optional[int] = None,
        trace_id: Optional[str] = None,
        complexity: float = 0.0,
        load: float = 0.0,
    ) -> List[str]:
        """Retire excess Swarm workers.

        Parameters
        ----------
        team_id:
            Identifier of the team to scale.
        current_workers:
            List of agent IDs currently in the team.
        agent_factory:
            Optional :class:`AgentFactory` instance.  When provided,
            retired workers are removed from the factory registry.
        n:
            Number of workers to retire.  Defaults to ``policy.scale_step``.
        trace_id:
            Optional trace identifier for audit correlation.
        complexity, load:
            Scores that triggered the scale-down (recorded in audit payload).

        Returns
        -------
        list[str]
            Agent IDs of the retired workers.
        """
        floor = self.policy.min_workers
        remove_count = min(
            n or self.policy.scale_step,
            max(0, len(current_workers) - floor),
        )
        if remove_count <= 0:
            logger.debug("scale_down: already at min_workers for team %s", team_id)
            return []

        retired = current_workers[-remove_count:]

        if agent_factory is not None:
            for aid in retired:
                agent_factory.agents.pop(aid, None)
                try:
                    agent_factory.message_bus.unregister(aid)
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

        tracked = self._managed_workers.get(team_id, [])
        for aid in retired:
            if aid in tracked:
                tracked.remove(aid)

        msg = (
            f"scale_down: -{remove_count} workers for team {team_id} "
            f"(complexity={complexity:.2f}, load={load:.2f})"
        )
        logger.info(msg)
        self._emit(
            "scheduler_decision",
            team_id,
            msg,
            payload={
                "action": ScalingAction.SCALE_DOWN,
                "retired": retired,
                "complexity": complexity,
                "load": load,
                "team_size_after": len(current_workers) - remove_count,
            },
            trace_id=trace_id,
        )
        return retired

    def autoscale(
        self,
        team_id: str,
        current_workers: List[str],
        complexity: float,
        load: float,
        agent_factory=None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate + act in a single call.

        Returns a dict with keys ``action``, ``added``, and ``retired``.
        """
        action = self.evaluate(
            team_id, len(current_workers), complexity, load
        )
        if action == ScalingAction.SCALE_UP:
            added = self.scale_up(
                team_id, current_workers, agent_factory,
                trace_id=trace_id, complexity=complexity, load=load,
            )
            return {"action": action, "added": added, "retired": []}
        if action == ScalingAction.SCALE_DOWN:
            retired = self.scale_down(
                team_id, current_workers, agent_factory,
                trace_id=trace_id, complexity=complexity, load=load,
            )
            return {"action": action, "added": [], "retired": retired}
        return {"action": action, "added": [], "retired": []}

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def managed_workers(self, team_id: str) -> List[str]:
        """Return the list of worker agent IDs managed by the scaler for *team_id*."""
        return list(self._managed_workers.get(team_id, []))
