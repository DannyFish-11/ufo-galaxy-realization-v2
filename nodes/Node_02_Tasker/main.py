"""
Node 02: Tasker Engine
======================
任务串行/并行编排引擎。
支持复杂任务的 DAG 编排、依赖管理、失败重试。

功能：
- 任务 DAG 定义与执行
- 串行/并行任务编排
- 任务依赖管理
- 失败重试与回滚
- 任务状态追踪
"""

import os
import json
import asyncio
import uuid
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 02 - Tasker Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Task Models
# =============================================================================

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

class ExecutionMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DAG = "dag"

@dataclass
class TaskStep:
    """单个任务步骤"""
    id: str
    name: str
    node_id: str  # 目标节点 (e.g., "Node_33_ADB")
    action: str   # 动作名称
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # 依赖的步骤 ID
    retry_count: int = 3
    timeout: int = 60
    on_failure: str = "abort"  # abort, skip, continue
    
@dataclass
class TaskResult:
    """任务结果"""
    step_id: str
    status: TaskStatus
    output: Any = None
    error: str = None
    started_at: datetime = None
    completed_at: datetime = None
    duration_ms: int = 0

@dataclass
class TaskPlan:
    """任务计划"""
    id: str
    name: str
    steps: List[TaskStep]
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    created_at: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING
    results: Dict[str, TaskResult] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)  # 共享上下文

# =============================================================================
# Task Engine
# =============================================================================

