"""
Node 110 - SmartOrchestrator (智能编排节点)
提供任务编排、工作流管理和智能调度能力
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import heapq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 110 - SmartOrchestrator", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """任务优先级"""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class WorkflowStatus(str, Enum):
    """工作流状态"""
    DRAFT = "draft"
    ACTIVE = "active"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"


@dataclass
class OrchestratedTask:
    """编排任务"""
    task_id: str
    name: str
    task_type: str
    priority: TaskPriority
    status: TaskStatus
    payload: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    assigned_node: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 300  # 秒
    
    def __lt__(self, other):
        priority_order = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
            TaskPriority.BACKGROUND: 4
        }
        return priority_order[self.priority] < priority_order[other.priority]


@dataclass
class WorkflowStep:
    """工作流步骤"""
    step_id: str
    name: str
    task_type: str
    config: Dict[str, Any]
    next_steps: List[str] = field(default_factory=list)
    condition: Optional[str] = None  # 条件表达式
    on_error: str = "fail"  # fail, skip, retry


@dataclass
class Workflow:
    """工作流定义"""
    workflow_id: str
    name: str
    description: str
    steps: Dict[str, WorkflowStep]
    entry_point: str
    status: WorkflowStatus = WorkflowStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.now)
    variables: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowExecution:
    """工作流执行实例"""
    execution_id: str
    workflow_id: str
    status: WorkflowStatus
    current_step: Optional[str]
    completed_steps: List[str] = field(default_factory=list)
    step_results: Dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeCapability:
    """节点能力"""
    node_id: str
    capabilities: List[str]
    current_load: float  # 0-1
    max_concurrent: int
    active_tasks: int
    last_heartbeat: datetime = field(default_factory=datetime.now)


class SmartOrchestrator:
    """智能编排器"""
    
    def __init__(self):
        self.tasks: Dict[str, OrchestratedTask] = {}
        self.task_queue: List[OrchestratedTask] = []
        self.workflows: Dict[str, Workflow] = {}
        self.executions: Dict[str, WorkflowExecution] = {}
        self.nodes: Dict[str, NodeCapability] = {}
        self.is_running = False
        self._lock = asyncio.Lock()
        self._task_handlers: Dict[str, Callable] = {}
    
    def register_node(self, node: NodeCapability) -> bool:
        """注册执行节点"""
        self.nodes[node.node_id] = node
        logger.info(f"Registered node: {node.node_id} with capabilities: {node.capabilities}")
        return True
    
    def update_node_status(self, node_id: str, load: float, active_tasks: int) -> bool:
        """更新节点状态"""
        if node_id not in self.nodes:
            return False
        self.nodes[node_id].current_load = load
        self.nodes[node_id].active_tasks = active_tasks
        self.nodes[node_id].last_heartbeat = datetime.now()
        return True
    
    async def submit_task(self, task: OrchestratedTask) -> str:
        """提交任务"""
        async with self._lock:
            self.tasks[task.task_id] = task
            
            # 检查依赖
            if self._check_dependencies(task):
                task.status = TaskStatus.QUEUED
                heapq.heappush(self.task_queue, task)
            else:
                task.status = TaskStatus.PENDING
            
            logger.info(f"Task submitted: {task.task_id} ({task.name})")
            return task.task_id
    
    def _check_dependencies(self, task: OrchestratedTask) -> bool:
        """检查任务依赖是否满足"""
        for dep_id in task.dependencies:
            if dep_id not in self.tasks:
                return False
            dep_task = self.tasks[dep_id]
            if dep_task.status != TaskStatus.COMPLETED:
                return False
        return True
    
    def _find_best_node(self, task: OrchestratedTask) -> Optional[str]:
        """找到最佳执行节点"""
        candidates = []
        for node_id, node in self.nodes.items():
            # 检查节点是否在线
            if (datetime.now() - node.last_heartbeat).total_seconds() > 60:
                continue
            
            # 检查能力匹配
            if task.task_type not in node.capabilities and "*" not in node.capabilities:
                continue
            
            # 检查负载
            if node.active_tasks >= node.max_concurrent:
                continue
            
            # 计算分数（负载越低越好）
            score = 1 - node.current_load
            candidates.append((score, node_id))
        
        if not candidates:
            return None
        
        candidates.sort(reverse=True)
        return candidates[0][1]
    
    async def schedule_tasks(self):
        """调度任务"""
        async with self._lock:
            # 检查待处理任务的依赖
            for task in list(self.tasks.values()):
                if task.status == TaskStatus.PENDING:
                    if self._check_dependencies(task):
                        task.status = TaskStatus.QUEUED
                        heapq.heappush(self.task_queue, task)
            
            # 分配任务到节点
            while self.task_queue:
                task = heapq.heappop(self.task_queue)
                
                if task.status != TaskStatus.QUEUED:
                    continue
                
                node_id = self._find_best_node(task)
                if node_id:
                    task.assigned_node = node_id
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now()
                    self.nodes[node_id].active_tasks += 1
                    
                    logger.info(f"Task {task.task_id} assigned to node {node_id}")
                    
                    # 执行任务
                    asyncio.create_task(self._execute_task(task))
                else:
                    # 没有可用节点，放回队列
                    heapq.heappush(self.task_queue, task)
                    break
    
    async def _execute_task(self, task: OrchestratedTask):
        """执行任务"""
        try:
            # 查找任务处理器
            handler = self._task_handlers.get(task.task_type)
            if handler:
                result = await handler(task.payload)
                task.result = result
                task.status = TaskStatus.COMPLETED
            else:
                # 模拟执行
                await asyncio.sleep(1)
                task.result = {"status": "simulated", "task_type": task.task_type}
                task.status = TaskStatus.COMPLETED
            
            task.completed_at = datetime.now()
            logger.info(f"Task {task.task_id} completed")
            
        except Exception as e:
            task.error = str(e)
            task.retry_count += 1
            
            if task.retry_count < task.max_retries:
                task.status = TaskStatus.QUEUED
                heapq.heappush(self.task_queue, task)
                logger.warning(f"Task {task.task_id} failed, retrying ({task.retry_count}/{task.max_retries})")
            else:
                task.status = TaskStatus.FAILED
                logger.error(f"Task {task.task_id} failed permanently: {e}")
        
        finally:
            # 更新节点状态
            if task.assigned_node and task.assigned_node in self.nodes:
                self.nodes[task.assigned_node].active_tasks -= 1
    
    def register_task_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self._task_handlers[task_type] = handler
    
    # 工作流管理
    def create_workflow(self, workflow: Workflow) -> str:
        """创建工作流"""
        self.workflows[workflow.workflow_id] = workflow
        logger.info(f"Workflow created: {workflow.workflow_id} ({workflow.name})")
        return workflow.workflow_id
    
    async def execute_workflow(self, workflow_id: str, context: Dict[str, Any] = None) -> str:
        """执行工作流"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow not found: {workflow_id}")
        
        workflow = self.workflows[workflow_id]
        
        execution = WorkflowExecution(
            execution_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            current_step=workflow.entry_point,
            context=context or {}
        )
        
        self.executions[execution.execution_id] = execution
        
        # 启动工作流执行
        asyncio.create_task(self._run_workflow(execution))
        
        return execution.execution_id
    
    async def _run_workflow(self, execution: WorkflowExecution):
        """运行工作流"""
        workflow = self.workflows[execution.workflow_id]
        
        try:
            while execution.current_step:
                step = workflow.steps.get(execution.current_step)
                if not step:
                    raise ValueError(f"Step not found: {execution.current_step}")
                
                # 检查条件
                if step.condition and not self._evaluate_condition(step.condition, execution.context):
                    # 跳过此步骤
                    execution.completed_steps.append(step.step_id)
                    execution.current_step = step.next_steps[0] if step.next_steps else None
                    continue
                
                # 创建并执行任务
                task = OrchestratedTask(
                    task_id=f"{execution.execution_id}_{step.step_id}",
                    name=step.name,
                    task_type=step.task_type,
                    priority=TaskPriority.NORMAL,
                    status=TaskStatus.PENDING,
                    payload={**step.config, **execution.context}
                )
                
                await self.submit_task(task)
                
                # 等待任务完成
                while task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    await asyncio.sleep(0.5)
                
                if task.status == TaskStatus.FAILED:
                    if step.on_error == "fail":
                        raise Exception(f"Step {step.step_id} failed: {task.error}")
                    elif step.on_error == "skip":
                        pass
                    elif step.on_error == "retry":
                        continue
                
                # 保存结果
                execution.step_results[step.step_id] = task.result
                execution.completed_steps.append(step.step_id)
                
                # 更新上下文
                if task.result:
                    execution.context.update(task.result if isinstance(task.result, dict) else {"result": task.result})
                
                # 确定下一步
                execution.current_step = step.next_steps[0] if step.next_steps else None
            
            execution.status = WorkflowStatus.COMPLETED
            execution.completed_at = datetime.now()
            logger.info(f"Workflow execution {execution.execution_id} completed")
            
        except Exception as e:
            execution.status = WorkflowStatus.FAILED
            execution.error = str(e)
            execution.completed_at = datetime.now()
            logger.error(f"Workflow execution {execution.execution_id} failed: {e}")
    
    def _evaluate_condition(self, condition: str, context: Dict) -> bool:
        """评估条件"""
        try:
            return eval(condition, {"__builtins__": {}}, context)
        except Exception:
            return True
    
    async def start(self):
        """启动编排器"""
        self.is_running = True
        logger.info("Smart Orchestrator started")
        
        while self.is_running:
            await self.schedule_tasks()
            await asyncio.sleep(1)
    
    def stop(self):
        """停止编排器"""
        self.is_running = False
        logger.info("Smart Orchestrator stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """获取编排器状态"""
        return {
            "is_running": self.is_running,
            "total_tasks": len(self.tasks),
            "queued_tasks": len(self.task_queue),
            "running_tasks": sum(1 for t in self.tasks.values() if t.status == TaskStatus.RUNNING),
            "completed_tasks": sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED),
            "failed_tasks": sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED),
            "workflows": len(self.workflows),
            "active_executions": sum(1 for e in self.executions.values() if e.status == WorkflowStatus.RUNNING),
            "registered_nodes": len(self.nodes)
        }


# 全局实例
orchestrator = SmartOrchestrator()


# API 模型
class SubmitTaskRequest(BaseModel):
    name: str
    task_type: str
    priority: str = "normal"
    payload: Dict[str, Any] = {}
    dependencies: List[str] = []
    timeout: int = 300

class RegisterNodeRequest(BaseModel):
    node_id: str
    capabilities: List[str]
    max_concurrent: int = 5

class CreateWorkflowRequest(BaseModel):
    name: str
    description: str
    steps: Dict[str, Dict[str, Any]]
    entry_point: str

class ExecuteWorkflowRequest(BaseModel):
    workflow_id: str
    context: Dict[str, Any] = {}


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_110_SmartOrchestrator"}

@app.get("/status")
async def get_status():
    return orchestrator.get_status()

@app.post("/tasks")
async def submit_task(request: SubmitTaskRequest):
    task = OrchestratedTask(
        task_id=str(uuid.uuid4()),
        name=request.name,
        task_type=request.task_type,
        priority=TaskPriority(request.priority),
        status=TaskStatus.PENDING,
        payload=request.payload,
        dependencies=request.dependencies,
        timeout=request.timeout
    )
    task_id = await orchestrator.submit_task(task)
    return {"task_id": task_id}

@app.get("/tasks")
async def list_tasks(status: Optional[str] = None, limit: int = 50):
    tasks = list(orchestrator.tasks.values())
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    tasks = sorted(tasks, key=lambda t: t.created_at, reverse=True)[:limit]
    return [asdict(t) for t in tasks]

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in orchestrator.tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return asdict(orchestrator.tasks[task_id])

@app.post("/nodes")
async def register_node(request: RegisterNodeRequest):
    node = NodeCapability(
        node_id=request.node_id,
        capabilities=request.capabilities,
        current_load=0.0,
        max_concurrent=request.max_concurrent,
        active_tasks=0
    )
    orchestrator.register_node(node)
    return {"success": True}

@app.get("/nodes")
async def list_nodes():
    return {nid: asdict(n) for nid, n in orchestrator.nodes.items()}

@app.post("/workflows")
async def create_workflow(request: CreateWorkflowRequest):
    steps = {}
    for step_id, step_config in request.steps.items():
        steps[step_id] = WorkflowStep(
            step_id=step_id,
            name=step_config.get("name", step_id),
            task_type=step_config.get("task_type", "generic"),
            config=step_config.get("config", {}),
            next_steps=step_config.get("next_steps", []),
            condition=step_config.get("condition"),
            on_error=step_config.get("on_error", "fail")
        )
    
    workflow = Workflow(
        workflow_id=str(uuid.uuid4()),
        name=request.name,
        description=request.description,
        steps=steps,
        entry_point=request.entry_point
    )
    workflow_id = orchestrator.create_workflow(workflow)
    return {"workflow_id": workflow_id}

@app.get("/workflows")
async def list_workflows():
    return {wid: {"name": w.name, "description": w.description, "status": w.status.value} 
            for wid, w in orchestrator.workflows.items()}

@app.post("/workflows/execute")
async def execute_workflow(request: ExecuteWorkflowRequest):
    try:
        execution_id = await orchestrator.execute_workflow(request.workflow_id, request.context)
        return {"execution_id": execution_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/executions")
async def list_executions(limit: int = 50):
    executions = sorted(orchestrator.executions.values(), key=lambda e: e.started_at, reverse=True)[:limit]
    return [asdict(e) for e in executions]

@app.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    if execution_id not in orchestrator.executions:
        raise HTTPException(status_code=404, detail="Execution not found")
    return asdict(orchestrator.executions[execution_id])

@app.post("/start")
async def start_orchestrator(background_tasks: BackgroundTasks):
    if not orchestrator.is_running:
        background_tasks.add_task(orchestrator.start)
        return {"status": "started"}
    return {"status": "already_running"}

@app.post("/stop")
async def stop_orchestrator():
    orchestrator.stop()
    return {"status": "stopped"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8110)
