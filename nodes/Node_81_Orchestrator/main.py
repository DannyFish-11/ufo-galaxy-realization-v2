"""
Node 81: Orchestrator - 统一编排器
智能任务编排、工作流管理、节点协调

架构说明
--------
该节点现在是 ConstellationRuntime 的**从属组件**，而非顶级编排入口。
``/workflow`` 端点首先委托给 ConstellationRuntime.run()；仅当
ConstellationRuntime 不可用时才回退到本地工作流引擎。
``/decompose`` 保留为纯规划/分解辅助模块，可由 ConstellationRuntime 调用。

功能：
1. 任务分解 - 将复杂任务分解为子任务（辅助角色）
2. 节点选择 - 智能选择最合适的节点
3. 工作流编排 - 管理任务执行流程（降级策略）
4. 结果聚合 - 汇总各节点结果
5. 错误处理 - 自动重试和降级

集成：
- 与 Node 79 (Local LLM) 配合实现智能任务分解
- 与 Node 80 (Memory System) 配合实现工作流记忆
- 与所有节点协调执行任务
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx
from nodes.common.cors_config import get_cors_origins


def _safe_condition(condition: str, context: dict) -> bool:
    """Safely evaluate a simple condition string without eval().

    Supports: ``key == value``, ``key != value``, ``key > value``,
    ``key in list_val``, plain key truthiness check.
    Falls back to True if the condition cannot be parsed.
    """
    import ast as _ast
    import operator
    import re

    condition = condition.strip()
    if not condition:
        return True

    ops = {"==": operator.eq, "!=": operator.ne, ">=": operator.ge,
           "<=": operator.le, ">": operator.gt, "<": operator.lt}

    for op_str, op_func in sorted(ops.items(), key=lambda x: -len(x[0])):
        if op_str in condition:
            left, right = condition.split(op_str, 1)
            left, right = left.strip(), right.strip()
            lval = context.get(left, left)
            try:
                rval = _ast.literal_eval(right)
            except (ValueError, SyntaxError):
                rval = context.get(right, right)
            try:
                return op_func(lval, rval)
            except TypeError:
                return False

    # Simple truthiness: check if context[condition] is truthy
    return bool(context.get(condition, True))


# =============================================================================
# Configuration
# =============================================================================

from core.port_config import get_node_port

NODE_ID = os.getenv("NODE_ID", "81")
NODE_NAME = os.getenv("NODE_NAME", "Orchestrator")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 节点服务地址
NODE_SERVICES = {
    "00": f"http://localhost:{get_node_port('Node_00_StateMachine')}",  # StateMachine
    "01": f"http://localhost:{get_node_port('Node_01_OneAPI')}",  # OneAPI
    "02": f"http://localhost:{get_node_port('Node_02_Tasker')}",  # Tasker
    "79": f"http://localhost:{get_node_port('Node_79_LocalLLM')}",  # LocalLLM
    "80": f"http://localhost:{get_node_port('Node_80_MemorySystem')}",  # MemorySystem
    "22": f"http://localhost:{get_node_port('Node_22_BraveSearch')}",  # BraveSearch
    "24": f"http://localhost:{get_node_port('Node_24_Weather')}",  # Weather
    "06": f"http://localhost:{get_node_port('Node_06_Filesystem')}",  # Filesystem
    "12": f"http://localhost:{get_node_port('Node_12_Postgres')}",  # Postgres
    "13": f"http://localhost:{get_node_port('Node_13_SQLite')}",  # SQLite
}

# 超时配置
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskType(str, Enum):
    SIMPLE = "simple"          # 单节点任务
    SEQUENTIAL = "sequential"  # 顺序执行
    PARALLEL = "parallel"      # 并行执行
    CONDITIONAL = "conditional" # 条件执行
    LOOP = "loop"              # 循环执行

class NodeCall(BaseModel):
    node_id: str
    endpoint: str
    method: str = "POST"
    data: Optional[Dict[str, Any]] = {}
    timeout: Optional[int] = DEFAULT_TIMEOUT
    retry: Optional[int] = MAX_RETRIES

class Task(BaseModel):
    task_id: str
    task_type: TaskType
    description: str
    calls: List[NodeCall]
    dependencies: Optional[List[str]] = []
    condition: Optional[str] = None  # Python 表达式
    metadata: Optional[Dict[str, Any]] = {}

class WorkflowRequest(BaseModel):
    workflow_id: Optional[str] = None
    description: str
    tasks: List[Task]
    save_to_memory: bool = True
    user_id: Optional[str] = "default"
    legacy_override: bool = Field(
        False,
        description=(
            "Explicitly enable the legacy fallback path. "
            "When True, the request acknowledges use of the deprecated local workflow engine "
            "when ConstellationRuntime is unavailable. A DEPRECATION GUARDRAIL warning is always logged. "
            "Keep the default (False) for all normal usage."
        ),
    )

class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    duration: Optional[float] = None

class WorkflowResult(BaseModel):
    workflow_id: str
    status: TaskStatus
    tasks: List[TaskResult]
    started_at: str
    completed_at: Optional[str] = None
    duration: Optional[float] = None

# =============================================================================
# Orchestrator Service
# =============================================================================

class OrchestratorService:
    """编排器服务"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=60)
        self.workflows: Dict[str, WorkflowResult] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
    
    async def call_node(self, call: NodeCall) -> Any:
        """调用节点"""
        node_url = NODE_SERVICES.get(call.node_id)
        if not node_url:
            raise HTTPException(status_code=404, detail=f"Node {call.node_id} not found")
        
        url = f"{node_url}{call.endpoint}"
        
        for attempt in range(call.retry):
            try:
                if call.method == "GET":
                    response = await self.http_client.get(url, params=call.data, timeout=call.timeout)
                elif call.method == "POST":
                    response = await self.http_client.post(url, json=call.data, timeout=call.timeout)
                elif call.method == "PUT":
                    response = await self.http_client.put(url, json=call.data, timeout=call.timeout)
                elif call.method == "DELETE":
                    response = await self.http_client.delete(url, timeout=call.timeout)
                else:
                    raise ValueError(f"Unsupported method: {call.method}")
                
                response.raise_for_status()
                return response.json()
            
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{call.retry} failed for Node {call.node_id}: {e}")
                
                if attempt == call.retry - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)  # 指数回退
        
        return None
    
    async def execute_simple_task(self, task: Task) -> TaskResult:
        """执行简单任务（单节点）"""
        start_time = datetime.now()
        
        try:
            if len(task.calls) != 1:
                raise ValueError("Simple task must have exactly one call")
            
            call = task.calls[0]
            result = await self.call_node(call)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                started_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                duration=duration
            )
        
        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.error(f"Task {task.task_id} failed: {e}")
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                duration=duration
            )
    
    async def execute_sequential_task(self, task: Task) -> TaskResult:
        """执行顺序任务"""
        start_time = datetime.now()
        results = []
        
        try:
            for call in task.calls:
                result = await self.call_node(call)
                results.append(result)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                result=results,
                started_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                duration=duration
            )
        
        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.error(f"Task {task.task_id} failed: {e}")
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                result=results,  # 返回已完成的部分
                started_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                duration=duration
            )
    
    async def execute_parallel_task(self, task: Task) -> TaskResult:
        """执行并行任务"""
        start_time = datetime.now()
        
        try:
            # 并行执行所有调用
            tasks = [self.call_node(call) for call in task.calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 检查是否有错误
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                raise errors[0]
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                result=results,
                started_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                duration=duration
            )
        
        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.error(f"Task {task.task_id} failed: {e}")
            
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=start_time.isoformat(),
                completed_at=end_time.isoformat(),
                duration=duration
            )
    
    async def execute_task(self, task: Task, context: Dict[str, Any] = None) -> TaskResult:
        """执行任务"""
        logger.info(f"Executing task: {task.task_id} ({task.task_type})")
        
        # 检查条件
        if task.condition and context:
            try:
                # 安全条件评估（不使用 eval）
                if not _safe_condition(task.condition, context):
                    logger.info(f"Task {task.task_id} skipped (condition not met)")
                    return TaskResult(
                        task_id=task.task_id,
                        status=TaskStatus.COMPLETED,
                        result={"skipped": True, "reason": "condition not met"},
                        started_at=datetime.now().isoformat()
                    )
            except Exception as e:
                logger.error(f"Condition evaluation failed: {e}")
        
        # 根据任务类型执行
        if task.task_type == TaskType.SIMPLE:
            return await self.execute_simple_task(task)
        elif task.task_type == TaskType.SEQUENTIAL:
            return await self.execute_sequential_task(task)
        elif task.task_type == TaskType.PARALLEL:
            return await self.execute_parallel_task(task)
        else:
            raise ValueError(f"Unsupported task type: {task.task_type}")
    
    async def execute_workflow(self, request: WorkflowRequest) -> WorkflowResult:
        """执行工作流"""
        workflow_id = request.workflow_id or f"wf_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        start_time = datetime.now()
        
        logger.info(f"Starting workflow: {workflow_id}")
        
        # 初始化工作流结果
        workflow_result = WorkflowResult(
            workflow_id=workflow_id,
            status=TaskStatus.RUNNING,
            tasks=[],
            started_at=start_time.isoformat()
        )
        
        self.workflows[workflow_id] = workflow_result
        
        try:
            # 构建依赖图
            task_map = {task.task_id: task for task in request.tasks}
            completed_tasks: Dict[str, TaskResult] = {}
            context = {}
            
            # 执行任务（简单的拓扑排序）
            remaining_tasks = set(task_map.keys())
            
            while remaining_tasks:
                # 找到所有依赖已满足的任务
                ready_tasks = [
                    task_id for task_id in remaining_tasks
                    if all(dep in completed_tasks for dep in task_map[task_id].dependencies)
                ]
                
                if not ready_tasks:
                    raise ValueError("Circular dependency detected or missing dependencies")
                
                # 执行就绪的任务
                for task_id in ready_tasks:
                    task = task_map[task_id]
                    result = await self.execute_task(task, context)
                    
                    completed_tasks[task_id] = result
                    workflow_result.tasks.append(result)
                    
                    # 更新上下文
                    if result.status == TaskStatus.COMPLETED and result.result:
                        context[task_id] = result.result
                    
                    remaining_tasks.remove(task_id)
            
            # 完成工作流
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            workflow_result.status = TaskStatus.COMPLETED
            workflow_result.completed_at = end_time.isoformat()
            workflow_result.duration = duration
            
            logger.info(f"Workflow {workflow_id} completed in {duration:.2f}s")
            
            # 保存到记忆系统
            if request.save_to_memory:
                try:
                    await self.http_client.post(
                        f"{NODE_SERVICES['80']}/memory",
                        json={
                            "content": f"Workflow: {request.description}",
                            "memory_type": "long_term",
                            "tags": ["workflow", workflow_id],
                            "metadata": {
                                "workflow_id": workflow_id,
                                "duration": duration,
                                "task_count": len(request.tasks)
                            },
                            "user_id": request.user_id
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to save workflow to memory: {e}")
            
            return workflow_result
        
        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.error(f"Workflow {workflow_id} failed: {e}")
            
            workflow_result.status = TaskStatus.FAILED
            workflow_result.completed_at = end_time.isoformat()
            workflow_result.duration = duration
            
            return workflow_result
    
    async def decompose_task(self, description: str) -> List[Task]:
        """使用 LLM 分解任务"""
        try:
            response = await self.http_client.post(
                f"{NODE_SERVICES['79']}/generate",
                json={
                    "prompt": f"""分解以下任务为具体的执行步骤，返回 JSON 格式：

任务描述：{description}

可用节点：
- Node 22: BraveSearch (搜索)
- Node 24: Weather (天气)
- Node 06: Filesystem (文件操作)
- Node 12: Postgres (数据库)
- Node 13: SQLite (数据库)

返回格式：
{{
  "tasks": [
    {{
      "task_id": "task_1",
      "task_type": "simple",
      "description": "...",
      "calls": [
        {{
          "node_id": "22",
          "endpoint": "/search",
          "method": "POST",
          "data": {{"query": "..."}}
        }}
      ]
    }}
  ]
}}

只返回 JSON，不要其他内容。""",
                    "task_type": "complex"
                }
            )
            
            result = response.json()
            tasks_json = json.loads(result["response"])
            
            tasks = [Task(**task_data) for task_data in tasks_json["tasks"]]
            return tasks
        
        except Exception as e:
            logger.error(f"Task decomposition failed: {e}")
            raise HTTPException(status_code=500, detail=f"Task decomposition failed: {e}")
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()

# =============================================================================
# FastAPI Application
# =============================================================================

orchestrator = OrchestratorService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.warning(
        "DEPRECATION [Node_81_Orchestrator]: This node is a legacy helper/subordinate "
        "orchestrator. The /workflow endpoint delegates to ConstellationRuntime. "
        "Do not invoke this node as a primary system entry point. "
        "Use core.constellation_runtime.get_constellation_runtime() instead."
    )
    logger.info("Starting Node 81: Orchestrator")
    yield
    await orchestrator.close()
    logger.info("Node 81 shutdown complete")

app = FastAPI(
    title="Node 81: Orchestrator",
    description="统一编排器 - 智能任务编排和工作流管理",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "Node 81: Orchestrator",
        "status": "running",
        "features": [
            "Task decomposition",
            "Workflow orchestration",
            "Node coordination",
            "Error handling"
        ],
        "task_types": [t.value for t in TaskType]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "active_workflows": len(orchestrator.workflows),
        "running_tasks": len(orchestrator.running_tasks),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def get_status():
    return {"status": "ok", "node_id": NODE_ID, "name": NODE_NAME, "timestamp": __import__("datetime").datetime.now().isoformat()}

@app.post("/workflow")
async def execute_workflow(request: WorkflowRequest, background_tasks: BackgroundTasks):
    """执行工作流

    委托链路：
    1. 首先尝试 ConstellationRuntime.run()（系统级统一编排入口）
    2. 若 ConstellationRuntime 不可用则回退到本地工作流引擎

    返回 WorkflowResult 兼容结构，确保向后兼容。

    .. deprecated::
        直接调用此端点作为主编排入口已废弃。
        请使用 ConstellationRuntime 作为统一入口。
        若需要显式使用旧版降级路径，请在请求中设置 ``legacy_override=True``。
    """
    # Guardrail: warn if caller opted into legacy override
    if request.legacy_override:
        logger.warning(
            "DEPRECATION GUARDRAIL [Node_81]: legacy_override=True received. "
            "Caller is explicitly bypassing ConstellationRuntime. "
            "workflow=%r  — migrate to ConstellationRuntime to suppress this warning.",
            request.description[:80],
        )

    # ── 1. ConstellationRuntime 主路径 ──────────────────────────────────
    try:
        from core.constellation_runtime import (
            get_constellation_runtime,
            wrap_as_orchestration_response,
        )
        runtime = get_constellation_runtime()
        cr_result = await runtime.run(
            task_description=request.description,
            user_id=request.user_id or "default",
        )
        # Shape ConstellationRuntime result into WorkflowResult-compatible response
        shaped = wrap_as_orchestration_response(cr_result)
        cr_status = TaskStatus.COMPLETED if cr_result.get("success") else TaskStatus.FAILED
        now = datetime.now().isoformat()
        return WorkflowResult(
            workflow_id=shaped["task_id"],
            status=cr_status,
            tasks=[
                TaskResult(
                    task_id=shaped["task_id"],
                    status=cr_status,
                    result=shaped["result"],
                    started_at=now,
                    completed_at=now,
                )
            ],
            started_at=now,
            completed_at=now,
        )
    except Exception as cr_exc:
        logger.warning(
            "ConstellationRuntime 不可用，回退到本地工作流引擎: %s", cr_exc
        )

    # ── 2. 本地工作流引擎降级路径 ────────────────────────────────────────
    # Guardrail: log structured warning about legacy fallback
    if not request.legacy_override:
        logger.warning(
            "DEPRECATION GUARDRAIL [Node_81]: ConstellationRuntime unavailable and "
            "legacy_override=False. Falling back to legacy local workflow engine. "
            "Set legacy_override=True in your request to acknowledge this deprecated path. "
            "workflow=%r",
            request.description[:80],
        )
    result = await orchestrator.execute_workflow(request)
    return result

@app.post("/decompose")
async def decompose_task(description: str):
    """分解任务"""
    tasks = await orchestrator.decompose_task(description)
    return {
        "description": description,
        "tasks": [t.dict() for t in tasks]
    }

@app.get("/workflow/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """获取工作流状态"""
    workflow = orchestrator.workflows.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow

@app.get("/workflows")
async def list_workflows():
    """列出所有工作流"""
    return {
        "workflows": list(orchestrator.workflows.values()),
        "count": len(orchestrator.workflows)
    }

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)