class TaskEngine:
    """任务编排引擎"""
    
    def __init__(self):
        self.plans: Dict[str, TaskPlan] = {}
        self.node_endpoints: Dict[str, str] = self._load_node_endpoints()
        self.running_tasks: Set[str] = set()
        
    def _load_node_endpoints(self) -> Dict[str, str]:
        """加载节点端点配置"""
        # 从环境变量或配置文件加载
        base_ip = os.getenv("GALAXY_NET_BASE", "10.88.0")
        return {
            "Node_00": f"http://{base_ip}.0:8000",
            "Node_01": f"http://{base_ip}.1:8001",
            "Node_33": f"http://{base_ip}.33:8033",
            "Node_34": f"http://{base_ip}.34:8034",
            "Node_49": f"http://{base_ip}.49:8049",
            "Node_50": f"http://{base_ip}.50:8050",
            "Node_58": f"http://{base_ip}.58:8058",
            # ... 其他节点
        }
        
    def create_plan(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        mode: str = "sequential"
    ) -> TaskPlan:
        """创建任务计划"""
        plan_id = str(uuid.uuid4())[:8]
        
        task_steps = []
        for i, step in enumerate(steps):
            task_steps.append(TaskStep(
                id=step.get("id", f"step_{i}"),
                name=step.get("name", f"Step {i}"),
                node_id=step.get("node_id", ""),
                action=step.get("action", ""),
                params=step.get("params", {}),
                depends_on=step.get("depends_on", []),
                retry_count=step.get("retry_count", 3),
                timeout=step.get("timeout", 60),
                on_failure=step.get("on_failure", "abort")
            ))
            
        plan = TaskPlan(
            id=plan_id,
            name=name,
            steps=task_steps,
            mode=ExecutionMode(mode)
        )
        
        self.plans[plan_id] = plan
        return plan
        
    async def execute_plan(self, plan_id: str) -> TaskPlan:
        """执行任务计划"""
        plan = self.plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")
            
        if plan_id in self.running_tasks:
            raise ValueError(f"Plan already running: {plan_id}")
            
        self.running_tasks.add(plan_id)
        plan.status = TaskStatus.RUNNING
        
        try:
            if plan.mode == ExecutionMode.SEQUENTIAL:
                await self._execute_sequential(plan)
            elif plan.mode == ExecutionMode.PARALLEL:
                await self._execute_parallel(plan)
            elif plan.mode == ExecutionMode.DAG:
                await self._execute_dag(plan)
                
            # 检查最终状态
            failed = any(r.status == TaskStatus.FAILED for r in plan.results.values())
            plan.status = TaskStatus.FAILED if failed else TaskStatus.SUCCESS
            
        except Exception as e:
            plan.status = TaskStatus.FAILED
            raise
        finally:
            self.running_tasks.discard(plan_id)
            
        return plan
        
    async def _execute_sequential(self, plan: TaskPlan):
        """串行执行"""
        for step in plan.steps:
            result = await self._execute_step(step, plan.context)
            plan.results[step.id] = result
            
            if result.status == TaskStatus.FAILED:
                if step.on_failure == "abort":
                    break
                elif step.on_failure == "skip":
                    continue
                    
    async def _execute_parallel(self, plan: TaskPlan):
        """并行执行"""
        tasks = [
            self._execute_step(step, plan.context)
            for step in plan.steps
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for step, result in zip(plan.steps, results):
            if isinstance(result, Exception):
                plan.results[step.id] = TaskResult(
                    step_id=step.id,
                    status=TaskStatus.FAILED,
                    error=str(result)
                )
            else:
                plan.results[step.id] = result
                
    async def _execute_dag(self, plan: TaskPlan):
        """DAG 执行 (拓扑排序)"""
        # 构建依赖图
        in_degree = defaultdict(int)
        dependents = defaultdict(list)
        step_map = {s.id: s for s in plan.steps}
        
        for step in plan.steps:
            for dep in step.depends_on:
                dependents[dep].append(step.id)
                in_degree[step.id] += 1
                
        # 找到入度为 0 的节点
        ready = [s.id for s in plan.steps if in_degree[s.id] == 0]
        
        while ready:
            # 并行执行所有就绪的步骤
            current_batch = ready[:]
            ready = []
            
            tasks = [
                self._execute_step(step_map[sid], plan.context)
                for sid in current_batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for sid, result in zip(current_batch, results):
                if isinstance(result, Exception):
                    plan.results[sid] = TaskResult(
                        step_id=sid,
                        status=TaskStatus.FAILED,
                        error=str(result)
                    )
                    # 检查失败策略
                    if step_map[sid].on_failure == "abort":
                        return
                else:
                    plan.results[sid] = result
                    
                # 更新依赖
                for dependent in dependents[sid]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        # 检查所有依赖是否成功
                        deps_ok = all(
                            plan.results.get(d, TaskResult(d, TaskStatus.PENDING)).status == TaskStatus.SUCCESS
                            for d in step_map[dependent].depends_on
                        )
                        if deps_ok:
                            ready.append(dependent)
                        else:
                            plan.results[dependent] = TaskResult(
                                step_id=dependent,
                                status=TaskStatus.SKIPPED,
                                error="Dependency failed"
                            )
                            
    async def _execute_step(
        self, 
        step: TaskStep, 
        context: Dict[str, Any]
    ) -> TaskResult:
        """执行单个步骤"""
        result = TaskResult(
            step_id=step.id,
            status=TaskStatus.RUNNING,
            started_at=datetime.now()
        )
        
        # 变量替换
        params = self._substitute_variables(step.params, context)
        
        # 重试循环
        last_error = None
        for attempt in range(step.retry_count):
            try:
                output = await self._call_node(
                    step.node_id,
                    step.action,
                    params,
                    step.timeout
                )
                
                result.status = TaskStatus.SUCCESS
                result.output = output
                result.completed_at = datetime.now()
                result.duration_ms = int(
                    (result.completed_at - result.started_at).total_seconds() * 1000
                )
                
                # 保存输出到上下文
                context[f"{step.id}_output"] = output
                
                return result
                
            except Exception as e:
                last_error = str(e)
                if attempt < step.retry_count - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                    
        result.status = TaskStatus.FAILED
        result.error = last_error
        result.completed_at = datetime.now()
        result.duration_ms = int(
            (result.completed_at - result.started_at).total_seconds() * 1000
        )
        
        return result
        
    def _substitute_variables(
        self, 
        params: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """变量替换 (支持 {{variable}} 语法)"""
        result = {}
        for key, value in params.items():
            if isinstance(value, str) and "{{" in value:
                for ctx_key, ctx_value in context.items():
                    value = value.replace(f"{{{{{ctx_key}}}}}", str(ctx_value))
            result[key] = value
        return result
        
    async def _call_node(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any],
        timeout: int
    ) -> Any:
        """调用节点"""
        # 获取节点端点
        endpoint = self.node_endpoints.get(node_id)
        if not endpoint:
            # 尝试从 Node 00 状态机获取
            endpoint = f"http://localhost:80{node_id.split('_')[1]}"
            
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{endpoint}/mcp/call",
                json={"tool": action, "params": params}
            )
            response.raise_for_status()
            return response.json()
            
    def get_plan(self, plan_id: str) -> Optional[TaskPlan]:
        """获取任务计划"""
        return self.plans.get(plan_id)
        
    def cancel_plan(self, plan_id: str) -> bool:
        """取消任务计划"""
        plan = self.plans.get(plan_id)
        if plan and plan.status == TaskStatus.RUNNING:
            plan.status = TaskStatus.CANCELLED
            return True
        return False

# =============================================================================
# Global Instance
# =============================================================================

engine = TaskEngine()

# =============================================================================
# API Endpoints
# =============================================================================

class CreatePlanRequest(BaseModel):
    name: str
    steps: List[Dict[str, Any]]
    mode: str = "sequential"

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node_id": "02",
        "name": "Tasker Engine",
        "active_plans": len(engine.running_tasks),
        "total_plans": len(engine.plans),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/plans")
async def create_plan(request: CreatePlanRequest):
    """创建任务计划"""
    plan = engine.create_plan(
        name=request.name,
        steps=request.steps,
        mode=request.mode
    )
    return {
        "plan_id": plan.id,
        "name": plan.name,
        "steps": len(plan.steps),
        "mode": plan.mode.value,
        "status": plan.status.value
    }

@app.post("/plans/{plan_id}/execute")
async def execute_plan(plan_id: str, background_tasks: BackgroundTasks):
    """执行任务计划"""
    plan = engine.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    # 异步执行
    background_tasks.add_task(engine.execute_plan, plan_id)
    
    return {
        "plan_id": plan_id,
        "status": "started",
        "message": "Plan execution started in background"
    }

@app.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    """获取任务计划状态"""
    plan = engine.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    return {
        "plan_id": plan.id,
        "name": plan.name,
        "status": plan.status.value,
        "mode": plan.mode.value,
        "steps": [
            {
                "id": s.id,
                "name": s.name,
                "node_id": s.node_id,
                "action": s.action,
                "status": plan.results.get(s.id, TaskResult(s.id, TaskStatus.PENDING)).status.value,
                "output": plan.results.get(s.id, TaskResult(s.id, TaskStatus.PENDING)).output,
                "error": plan.results.get(s.id, TaskResult(s.id, TaskStatus.PENDING)).error
            }
            for s in plan.steps
        ],
        "created_at": plan.created_at.isoformat()
    }

@app.post("/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str):
    """取消任务计划"""
    if engine.cancel_plan(plan_id):
        return {"status": "cancelled"}
    raise HTTPException(status_code=400, detail="Cannot cancel plan")

@app.get("/plans")
async def list_plans():
    """列出所有任务计划"""
    return {
        "plans": [
            {
                "plan_id": p.id,
                "name": p.name,
                "status": p.status.value,
                "steps": len(p.steps),
                "created_at": p.created_at.isoformat()
            }
            for p in engine.plans.values()
        ]
    }

# =============================================================================
# MCP Tool Interface
# =============================================================================

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "create_plan":
        plan = engine.create_plan(**params)
        return {"plan_id": plan.id}
    elif tool == "execute_plan":
        plan = await engine.execute_plan(params.get("plan_id"))
        return {"status": plan.status.value}
    elif tool == "get_plan":
        plan = engine.get_plan(params.get("plan_id"))
        return {"plan": plan.__dict__ if plan else None}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
