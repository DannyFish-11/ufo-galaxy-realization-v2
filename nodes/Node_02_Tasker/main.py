"""
Node 02: Tasker - 任务调度器
=============================
提供任务队列管理、定时任务、任务状态跟踪功能
"""
import os
import json
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import heapq

app = FastAPI(title="Node 02 - Tasker", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(int, Enum):
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0

class Task(BaseModel):
    id: str
    name: str
    command: str
    params: Dict[str, Any] = {}
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_queue: List[tuple] = []  # (priority, created_at, task_id)
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.scheduled_tasks: Dict[str, asyncio.Task] = {}
        self.task_handlers: Dict[str, Callable] = {}
        self._lock = asyncio.Lock()
        self._load_persisted_tasks()

    def _load_persisted_tasks(self):
        """加载持久化的任务"""
        persist_file = os.getenv("TASKER_PERSIST_FILE", "/tmp/tasker_tasks.json")
        if os.path.exists(persist_file):
            try:
                with open(persist_file, 'r') as f:
                    data = json.load(f)
                    for task_data in data.get("tasks", []):
                        task = Task(**task_data)
                        self.tasks[task.id] = task
                        if task.status == TaskStatus.PENDING:
                            heapq.heappush(self.task_queue, (task.priority, task.created_at, task.id))
            except Exception as e:
                print(f"Failed to load persisted tasks: {e}")

    async def _persist_tasks(self):
        """持久化任务"""
        persist_file = os.getenv("TASKER_PERSIST_FILE", "/tmp/tasker_tasks.json")
        try:
            with open(persist_file, 'w') as f:
                json.dump({"tasks": [t.dict() for t in self.tasks.values()]}, f, default=str)
        except Exception as e:
            print(f"Failed to persist tasks: {e}")

    def register_handler(self, command: str, handler: Callable):
        """注册任务处理器"""
        self.task_handlers[command] = handler

    async def create_task(self, name: str, command: str, params: Dict = None, 
                         priority: TaskPriority = TaskPriority.NORMAL,
                         scheduled_at: Optional[datetime] = None) -> Task:
        """创建新任务"""
        async with self._lock:
            task = Task(
                id=str(uuid.uuid4()),
                name=name,
                command=command,
                params=params or {},
                priority=priority,
                created_at=datetime.now(),
                scheduled_at=scheduled_at
            )
            self.tasks[task.id] = task

            if scheduled_at and scheduled_at > datetime.now():
                # 定时任务
                delay = (scheduled_at - datetime.now()).total_seconds()
                self.scheduled_tasks[task.id] = asyncio.create_task(self._run_scheduled(task.id, delay))
            else:
                # 立即执行
                heapq.heappush(self.task_queue, (priority, task.created_at, task.id))

            await self._persist_tasks()
            return task

    async def _run_scheduled(self, task_id: str, delay: float):
        """运行定时任务"""
        await asyncio.sleep(delay)
        async with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                heapq.heappush(self.task_queue, (task.priority, task.created_at, task.id))
                del self.scheduled_tasks[task_id]

    async def execute_task(self, task_id: str) -> Any:
        """执行任务"""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()

        handler = self.task_handlers.get(task.command)
        if not handler:
            task.status = TaskStatus.FAILED
            task.error = f"No handler registered for command: {task.command}"
            task.completed_at = datetime.now()
            return task

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**task.params)
            else:
                result = handler(**task.params)
            task.result = result
            task.status = TaskStatus.COMPLETED
        except Exception as e:
            task.retry_count += 1
            if task.retry_count < task.max_retries:
                task.status = TaskStatus.PENDING
                heapq.heappush(self.task_queue, (task.priority, datetime.now(), task.id))
            else:
                task.status = TaskStatus.FAILED
                task.error = str(e)

        task.completed_at = datetime.now()
        await self._persist_tasks()
        return task

    async def process_queue(self):
        """处理任务队列"""
        while True:
            async with self._lock:
                if self.task_queue:
                    _, _, task_id = heapq.heappop(self.task_queue)
                    if task_id in self.tasks and self.tasks[task_id].status == TaskStatus.PENDING:
                        asyncio.create_task(self.execute_task(task_id))
            await asyncio.sleep(0.1)

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None, limit: int = 100) -> List[Task]:
        tasks = list(self.tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda x: x.created_at, reverse=True)
        return tasks[:limit]

    async def cancel_task(self, task_id: str) -> bool:
        async with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    task.status = TaskStatus.CANCELLED
                    task.completed_at = datetime.now()
                    if task_id in self.scheduled_tasks:
                        self.scheduled_tasks[task_id].cancel()
                        del self.scheduled_tasks[task_id]
                    await self._persist_tasks()
                    return True
        return False

    async def retry_task(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.FAILED:
                    task.status = TaskStatus.PENDING
                    task.retry_count = 0
                    task.error = None
                    heapq.heappush(self.task_queue, (task.priority, datetime.now(), task.id))
                    await self._persist_tasks()
                    return task
        return None

# 全局任务管理器
task_manager = TaskManager()

# 注册示例处理器
async def example_handler(message: str = "Hello"):
    await asyncio.sleep(2)
    return {"message": message, "processed_at": datetime.now().isoformat()}

task_manager.register_handler("example", example_handler)

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "02",
        "name": "Tasker",
        "pending_tasks": len([t for t in task_manager.tasks.values() if t.status == TaskStatus.PENDING]),
        "running_tasks": len([t for t in task_manager.tasks.values() if t.status == TaskStatus.RUNNING]),
        "total_tasks": len(task_manager.tasks),
        "timestamp": datetime.now().isoformat()
    }

class CreateTaskRequest(BaseModel):
    name: str
    command: str
    params: Dict[str, Any] = {}
    priority: TaskPriority = TaskPriority.NORMAL
    scheduled_at: Optional[datetime] = None

@app.post("/tasks")
async def create_task(request: CreateTaskRequest):
    """创建新任务"""
    task = await task_manager.create_task(
        name=request.name,
        command=request.command,
        params=request.params,
        priority=request.priority,
        scheduled_at=request.scheduled_at
    )
    return task

@app.get("/tasks")
async def list_tasks(status: Optional[TaskStatus] = None, limit: int = 100):
    """列出任务"""
    return task_manager.list_tasks(status=status, limit=limit)

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    success = await task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task")
    return {"success": True}

@app.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """重试失败任务"""
    task = await task_manager.retry_task(task_id)
    if not task:
        raise HTTPException(status_code=400, detail="Cannot retry task")
    return task

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务"""
    if task_id in task_manager.tasks:
        await task_manager.cancel_task(task_id)
        del task_manager.tasks[task_id]
        await task_manager._persist_tasks()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Task not found")

@app.get("/handlers")
async def list_handlers():
    """列出已注册的处理器"""
    return {"handlers": list(task_manager.task_handlers.keys())}

@app.on_event("startup")
async def startup():
    """启动后台任务处理"""
    asyncio.create_task(task_manager.process_queue())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
