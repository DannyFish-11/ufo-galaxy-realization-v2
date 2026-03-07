"""
UFO Galaxy - Task Routes
==========================

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

logger = logging.getLogger("UFO-Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create task management routes router."""
    router = APIRouter()

    @router.post("/api/v1/tasks")
    async def create_task(req: TaskRequest):
        """创建任务"""
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
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
                "task_type": req.task_type,
                "payload": req.payload
            })
            task["status"] = "sent"

        return JSONResponse({
            "success": True,
            "task_id": task_id,
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

    return router
