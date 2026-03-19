#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — ConstellationRuntime
================================

Unified system entry point that closes the planning→DAG→execution loop for
TaskConstellation-based orchestration.

Architecture
------------
::

    User Request
        │
        ▼
    ConstellationRuntime.run()
        │
        ├─ 1. Intent/Decomposition  →  TaskDecomposition  (LLM or direct)
        │
        ├─ 2. DAG construction      →  layers (via DAGScheduler)
        │        └─ audit: DAG_PLANNED
        │
        ├─ 3. Scheduling & dispatch →  select_device() per sub-task
        │        └─ audit: DAG_DISPATCHED
        │
        ├─ 4. Layered execution     →  parallel within each DAG layer
        │        ├─ on_task_failed  →  DAGEvolver.on_task_failed()
        │        ├─ on_timeout      →  DAGEvolver.on_timeout()
        │        └─ audit: TASK_COMPLETED / TASK_FAILED
        │
        └─ 5. Result aggregation    →  OrchestrationResult
                 └─ audit: DAG_COMPLETED

Default scheduler: delegates to ``Node_71`` multi-device scheduler when
available; falls back to ``SmartOrchestrator`` from
``core.orchestrator_engine``.

Usage
-----
    from core.constellation_runtime import get_constellation_runtime

    runtime = get_constellation_runtime()
    result = await runtime.run(
        task_description="截图并分析手机屏幕内容",
        device_id="pc_01",
        session_id="sess_abc",
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ConstellationRuntime")


# ---------------------------------------------------------------------------
# ConstellationRuntime
# ---------------------------------------------------------------------------

class ConstellationRuntime:
    """Unified planning→DAG→execution loop.

    Parameters
    ----------
    config:
        Optional configuration dict forwarded to sub-components.
    enable_dag_evolution:
        Whether to activate :class:`~core.dag_evolver.DAGEvolver` hooks.
        Default ``True``.
    max_replan_attempts:
        Maximum per-task replan attempts forwarded to the evolver.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        enable_dag_evolution: bool = True,
        max_replan_attempts: int = 3,
    ) -> None:
        self._config = config or {}
        self.enable_dag_evolution = enable_dag_evolution
        self._evolver = None
        self._smart_orchestrator = None
        self._max_replan_attempts = max_replan_attempts
        logger.info(
            "ConstellationRuntime 初始化 [dag_evolution=%s]", enable_dag_evolution
        )

    # ------------------------------------------------------------------
    # Lazy dependency accessors
    # ------------------------------------------------------------------

    def _get_evolver(self):
        if self._evolver is None and self.enable_dag_evolution:
            try:
                from core.dag_evolver import DAGEvolver
                self._evolver = DAGEvolver(
                    max_replan_attempts=self._max_replan_attempts
                )
            except Exception as exc:
                logger.warning("DAGEvolver 不可用: %s", exc)
        return self._evolver

    def _get_smart_orchestrator(self):
        if self._smart_orchestrator is None:
            try:
                from core.orchestrator_engine import SmartOrchestrator
                self._smart_orchestrator = SmartOrchestrator(self._config)
            except Exception as exc:
                logger.warning("SmartOrchestrator 不可用: %s", exc)
        return self._smart_orchestrator

    def _get_device_pool(self):
        try:
            from core.device_pool_manager import get_device_pool_manager
            return get_device_pool_manager()
        except Exception as exc:
            logger.debug("DevicePoolManager 不可用: %s", exc)
            return None

    def _get_audit_ledger(self):
        try:
            from core.control_plane.audit_ledger import AuditLedger
            return AuditLedger.get_instance()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        task_description: str,
        device_id: str = "",
        session_id: Optional[str] = None,
        user_id: str = "default",
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 300.0,
    ) -> Dict[str, Any]:
        """Execute a task through the full constellation loop.

        Args:
            task_description: Natural-language task description.
            device_id: Source device ID (used for context enrichment).
            session_id: Session identifier (auto-generated if None).
            user_id: User identifier.
            context: Additional context forwarded to decomposition.
            timeout_seconds: Overall execution timeout.

        Returns:
            Dict with keys ``success``, ``result``, ``trace_id``,
            ``session_id``, ``mode``, and ``data``.
        """
        trace_id = (context or {}).get("trace_id") or uuid.uuid4().hex
        session_id = session_id or uuid.uuid4().hex[:12]
        t0 = time.monotonic()

        logger.info("[%s] ConstellationRuntime.run: %s", trace_id, task_description[:80])

        # ── Try Node_71 fast path ─────────────────────────────────────────
        node71_result = await self._try_node71(
            task_description, trace_id, device_id, session_id, context
        )
        if node71_result is not None:
            return node71_result

        # ── SmartOrchestrator DAG path ────────────────────────────────────
        try:
            result = await asyncio.wait_for(
                self._run_dag_loop(
                    task_description=task_description,
                    trace_id=trace_id,
                    device_id=device_id,
                    session_id=session_id,
                    user_id=user_id,
                    context=context or {},
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("[%s] ConstellationRuntime 超时 (%.0fs)", trace_id, timeout_seconds)
            result = {
                "success": False,
                "reply": f"执行超时（{timeout_seconds:.0f}秒）",
                "trace_id": trace_id,
                "session_id": session_id,
                "mode": "timeout",
                "data": {},
            }

        result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return result

    # ------------------------------------------------------------------
    # Internal: Node_71 fast path
    # ------------------------------------------------------------------

    async def _try_node71(
        self,
        task_description: str,
        trace_id: str,
        device_id: str,
        session_id: str,
        context: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Attempt to route through Node_71 multi-device scheduler.

        Returns a result dict on success, or None if Node_71 is unavailable.
        """
        try:
            from core.node_registry import get_registry
            registry = get_registry()
            node = registry.get_node("Node_71") if registry else None
            if node is None:
                return None

            resp = await registry.call_node(
                "Node_71",
                "orchestrate",
                {
                    "task": task_description,
                    "trace_id": trace_id,
                    "device_id": device_id,
                    "session_id": session_id,
                    "context": context or {},
                },
            )
            if resp.get("success"):
                logger.info("[%s] Node_71 成功处理任务", trace_id)
                return {
                    "success": True,
                    "reply": resp.get("reply") or resp.get("result") or "完成",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "mode": "node71",
                    "data": resp,
                }
        except Exception as exc:
            logger.debug("[%s] Node_71 不可用，降级到 DAG 路径: %s", trace_id, exc)
        return None

    # ------------------------------------------------------------------
    # Internal: full DAG execution loop
    # ------------------------------------------------------------------

    async def _run_dag_loop(
        self,
        task_description: str,
        trace_id: str,
        device_id: str,
        session_id: str,
        user_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Core planning → DAG → execution loop."""
        from core.schemas.orchestration import (
            OrchestrationRequest,
            OrchestrationStatus,
            SubTaskStatus,
        )

        ledger = self._get_audit_ledger()
        request_id = f"cr_{uuid.uuid4().hex[:12]}"

        # ── 1. Intent / Decomposition ──────────────────────────────────
        orchestrator = self._get_smart_orchestrator()
        if orchestrator is None:
            return {
                "success": False,
                "reply": "SmartOrchestrator 不可用",
                "trace_id": trace_id,
                "session_id": session_id,
                "mode": "fallback",
                "data": {},
            }

        orch_request = OrchestrationRequest(
            request_id=request_id,
            task_description=task_description,
            session_id=session_id,
            device_id=device_id,
            user_context={**context, "trace_id": trace_id, "user_id": user_id},
        )

        # Audit: intent stage
        self._ledger_append(
            ledger, "TASK_CREATED", trace_id=trace_id, task_id=request_id,
            source="constellation_runtime",
            message=f"TaskConstellation: {task_description[:80]}",
        )

        # ── 2. Decompose → DAG ────────────────────────────────────────
        decomposition = await orchestrator._decompose_task(
            task_description, orch_request.user_context
        )

        # Audit: plan stage
        self._ledger_append(
            ledger, "DAG_PLANNED", trace_id=trace_id, task_id=request_id,
            source="constellation_runtime",
            payload={
                "subtask_count": len(decomposition.subtasks),
                "goal": decomposition.goal,
            },
        )

        if not decomposition.subtasks:
            # Simple task — skip DAG
            result = await orchestrator._execute_simple_task(task_description, orch_request)
            self._ledger_append(
                ledger, "DAG_COMPLETED", trace_id=trace_id, task_id=request_id,
                source="constellation_runtime",
                payload={"mode": "simple", "status": "success"},
            )
            return {
                "success": True,
                "reply": result.get("reply", "任务完成"),
                "trace_id": trace_id,
                "session_id": session_id,
                "mode": "simple",
                "data": result,
            }

        # Build DAG layers
        try:
            from core.orchestrator_engine import DAGScheduler
            layers, task_map = DAGScheduler.build_and_validate(decomposition.subtasks)
        except ValueError as dag_err:
            logger.error("[%s] DAG 构建失败: %s", trace_id, dag_err)
            return {
                "success": False,
                "reply": f"DAG 构建失败: {dag_err}",
                "trace_id": trace_id,
                "session_id": session_id,
                "mode": "dag_error",
                "data": {},
            }

        # Assign devices via DevicePoolManager
        pool = self._get_device_pool()
        if pool:
            for subtask in decomposition.subtasks:
                if not subtask.device_id:
                    caps = [subtask.device_type] if subtask.device_type else None
                    selected = pool.select_device(required_capabilities=caps)
                    if selected:
                        subtask.device_id = selected

        # Audit: dispatch stage
        self._ledger_append(
            ledger, "DAG_DISPATCHED", trace_id=trace_id, task_id=request_id,
            source="constellation_runtime",
            payload={
                "layers": len(layers),
                "tasks": [st.task_id for st in decomposition.subtasks],
            },
        )

        # ── 3. Layered execution ────────────────────────────────────────
        orch_result = await self._execute_layers(
            layers=layers,
            task_map=task_map,
            decomposition=decomposition,
            orch_request=orch_request,
            orchestrator=orchestrator,
            trace_id=trace_id,
            request_id=request_id,
            ledger=ledger,
        )

        # Return devices to pool
        if pool:
            for subtask in decomposition.subtasks:
                if subtask.device_id:
                    if subtask.status == SubTaskStatus.SUCCESS:
                        pool.mark_success(subtask.device_id)
                    elif subtask.status == SubTaskStatus.FAILED:
                        pool.mark_failure(subtask.device_id, error=subtask.error)

        # Audit: result stage
        self._ledger_append(
            ledger, "DAG_COMPLETED", trace_id=trace_id, task_id=request_id,
            source="constellation_runtime",
            payload={
                "status": orch_result.status.value,
                "completed": orch_result.completed_subtasks,
                "failed": orch_result.failed_subtasks,
                "total": orch_result.total_subtasks,
            },
        )

        success = orch_result.status in (
            OrchestrationStatus.SUCCESS, OrchestrationStatus.PARTIAL_SUCCESS
        )
        return {
            "success": success,
            "reply": orch_result.summary or ("任务完成" if success else "任务失败"),
            "trace_id": trace_id,
            "session_id": session_id,
            "mode": "dag",
            "data": orch_result.model_dump(),
        }

    # ------------------------------------------------------------------
    # Layered execution with DAG evolution
    # ------------------------------------------------------------------

    async def _execute_layers(
        self,
        layers,
        task_map,
        decomposition,
        orch_request,
        orchestrator,
        trace_id: str,
        request_id: str,
        ledger,
    ):
        """Execute DAG layers with optional evolution hooks."""
        from core.schemas.orchestration import (
            OrchestrationResult,
            OrchestrationStatus,
            SubTaskStatus,
        )

        result = OrchestrationResult(
            request_id=request_id,
            status=OrchestrationStatus.EXECUTING,
            goal=orch_request.task_description,
            subtasks=decomposition.subtasks,
            total_subtasks=len(decomposition.subtasks),
        )

        evolver = self._get_evolver()
        completed = 0
        failed = 0

        for layer_idx, layer_task_ids in enumerate(layers):
            tasks_to_run = []
            for tid in layer_task_ids:
                task = task_map.get(tid)
                if task is None:
                    continue
                deps_ok = all(
                    task_map.get(dep_id) is not None
                    and task_map[dep_id].status == SubTaskStatus.SUCCESS
                    for dep_id in (task.depends_on or [])
                    if dep_id in task_map
                )
                if deps_ok:
                    tasks_to_run.append(task)
                else:
                    task.status = SubTaskStatus.SKIPPED
                    task.error = "前置依赖失败，已跳过"
                    failed += 1

            if tasks_to_run:
                layer_results = await asyncio.gather(
                    *[
                        orchestrator._execute_subtask(task, orch_request)
                        for task in tasks_to_run
                    ],
                    return_exceptions=True,
                )

                for task, res in zip(tasks_to_run, layer_results):
                    if isinstance(res, Exception):
                        task.status = SubTaskStatus.FAILED
                        task.error = str(res)

                    if task.status == SubTaskStatus.SUCCESS:
                        completed += 1
                        self._ledger_append(
                            ledger, "TASK_COMPLETED",
                            trace_id=trace_id, task_id=task.task_id,
                            source="constellation_runtime",
                        )
                    elif task.status == SubTaskStatus.FAILED:
                        failed += 1
                        self._ledger_append(
                            ledger, "TASK_FAILED",
                            trace_id=trace_id, task_id=task.task_id,
                            source="constellation_runtime",
                            payload={"error": task.error},
                        )
                        # DAG evolution: replan on failure
                        if evolver:
                            decomposition = evolver.on_task_failed(
                                decomposition,
                                failed_task_id=task.task_id,
                                error=task.error,
                                context={"trace_id": trace_id},
                            )
                            self._ledger_append(
                                ledger, "DAG_EVOLVED",
                                trace_id=trace_id, task_id=request_id,
                                source="constellation_runtime",
                                payload={"trigger": "task_failed", "task_id": task.task_id},
                            )

        result.completed_subtasks = completed
        result.failed_subtasks = failed

        if failed == 0:
            result.status = OrchestrationStatus.SUCCESS
            result.summary = f"全部 {completed} 个子任务执行成功"
        elif completed > 0:
            result.status = OrchestrationStatus.PARTIAL_SUCCESS
            result.summary = f"{completed}/{result.total_subtasks} 成功, {failed} 失败"
        else:
            result.status = OrchestrationStatus.FAILED
            result.summary = f"全部 {failed} 个子任务失败"

        return result

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ledger_append(ledger, event_name: str, **kwargs) -> None:
        """Append an event to the audit ledger (best-effort, never raises)."""
        if ledger is None:
            return
        try:
            from core.control_plane.audit_ledger import EventType, Severity
            et = getattr(EventType, event_name.upper(), None)
            if et is None:
                return
            ledger.append(et, **kwargs)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Response shape helpers
# ---------------------------------------------------------------------------

def wrap_as_orchestration_response(
    cr_result: Dict[str, Any],
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap a :meth:`ConstellationRuntime.run` result into an
    ``OrchestrationResponse``-compatible dict.

    This helper exists so that Node_110 / Node_81 can delegate to
    ConstellationRuntime while still returning the response schema their
    existing clients expect.

    Args:
        cr_result: The dict returned by :meth:`ConstellationRuntime.run`.
        task_id:   Optional task ID to embed in the response.  Defaults to
                   the ``trace_id`` from *cr_result*.

    Returns:
        A dict with keys ``task_id``, ``status``, ``execution_plan``, and
        ``result`` — matching the ``OrchestrationResponse`` model used by
        Node_110, and enriched with ``trace_id`` / ``session_id`` for
        Node_81 consumers.
    """
    resolved_task_id = task_id or cr_result.get("trace_id") or uuid.uuid4().hex[:12]
    status = "completed" if cr_result.get("success") else "failed"
    return {
        "task_id": resolved_task_id,
        "status": status,
        "execution_plan": {
            "mode": cr_result.get("mode", "dag"),
            "trace_id": cr_result.get("trace_id"),
            "session_id": cr_result.get("session_id"),
        },
        "result": {
            "reply": cr_result.get("reply", ""),
            "success": cr_result.get("success", False),
            "data": cr_result.get("data", {}),
            "elapsed_ms": cr_result.get("elapsed_ms"),
        },
        # Pass-through fields for Node_81 consumers
        "trace_id": cr_result.get("trace_id"),
        "session_id": cr_result.get("session_id"),
    }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_runtime_instance: Optional[ConstellationRuntime] = None


def get_constellation_runtime(
    config: Optional[Dict[str, Any]] = None,
    enable_dag_evolution: bool = True,
) -> ConstellationRuntime:
    """Return (or create) the global :class:`ConstellationRuntime` singleton."""
    global _runtime_instance
    if _runtime_instance is None:
        _runtime_instance = ConstellationRuntime(
            config=config,
            enable_dag_evolution=enable_dag_evolution,
        )
    return _runtime_instance


# ---------------------------------------------------------------------------
# Legacy path guardrail
# ---------------------------------------------------------------------------

#: Known legacy orchestrator entry-point paths that should not be invoked
#: directly as primary system entry points.
LEGACY_ORCHESTRATOR_PATHS = frozenset(
    {
        "nodes.Node_110_SmartOrchestrator.server",
        "nodes.Node_110_SmartOrchestrator.main",
        "nodes.Node_81_Orchestrator.main",
        "nodes.Node_50_Transformer.task_orchestrator",
        "galaxy_gateway.orchestrator.task_orchestrator",
    }
)


def warn_legacy_path(
    caller: str,
    trace_id: Optional[str] = None,
    recommendation: str = "Use core.constellation_runtime.get_constellation_runtime() instead.",
) -> None:
    """Log a structured deprecation warning when a legacy orchestrator path is invoked.

    This guardrail is called by ConstellationRuntime's internal helpers when
    they detect that execution originated from a known legacy entry point.
    It is also exported so that legacy nodes can call it proactively.

    Args:
        caller:         Module or class name of the legacy caller (e.g.
                        ``"nodes.Node_110_SmartOrchestrator.server"``).
        trace_id:       Optional request trace ID for log correlation.
        recommendation: Human-readable migration guidance.

    Example::

        from core.constellation_runtime import warn_legacy_path
        warn_legacy_path(
            caller="nodes.Node_110_SmartOrchestrator.server",
            trace_id="abc123",
        )
    """
    logger.warning(
        "LEGACY PATH GUARDRAIL | caller=%r | trace_id=%s | %s",
        caller,
        trace_id or "n/a",
        recommendation,
    )
