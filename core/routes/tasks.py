"""
Galaxy - Task Routes
==========================

**Architecture role: ROUTE ADAPTER SURFACE — no orchestration authority**
--------------------------------------------------------------------------
This module is a **route adapter surface** for task management endpoints.
Task creation stamps a ``task_id`` and ``trace_id`` and forwards
device-targeted tasks to the canonical execution chain::

    POST /api/v1/tasks   ← you are here (route adapter — no authority)
        → connection_manager.send_to_device()   (simple fire-and-forget)
           task_id and trace_id are stamped on the wire message so that
           the dispatch is traceable through the canonical correlation chain.
           (for full orchestration: use POST /api/v1/command/unified which
            routes through CommandRouter → DeviceRouter canonically)

This module MUST NOT contain orchestration or dispatch logic.

PR-507: Canonical task front-loading — a ``CanonicalTask`` is created via
``task_adapter.adapt_to_canonical_task()`` at the top of ``create_task()``
so that task ontology is established before any dispatch.  The task_id and
trace_id are drawn from the canonical task's identity so that the rest of
the execution chain shares the same correlation fields.

Routes:
  POST /api/v1/tasks                      - 创建任务
  GET  /api/v1/tasks/{task_id}            - 任务状态
  GET  /api/v1/tasks                      - 任务列表
  POST /api/v1/tasks/{task_id}/result     - 提交任务结果
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.routes._shared import connection_manager, task_queue
from core.routes._models import TaskRequest

logger = logging.getLogger("Galaxy.API")

# PR-507: Canonical task front-loading — this module now creates a
# CanonicalTask via adapt_to_canonical_task() at API ingress before
# any dispatch so that the task ontology layer is always the primary object.
CANONICAL_TASK_API_INGRESS_FRONT_LOADED: str = (
    "CANONICAL_TASK_API_INGRESS_V1: core/routes/tasks.py create_task() "
    "calls adapt_to_canonical_task() before dispatch so CanonicalTask is "
    "the primary ontology object at API ingress."
)

# PR-513 / GAP-512-001: API task ingress now records TaskExecutionRecord in
# ReplayFoundation so that audit lineage is complete for API-ingressed tasks.
TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED: str = (
    "TASK_INGRESS_REPLAY_FOUNDATION_V1: core/routes/tasks.py create_task() "
    "calls ReplayFoundation.record_task_execution() after CanonicalTask "
    "front-load so API-ingressed tasks have complete audit lineage (GAP-512-001)."
)

# PR-E: API task dispatch now attempts CommandRouter.route_envelope() first,
# falling back to the compat send_to_device path only when the canonical
# router is unavailable.  This converges the API task entry path onto the
# canonical dispatch spine (OpenClawd → CommandRouter → DeviceRouter).
TASK_INGRESS_CANONICAL_DISPATCH_SPINE: str = (
    "TASK_INGRESS_CANONICAL_DISPATCH_V1: core/routes/tasks.py create_task() "
    "attempts CommandRouter.route_envelope() before falling back to compat "
    "send_to_device, so the API task path converges on the canonical spine."
)


class TaskResultPayload(BaseModel):
    """Request body for POST /api/v1/tasks/{task_id}/result.

    ``status`` carries the Android/device execution result status.  When absent
    the result is treated as successful.  The value is normalised from the
    Android execution taxonomy (``success`` / ``failed`` / ``error`` /
    ``cancelled`` / ``degraded``) to the canonical V2 vocabulary before being
    written to task_queue, mirroring the mapping applied by
    ``_normalize_android_goal_status`` in the canonical WS handler.
    """

    status: Optional[str] = None
    result: Optional[Any] = None
    details: Optional[str] = None
    trace_id: Optional[str] = None


def _map_result_status(raw_status: Optional[str]) -> str:
    """Map Android/device result status to canonical V2 task status.

    Mirrors the taxonomy in
    ``galaxy_gateway.android.handlers.goal_execution._normalize_android_goal_status``
    so the REST callback path produces consistent statuses with the canonical
    WebSocket handler path.

    Mapping:
        failed / error   → "failed"
        cancelled        → "cancelled"
        degraded         → "degraded"
        anything else    → "completed"   (includes "success", "completed", absent)
    """
    if not raw_status:
        return "completed"
    s = str(raw_status).lower().strip()
    if s in ("failed", "error"):
        return "failed"
    if s == "cancelled":
        return "cancelled"
    if s == "degraded":
        return "degraded"
    return "completed"


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create task management routes router."""
    router = APIRouter()

    @router.post("/api/v1/tasks")
    async def create_task(req: TaskRequest):
        """创建任务"""
        # PR-507: Front-load canonical task creation — CanonicalTask is the
        # primary ontology object; task_id/trace_id flow from its identity.
        task_id: Optional[str] = None
        trace_id: Optional[str] = None
        try:
            from core.task_adapter import adapt_to_canonical_task
            from core.canonical_task import TaskOrigin
            _canonical = adapt_to_canonical_task(
                {
                    "task_type": req.task_type,
                    "payload": req.payload,
                    "targets": [req.device_id] if req.device_id else [],
                    "tool_name": req.task_type,
                    "args": req.payload or {},
                },
                origin=TaskOrigin.API_REQUEST,
            )
            task_id = _canonical.identity.task_id
            trace_id = _canonical.identity.trace_id
            logger.debug(
                "create_task: CanonicalTask front-loaded task_id=%s trace_id=%s",
                task_id, trace_id,
            )
            # PR-513 / GAP-512-001: Record TaskExecutionRecord in ReplayFoundation
            # so API-ingressed tasks have complete audit lineage.
            try:
                from core.replay_foundation import record_task_execution
                record_task_execution(_canonical)
            except Exception as _rep_err:
                logger.debug(
                    "create_task: ReplayFoundation.record_task_execution skipped — %s",
                    _rep_err,
                )
        except Exception as _ct_err:
            logger.debug("create_task: CanonicalTask front-load skipped — %s", _ct_err)

        if task_id is None:
            task_id = str(uuid.uuid4())
        if trace_id is None:
            trace_id = f"trace_{uuid.uuid4().hex[:12]}"

        task = {
            "task_id": task_id,
            "trace_id": trace_id,
            "task_type": req.task_type,
            "payload": req.payload,
            "device_id": req.device_id,
            "priority": req.priority,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        task_queue[task_id] = task

        if req.device_id and req.device_id in connection_manager.active_devices:
            # PR-E: attempt canonical dispatch via CommandRouter.route_envelope()
            # before falling back to the compat send_to_device path.
            # This ensures major live task entry paths converge on the canonical
            # dispatch spine (OpenClawd → CommandRouter → DeviceRouter).
            canonical_dispatched = False
            try:
                from core.command_router import get_command_router
                from core.schemas.task_envelope import TaskEnvelope
                cmd_router = get_command_router()
                envelope = TaskEnvelope(
                    task_id=task_id,
                    trace_id=trace_id,
                    tool_name=req.task_type,
                    args=req.payload or {},
                    targets=[req.device_id],
                    source="api_tasks",
                )
                result = await cmd_router.route_envelope(envelope)
                # Treat the dispatch as successful when the router returns any
                # non-None, non-error result.  An explicit error result (a dict
                # with status="error" or similar) is treated as a failure so
                # the compat fallback can still run.
                if result is not None and (
                    not isinstance(result, dict)
                    or result.get("status") != "error"
                ):
                    task["status"] = "sent"
                    task["dispatch_authority"] = "canonical_command_router"
                    canonical_dispatched = True
                    logger.debug(
                        "create_task: routed via CommandRouter.route_envelope task_id=%s", task_id
                    )
            except Exception as _router_err:
                logger.debug(
                    "create_task: CommandRouter.route_envelope unavailable (%s), "
                    "falling back to compat send_to_device",
                    _router_err,
                )

            if not canonical_dispatched:
                # Compat fallback: direct send_to_device — emit structured guardrail
                try:
                    from core.orchestration_authority.legacy_paths import emit_legacy_guardrail

                    emit_legacy_guardrail(
                        caller="core.routes.tasks.create_task",
                        trace_id=trace_id,
                        override_recommendation=(
                            "Use POST /api/v1/command/unified or "
                            "CommandRouter.route_envelope() for canonical control-plane "
                            "routing."
                        ),
                    )
                except Exception as _guardrail_exc:
                    logger.debug("create_task: legacy guardrail emission skipped - %s", _guardrail_exc)

                await connection_manager.send_to_device(req.device_id, {
                    "type": "task",
                    "task_id": task_id,
                    "trace_id": trace_id,
                    "task_type": req.task_type,
                    "payload": req.payload
                })
                task["status"] = "sent"
                task["dispatch_authority"] = "compat_route_adapter"

        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "trace_id": trace_id,
            "status": task["status"]
        })

    @router.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str):
        """获取任务状态"""
        if task_id in task_queue:
            return JSONResponse(task_queue[task_id])
        raise HTTPException(status_code=404, detail="任务未找到")

    @router.get("/api/v1/tasks")
    async def list_tasks(status: str = None, limit: int = 50):
        """列出任务"""
        tasks = list(task_queue.values())
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return JSONResponse({
            "tasks": tasks[:limit],
            "total": len(tasks)
        })

    @router.post("/api/v1/tasks/{task_id}/result")
    async def submit_task_result(task_id: str, payload: Optional[TaskResultPayload] = None):
        """提交任务结果（设备回调）.

        Accepts an optional JSON body with a ``status`` field from the
        Android/device execution taxonomy.  The status is normalised to the
        canonical V2 vocabulary before being written — a failed or cancelled
        result is **not** recorded as ``completed``.

        State consistency (PR-893)
        --------------------------
        After updating ``task_queue`` the handler also advances the
        :class:`~core.canonical_task.CanonicalTaskRuntime` lifecycle to the
        matching terminal state so that both state surfaces agree.  Without
        this step the REST result path could leave ``CanonicalTaskRuntime`` in
        a stale intermediate lifecycle (e.g. ``dispatched``) while
        ``task_queue`` already reflects ``completed`` or ``failed``,
        creating the dual-track state drift described in PR-893.
        """
        if task_id not in task_queue:
            raise HTTPException(status_code=404, detail="任务未找到")

        raw_status = (payload.status if payload else None)
        canonical_status = _map_result_status(raw_status)

        task_queue[task_id]["status"] = canonical_status
        task_queue[task_id]["completed_at"] = datetime.now().isoformat()
        if payload and payload.result is not None:
            task_queue[task_id]["result"] = payload.result

        # PR-893: sync CanonicalTaskRuntime to the same terminal state so the
        # two authority surfaces do not drift apart.
        try:
            from core.canonical_task import get_canonical_task_runtime, TaskLifecycle
            _runtime = get_canonical_task_runtime()
            _status_lower = canonical_status.lower()
            if _status_lower == "failed":
                _target = TaskLifecycle.FAILED
            elif _status_lower == "cancelled":
                _target = TaskLifecycle.CANCELLED
            elif _status_lower == "degraded":
                _target = TaskLifecycle.DEGRADED
            else:
                _target = TaskLifecycle.COMPLETED
            _runtime.update_lifecycle(task_id, _target)
            logger.debug(
                "submit_task_result: CanonicalTaskRuntime synced task_id=%s lifecycle=%s",
                task_id, _target.value,
            )
        except Exception as _sync_err:
            logger.warning(
                "submit_task_result: CanonicalTaskRuntime sync failed task_id=%s error=%s — "
                "task_queue was updated but CanonicalTaskRuntime lifecycle may be stale",
                task_id, _sync_err,
            )

        return {"success": True, "status": canonical_status}

    @router.delete("/api/v1/tasks/{task_id}/cancel")
    @router.post("/api/v1/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        """取消任务 (幂等 — 重复取消同一 task_id 安全).

        同时向 OpenClawd cancel_registry 注册取消，确保进行中的
        goal_execution / parallel_subtask 在下一个检查点终止。
        """
        already_terminal = False

        # Mark in task_queue if present
        if task_id in task_queue:
            current_status = task_queue[task_id].get("status", "")
            if current_status in ("completed", "failed", "cancelled"):
                already_terminal = True
            else:
                task_queue[task_id]["status"] = "cancelled"
                task_queue[task_id]["cancelled_at"] = datetime.now().isoformat()

        # Register cancellation in OpenClawd (idempotent)
        try:
            from core.openclawd import get_openclawd
            clawd = get_openclawd()
            clawd.cancel_task(task_id)
        except Exception as _e:
            logger.warning(
                "cancel_task: OpenClawd cancel_registry update failed — "
                "task_queue status was updated but in-flight goal_execution "
                "may not be interrupted immediately: %s",
                _e,
            )

        if already_terminal:
            return JSONResponse({
                "success": True,
                "task_id": task_id,
                "message": f"任务 {task_id} 已处于终态，取消为幂等操作",
                "idempotent": True,
            })

        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "message": f"任务 {task_id} 已标记为取消",
            "idempotent": False,
        })

    @router.delete("/api/v1/tasks/groups/{group_id}/cancel")
    @router.post("/api/v1/tasks/groups/{group_id}/cancel")
    async def cancel_group(group_id: str):
        """取消整个并行任务组 (幂等).

        向 OpenClawd cancel_registry 注册 group_id，所有属于该组的
        parallel_subtask 在下一个检查点终止。
        """
        try:
            from core.openclawd import get_openclawd
            clawd = get_openclawd()
            newly_cancelled = clawd.cancel_group(group_id)
        except Exception as _e:
            logger.warning("cancel_group: OpenClawd cancel_registry update failed: %s", _e)
            newly_cancelled = False

        return JSONResponse({
            "success": True,
            "group_id": group_id,
            "message": f"任务组 {group_id} 已标记为取消",
            "idempotent": not newly_cancelled,
        })

    return router
