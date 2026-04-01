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

Routes:
  POST /api/v1/tasks                      - 创建任务
  GET  /api/v1/tasks/{task_id}            - 任务状态
  GET  /api/v1/tasks                      - 任务列表
  POST /api/v1/tasks/{task_id}/result     - 提交任务结果
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from core.routes._shared import connection_manager, task_queue
from core.routes._models import TaskRequest

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create task management routes router."""
    router = APIRouter()

    @router.post("/api/v1/tasks")
    async def create_task(req: TaskRequest):
        """创建任务"""
        task_id = str(uuid.uuid4())
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
            await connection_manager.send_to_device(req.device_id, {
                "type": "task",
                "task_id": task_id,
                "trace_id": trace_id,
                "task_type": req.task_type,
                "payload": req.payload
            })
            task["status"] = "sent"

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
    async def submit_task_result(task_id: str):
        """提交任务结果（设备回调）"""
        if task_id in task_queue:
            task_queue[task_id]["status"] = "completed"
            task_queue[task_id]["completed_at"] = datetime.now().isoformat()
            return {"success": True}
        raise HTTPException(status_code=404, detail="任务未找到")

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
