"""
galaxy_gateway/routes/tasks.py — Task management and command dispatch routes.

Routes:
  POST   /api/tasks              - Submit a new task
  GET    /api/tasks/{task_id}    - Get task status
  GET    /api/tasks              - List all tasks
  DELETE /api/tasks/{task_id}    - Cancel a task
  POST   /api/commands           - Send a direct command to a device
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from galaxy_gateway.dependencies import get_task_orchestrator, get_websocket_manager
from galaxy_gateway.orchestrator import TaskPriority
from galaxy_gateway.protocol import AIPMessage, MessageType

try:
    from core.auth import require_auth as _require_auth
except ImportError:
    async def _require_auth():  # type: ignore[misc]
        return {"authenticated": True, "dev_mode": True}

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    user_request: str
    target_device: Optional[str] = None
    priority: str = "normal"
    timeout: int = 300


class CommandRequest(BaseModel):
    device_id: str
    command_type: str  # click, swipe, input, screenshot, etc.
    parameters: dict = {}


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------

_PRIORITY_MAP = {
    "low": TaskPriority.LOW,
    "normal": TaskPriority.NORMAL,
    "high": TaskPriority.HIGH,
    "urgent": TaskPriority.URGENT,
}


@router.post("/api/tasks")
async def submit_task(
    request: TaskRequest,
    auth: dict = Depends(_require_auth),
    orch=Depends(get_task_orchestrator),
):
    """Submit a task for execution."""
    priority = _PRIORITY_MAP.get(request.priority.lower(), TaskPriority.NORMAL)
    task = await orch.submit_task(
        user_request=request.user_request,
        target_device=request.target_device,
        priority=priority,
        timeout=request.timeout,
    )
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "assigned_device": task.assigned_device,
    }


@router.get("/api/tasks/{task_id}")
async def get_task(
    task_id: str,
    auth: dict = Depends(_require_auth),
    orch=Depends(get_task_orchestrator),
):
    """Return task status and results."""
    task = orch.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "user_request": task.user_request,
        "status": task.status.value,
        "assigned_device": task.assigned_device,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
        "results": [r.model_dump() for r in task.results],
    }


@router.get("/api/tasks")
async def get_all_tasks(
    auth: dict = Depends(_require_auth),
    orch=Depends(get_task_orchestrator),
):
    """Return all tasks (truncated summaries)."""
    tasks = orch.get_all_tasks()
    return {
        "total": len(tasks),
        "tasks": [
            {
                "task_id": t.task_id,
                "user_request": t.user_request[:100],
                "status": t.status.value,
                "assigned_device": t.assigned_device,
            }
            for t in tasks
        ],
    }


@router.delete("/api/tasks/{task_id}")
async def cancel_task(
    task_id: str,
    auth: dict = Depends(_require_auth),
    orch=Depends(get_task_orchestrator),
):
    """Cancel a pending or running task."""
    success = await orch.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task")
    return {"status": "cancelled", "task_id": task_id}


# ---------------------------------------------------------------------------
# Command endpoint
# ---------------------------------------------------------------------------

_MSG_TYPE_MAP = {
    "click": MessageType.GUI_CLICK,
    "swipe": MessageType.GUI_SWIPE,
    "input": MessageType.GUI_INPUT,
    "scroll": MessageType.GUI_SCROLL,
    "screenshot": MessageType.GUI_SCREENSHOT,
    "screen_content": MessageType.GUI_SCREEN_CONTENT,
}


@router.post("/api/commands")
async def send_command(
    request: CommandRequest,
    auth: dict = Depends(_require_auth),
    wsm=Depends(get_websocket_manager),
):
    """Send a direct GUI command to a connected device."""
    if not wsm.is_device_connected(request.device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    msg_type = _MSG_TYPE_MAP.get(request.command_type)
    if not msg_type:
        raise HTTPException(
            status_code=400, detail=f"Unknown command type: {request.command_type}"
        )

    message = AIPMessage(
        type=msg_type,
        device_id=request.device_id,
        payload=request.parameters,
    )
    success = await wsm.send_message(request.device_id, message)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send command")
    return {"status": "sent", "message_id": message.message_id}
