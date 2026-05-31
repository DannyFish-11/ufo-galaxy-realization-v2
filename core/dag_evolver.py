#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Dynamic DAG Evolver
==============================

Implements runtime DAG evolution hooks that allow the
:class:`core.constellation_runtime.ConstellationRuntime` to adapt the
execution graph in response to failures, timeouts, and missing capabilities.

Hooks
-----
* ``on_task_failed``      — replan the failed sub-graph.
* ``on_timeout``          — reassign / reschedule the timed-out task.
* ``on_missing_capability`` — insert a *capability-gap* node into the DAG.

All hooks mutate the provided :class:`~core.schemas.orchestration.TaskDecomposition`
in-place and return the modified object so the runtime can continue execution
with the evolved graph.

Usage
-----
    from core.dag_evolver import DAGEvolver

    evolver = DAGEvolver()
    decomposition = evolver.on_task_failed(
        decomposition, failed_task_id="sub_abc", error="connection refused"
    )
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.DAGEvolver")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_dependents(task_id: str, subtasks) -> List[str]:
    """Return IDs of all tasks that directly depend on *task_id*."""
    return [
        st.task_id
        for st in subtasks
        if task_id in (st.depends_on or [])
    ]


def _topological_sort(subtasks) -> List[str]:
    """Return a flat topological order of task_ids (Kahn's algorithm).

    Silently handles cycles by returning whatever was processed.
    """
    from collections import deque

    # First pass: initialize in_degree to 0 for all tasks
    in_degree: Dict[str, int] = {st.task_id: 0 for st in subtasks}
    # Second pass: increment for each valid dependency
    for st in subtasks:
        for dep in (st.depends_on or []):
            if dep in in_degree:
                in_degree[st.task_id] = in_degree.get(st.task_id, 0) + 1

    queue: deque = deque([tid for tid, deg in in_degree.items() if deg == 0])
    order: List[str] = []
    adj: Dict[str, List[str]] = {st.task_id: [] for st in subtasks}
    for st in subtasks:
        for dep in (st.depends_on or []):
            if dep in adj:
                adj[dep].append(st.task_id)

    while queue:
        tid = queue.popleft()
        order.append(tid)
        for dep in adj.get(tid, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
    return order


# ---------------------------------------------------------------------------
# DAGEvolver
# ---------------------------------------------------------------------------

class DAGEvolver:
    """Runtime DAG evolution engine.

    Parameters
    ----------
    max_replan_attempts:
        Maximum times a single task can be replanned before it is
        permanently marked as failed.
    """

    def __init__(self, max_replan_attempts: int = 3) -> None:
        self.max_replan_attempts = max_replan_attempts
        # Track how many times each task has been replanned
        self._replan_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Hook: task failed → replan sub-graph
    # ------------------------------------------------------------------

    def on_task_failed(
        self,
        decomposition,
        failed_task_id: str,
        error: str = "",
        context: Optional[Dict[str, Any]] = None,
    ):
        """Replan the sub-graph rooted at *failed_task_id*.

        Strategy
        --------
        1. Increment the replan counter for this task.
        2. If under the limit, reset the task and all downstream dependents
           back to ``PENDING`` so they will be re-executed.
        3. If the limit is exceeded, propagate ``FAILED`` to all dependents.
        4. Emit an audit event.

        Args:
            decomposition: The current :class:`TaskDecomposition`.
            failed_task_id: The task that failed.
            error: Human-readable error string.
            context: Optional extra context forwarded to the audit ledger.

        Returns:
            The mutated *decomposition*.
        """
        from core.schemas.orchestration import SubTaskStatus

        count = self._replan_counts.get(failed_task_id, 0) + 1
        self._replan_counts[failed_task_id] = count

        task_map = {st.task_id: st for st in decomposition.subtasks}
        failed_task = task_map.get(failed_task_id)
        if failed_task is None:
            logger.warning("on_task_failed: 找不到任务 %s", failed_task_id)
            return decomposition

        if count <= self.max_replan_attempts:
            # Reset failed task and its downstream dependents to PENDING
            affected: Set[str] = {failed_task_id}
            changed = True
            while changed:
                changed = False
                for st in decomposition.subtasks:
                    if any(dep in affected for dep in (st.depends_on or [])):
                        if st.task_id not in affected:
                            affected.add(st.task_id)
                            changed = True

            for tid in affected:
                t = task_map.get(tid)
                if t:
                    t.status = SubTaskStatus.PENDING
                    t.result = None
                    t.error = ""
                    t.started_at = None
                    t.completed_at = None

            logger.info(
                "DAG 演化 [on_task_failed]: 重置 %d 个任务 (attempt %d/%d) | 触发任务: %s",
                len(affected), count, self.max_replan_attempts, failed_task_id,
            )
            self._emit_audit(
                "TASK_REPLANNED",
                task_id=failed_task_id,
                affected_count=len(affected),
                attempt=count,
                error=error,
                context=context,
            )
        else:
            # Exceeded replan limit — cascade FAILED status
            failed_task.status = SubTaskStatus.FAILED
            failed_task.error = f"[replan exhausted] {error}"
            for st in decomposition.subtasks:
                if failed_task_id in (st.depends_on or []):
                    st.status = SubTaskStatus.FAILED
                    st.error = f"上游任务 {failed_task_id} 已耗尽重试次数"
            logger.warning(
                "DAG 演化 [on_task_failed]: 重试次数耗尽，放弃任务 %s", failed_task_id
            )
            self._emit_audit(
                "TASK_FAILED",
                task_id=failed_task_id,
                error=f"replan attempts exhausted: {error}",
                context=context,
            )

        return decomposition

    # ------------------------------------------------------------------
    # Hook: task timeout → reassign / reschedule
    # ------------------------------------------------------------------

    def on_timeout(
        self,
        decomposition,
        timed_out_task_id: str,
        preferred_device_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Reassign a timed-out task to a different device.

        Strategy
        --------
        1. Clear the task's ``device_id`` so the scheduler will re-select.
        2. If *preferred_device_id* is given, set it directly.
        3. Reset the task to ``PENDING``.
        4. Emit an audit event.

        Args:
            decomposition: The current :class:`TaskDecomposition`.
            timed_out_task_id: The task that timed out.
            preferred_device_id: Optional override device for the retry.
            context: Optional extra context.

        Returns:
            The mutated *decomposition*.
        """
        from core.schemas.orchestration import SubTaskStatus

        task_map = {st.task_id: st for st in decomposition.subtasks}
        timed_out_task = task_map.get(timed_out_task_id)
        if timed_out_task is None:
            logger.warning("on_timeout: 找不到任务 %s", timed_out_task_id)
            return decomposition

        old_device = timed_out_task.device_id
        timed_out_task.device_id = preferred_device_id or ""
        timed_out_task.status = SubTaskStatus.PENDING
        timed_out_task.result = None
        timed_out_task.error = ""
        timed_out_task.started_at = None
        timed_out_task.completed_at = None

        logger.info(
            "DAG 演化 [on_timeout]: 任务 %s 从设备 %s 重新分配",
            timed_out_task_id, old_device or "(auto)"
        )
        self._emit_audit(
            "TASK_REASSIGNED",
            task_id=timed_out_task_id,
            old_device_id=old_device,
            new_device_id=timed_out_task.device_id,
            context=context,
        )
        return decomposition

    # ------------------------------------------------------------------
    # Hook: missing capability → insert gap node
    # ------------------------------------------------------------------

    def on_missing_capability(
        self,
        decomposition,
        requesting_task_id: str,
        missing_capability: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Insert a *capability-gap* node before the requesting task.

        The gap node acts as a placeholder that informs the operator (or an
        automated resolver) that a capability must be provisioned before the
        downstream task can run.

        Strategy
        --------
        1. Create a new ``SubTask`` with ``action="acquire_capability"`` and
           ``params={"capability": missing_capability}``.
        2. Insert the new node as a dependency of *requesting_task_id*.
        3. Emit an audit event.

        Args:
            decomposition: The current :class:`TaskDecomposition`.
            requesting_task_id: Task that needs the capability.
            missing_capability: Name of the missing capability.
            context: Optional extra context.

        Returns:
            The mutated *decomposition*.
        """
        from core.schemas.orchestration import SubTask, SubTaskStatus

        gap_id = f"cap_gap_{uuid.uuid4().hex[:8]}"
        gap_task = SubTask(
            task_id=gap_id,
            name=f"Acquire capability: {missing_capability}",
            description=(
                f"自动插入的能力获取节点，为任务 {requesting_task_id} "
                f"获取能力 '{missing_capability}'。"
            ),
            action="acquire_capability",
            params={"capability": missing_capability},
            depends_on=[],
            status=SubTaskStatus.PENDING,
        )

        # Update the requesting task to depend on the gap node
        task_map = {st.task_id: st for st in decomposition.subtasks}
        requesting_task = task_map.get(requesting_task_id)
        if requesting_task is not None:
            if gap_id not in requesting_task.depends_on:
                requesting_task.depends_on = [gap_id] + list(requesting_task.depends_on)

        decomposition.subtasks.insert(0, gap_task)

        logger.info(
            "DAG 演化 [on_missing_capability]: 插入能力缺口节点 %s (cap=%s) → 任务 %s",
            gap_id, missing_capability, requesting_task_id,
        )
        self._emit_audit(
            "DAG_NODE_INSERTED",
            task_id=gap_id,
            requesting_task_id=requesting_task_id,
            capability=missing_capability,
            context=context,
        )
        return decomposition

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_audit(event_name: str, **kwargs) -> None:
        """Fire an audit-ledger event (best-effort, never raises)."""
        try:
            from core.control_plane.audit_ledger import AuditLedger, EventType
            ledger = AuditLedger.get_instance()
            et = getattr(EventType, event_name.upper(), None)
            if et is None:
                return
            # Flatten nested context dict into payload
            ctx = kwargs.pop("context", None) or {}
            payload = {**kwargs, **ctx}
            ledger.append(
                et,
                trace_id=payload.pop("trace_id", ""),
                task_id=payload.pop("task_id", ""),
                payload=payload,
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
