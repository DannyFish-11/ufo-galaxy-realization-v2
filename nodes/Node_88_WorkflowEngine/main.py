"""
Node 88: Workflow Engine - 工作流引擎
Workflow automation and orchestration: define multi-step workflows,
execute them asynchronously, track state, and support branching logic.

Step types:
  transform  - data transformation (expression-based)
  condition  - if/else branching
  http       - outbound HTTP request
  delay      - sleep for N seconds
  log        - emit a log message
  set        - set/update variables in the execution context
"""

import os
import json
import uuid
import ast
import operator as _op
import logging
import asyncio
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
from contextlib import asynccontextmanager
from copy import deepcopy

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

try:
    from core.port_config import get_node_port
    _port_from_config = get_node_port("Node_88_WorkflowEngine")
except Exception:
    _port_from_config = None

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins(): return ["*"]

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = "88"
NODE_NAME = "WorkflowEngine"
PORT = _port_from_config or int(os.getenv("NODE_PORT", "8088"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

WORKFLOW_MAX_STEPS = int(os.getenv("WORKFLOW_MAX_STEPS", "100"))
WORKFLOW_TIMEOUT = int(os.getenv("WORKFLOW_TIMEOUT", "300"))

START_TIME = datetime.now()

STEP_TYPES = ["transform", "condition", "http", "delay", "log", "set"]

# =============================================================================
# Safe Expression Evaluator (no eval/exec of arbitrary code)
# =============================================================================

# Supported operators for safe expression evaluation
_SAFE_OPERATORS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv, ast.Mod: _op.mod,
    ast.Pow: _op.pow, ast.USub: _op.neg, ast.UAdd: _op.pos,
    ast.Eq: _op.eq, ast.NotEq: _op.ne, ast.Lt: _op.lt, ast.LtE: _op.le,
    ast.Gt: _op.gt, ast.GtE: _op.ge,
    ast.And: lambda a, b: a and b, ast.Or: lambda a, b: a or b,
    ast.Not: _op.not_,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}

def _safe_eval(expr: str, ctx: Dict[str, Any]) -> Any:
    """Evaluate a simple arithmetic/comparison expression safely using AST (no eval/exec)."""
    def _eval_node(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("True", "true"):
                return True
            if node.id in ("False", "false"):
                return False
            if node.id in ("None", "null"):
                return None
            if node.id in ctx:
                return ctx[node.id]
            raise ValueError(f"Unknown variable: {node.id!r}")
        if isinstance(node, ast.BinOp):
            op_fn = _SAFE_OPERATORS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
            return op_fn(_eval_node(node.left), _eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            op_fn = _SAFE_OPERATORS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
            return op_fn(_eval_node(node.operand))
        if isinstance(node, ast.BoolOp):
            op_fn = _SAFE_OPERATORS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported bool operator")
            result = _eval_node(node.values[0])
            for val in node.values[1:]:
                result = op_fn(result, _eval_node(val))
            return result
        if isinstance(node, ast.Compare):
            left = _eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                op_fn = _SAFE_OPERATORS.get(type(op))
                if op_fn is None:
                    raise ValueError(f"Unsupported comparator: {type(op).__name__}")
                right = _eval_node(comparator)
                if not op_fn(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Attribute):
            obj = _eval_node(node.value)
            attr = node.attr
            # Only allow safe attribute access (e.g., list.len via len() is covered elsewhere)
            if attr.startswith("_"):
                raise ValueError(f"Access to private attribute {attr!r} is not allowed")
            return getattr(obj, attr)
        if isinstance(node, ast.Subscript):
            obj = _eval_node(node.value)
            key = _eval_node(node.slice)
            return obj[key]
        if isinstance(node, ast.List):
            return [_eval_node(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {_eval_node(k): _eval_node(v) for k, v in zip(node.keys, node.values)}
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    try:
        tree = ast.parse(expr.strip(), mode="eval")
        return _eval_node(tree.body)
    except (SyntaxError, ValueError) as e:
        raise RuntimeError(f"Expression error: {e}")

# =============================================================================
# Pydantic Models
# =============================================================================

class WorkflowStep(BaseModel):
    id: str = Field(..., description="Unique step ID within the workflow")
    type: str = Field(..., description=f"Step type: {STEP_TYPES}")
    action: Optional[str] = Field(None, description="Action name (for transform/log)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Step parameters")
    next: Optional[str] = Field(None, description="ID of next step (default: sequential)")
    next_true: Optional[str] = Field(None, description="Next step if condition is True")
    next_false: Optional[str] = Field(None, description="Next step if condition is False")

class WorkflowDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    steps: List[WorkflowStep]
    start_step: Optional[str] = Field(None, description="ID of first step (default: first in list)")
    tags: List[str] = Field(default_factory=list)

class ExecuteRequest(BaseModel):
    input: Dict[str, Any] = Field(default_factory=dict, description="Input data for the workflow")

class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}

# =============================================================================
# Workflow Engine
# =============================================================================

class WorkflowEngine:
    def __init__(self):
        self.workflows: Dict[str, dict] = {}        # workflow_id -> definition + metadata
        self.executions: Dict[str, dict] = {}       # execution_id -> execution state
        self._running: Dict[str, asyncio.Task] = {} # execution_id -> task

    # -------------------------------------------------------------------------
    # Workflow CRUD
    # -------------------------------------------------------------------------

    def create_workflow(self, definition: WorkflowDefinition) -> dict:
        if len(definition.steps) > WORKFLOW_MAX_STEPS:
            return {"success": False, "error": f"Workflow exceeds max step limit ({WORKFLOW_MAX_STEPS})"}

        step_ids = {s.id for s in definition.steps}
        for step in definition.steps:
            for next_id in [step.next, step.next_true, step.next_false]:
                if next_id and next_id not in step_ids:
                    return {"success": False, "error": f"Step '{step.id}' references unknown next step '{next_id}'"}
            if step.type not in STEP_TYPES:
                return {"success": False, "error": f"Unknown step type '{step.type}'. Valid: {STEP_TYPES}"}

        wf_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        start = definition.start_step or definition.steps[0].id if definition.steps else None
        self.workflows[wf_id] = {
            "id": wf_id,
            "name": definition.name,
            "description": definition.description,
            "steps": [s.model_dump() for s in definition.steps],
            "start_step": start,
            "tags": definition.tags,
            "created_at": now,
            "updated_at": now,
            "execution_count": 0,
        }
        logger.info(f"✅ Created workflow '{definition.name}' ({wf_id})")
        return {"success": True, "workflow_id": wf_id, "workflow": self.workflows[wf_id]}

    def get_workflow(self, workflow_id: str) -> Optional[dict]:
        return self.workflows.get(workflow_id)

    def list_workflows(self) -> List[dict]:
        return list(self.workflows.values())

    def delete_workflow(self, workflow_id: str) -> dict:
        if workflow_id not in self.workflows:
            return {"success": False, "error": f"Workflow '{workflow_id}' not found"}
        wf = self.workflows.pop(workflow_id)
        logger.info(f"Deleted workflow '{wf['name']}' ({workflow_id})")
        return {"success": True, "deleted": workflow_id}

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    def _new_execution(self, workflow_id: str, input_data: dict) -> dict:
        exec_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        execution = {
            "id": exec_id,
            "workflow_id": workflow_id,
            "status": "pending",
            "input": deepcopy(input_data),
            "context": deepcopy(input_data),
            "step_logs": [],
            "current_step": None,
            "started_at": now,
            "completed_at": None,
            "error": None,
            "output": None,
        }
        self.executions[exec_id] = execution
        return execution

    async def execute_workflow(self, workflow_id: str, input_data: dict) -> dict:
        wf = self.workflows.get(workflow_id)
        if not wf:
            return {"success": False, "error": f"Workflow '{workflow_id}' not found"}

        execution = self._new_execution(workflow_id, input_data)
        exec_id = execution["id"]
        wf["execution_count"] = wf.get("execution_count", 0) + 1

        task = asyncio.create_task(self._run_execution(exec_id, wf))
        self._running[exec_id] = task
        task.add_done_callback(lambda t: self._running.pop(exec_id, None))

        return {
            "success": True,
            "execution_id": exec_id,
            "status": "running",
            "message": f"Execution started for workflow '{wf['name']}'",
        }

    async def _run_execution(self, exec_id: str, wf: dict):
        execution = self.executions[exec_id]
        execution["status"] = "running"
        steps_by_id = {s["id"]: s for s in wf["steps"]}

        current_id = wf.get("start_step") or (wf["steps"][0]["id"] if wf["steps"] else None)
        if not current_id:
            execution["status"] = "failed"
            execution["error"] = "No steps defined in workflow"
            execution["completed_at"] = datetime.now().isoformat()
            return

        visited = 0
        try:
            async with asyncio.timeout(WORKFLOW_TIMEOUT):
                while current_id:
                    if visited >= WORKFLOW_MAX_STEPS:
                        raise RuntimeError(f"Max step iterations reached ({WORKFLOW_MAX_STEPS})")
                    step = steps_by_id.get(current_id)
                    if not step:
                        raise RuntimeError(f"Step '{current_id}' not found in workflow")

                    execution["current_step"] = current_id
                    step_log = {
                        "step_id": current_id,
                        "type": step["type"],
                        "started_at": datetime.now().isoformat(),
                        "result": None,
                        "error": None,
                    }
                    execution["step_logs"].append(step_log)

                    try:
                        next_id = await self._execute_step(step, execution["context"])
                        step_log["result"] = "ok"
                        step_log["completed_at"] = datetime.now().isoformat()
                        # Determine next step
                        if next_id is not None:
                            current_id = next_id
                        elif step.get("next"):
                            current_id = step["next"]
                        else:
                            # Move to next step sequentially
                            step_list = wf["steps"]
                            idx = next((i for i, s in enumerate(step_list) if s["id"] == current_id), None)
                            current_id = step_list[idx + 1]["id"] if idx is not None and idx + 1 < len(step_list) else None
                    except Exception as e:
                        step_log["error"] = str(e)
                        step_log["completed_at"] = datetime.now().isoformat()
                        raise RuntimeError(f"Step '{current_id}' failed: {e}") from e

                    visited += 1

            execution["status"] = "completed"
            execution["output"] = deepcopy(execution["context"])
        except asyncio.TimeoutError:
            execution["status"] = "timeout"
            execution["error"] = f"Execution exceeded timeout ({WORKFLOW_TIMEOUT}s)"
        except Exception as e:
            execution["status"] = "failed"
            execution["error"] = str(e)
        finally:
            execution["completed_at"] = datetime.now().isoformat()
            execution["current_step"] = None
            logger.info(f"Execution {exec_id} finished: {execution['status']}")

    async def _execute_step(self, step: dict, ctx: dict) -> Optional[str]:
        """Execute a single step, return explicit next step ID or None for default."""
        stype = step["type"]
        params = step.get("params", {})

        if stype == "set":
            for k, v in params.items():
                ctx[k] = self._resolve(v, ctx)
            return None

        elif stype == "log":
            msg = self._resolve(params.get("message", ""), ctx)
            level = params.get("level", "info").lower()
            getattr(logger, level, logger.info)(f"[workflow log] {msg}")
            return None

        elif stype == "delay":
            seconds = float(self._resolve(params.get("seconds", 1), ctx))
            await asyncio.sleep(seconds)
            return None

        elif stype == "transform":
            # Evaluate a simple expression safely; result stored in output_key
            expression = params.get("expression", "")
            output_key = params.get("output_key", "result")
            ctx[output_key] = _safe_eval(expression, ctx)
            return None

        elif stype == "condition":
            expression = params.get("expression", "True")
            result = bool(_safe_eval(expression, ctx))
            ctx["__last_condition__"] = result
            return step.get("next_true") if result else step.get("next_false")

        elif stype == "http":
            method = params.get("method", "GET").upper()
            url = self._resolve(params.get("url", ""), ctx)
            headers = {k: self._resolve(v, ctx) for k, v in params.get("headers", {}).items()}
            body = params.get("body")
            if isinstance(body, dict):
                body = {k: self._resolve(v, ctx) for k, v in body.items()}
            timeout = float(params.get("timeout", 30))
            output_key = params.get("output_key", "http_response")
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, headers=headers, json=body)
                resp.raise_for_status()
                try:
                    ctx[output_key] = resp.json()
                except Exception:
                    ctx[output_key] = resp.text
            return None

        else:
            raise RuntimeError(f"Unknown step type: {stype}")

    def _resolve(self, value: Any, ctx: dict) -> Any:
        """Resolve a string template {{key}} against context, or return value as-is."""
        if isinstance(value, str):
            for k, v in ctx.items():
                value = value.replace(f"{{{{{k}}}}}", str(v))
            return value
        return value

    # -------------------------------------------------------------------------
    # Execution management
    # -------------------------------------------------------------------------

    def get_execution(self, execution_id: str) -> Optional[dict]:
        return self.executions.get(execution_id)

    def list_executions(self, limit: int = 50) -> List[dict]:
        execs = list(self.executions.values())
        return sorted(execs, key=lambda e: e.get("started_at", ""), reverse=True)[:limit]

    async def cancel_execution(self, execution_id: str) -> dict:
        task = self._running.get(execution_id)
        if not task:
            exec_state = self.executions.get(execution_id)
            if exec_state and exec_state["status"] not in ("running", "pending"):
                return {"success": False, "error": f"Execution '{execution_id}' is not running (status: {exec_state['status']})"}
            return {"success": False, "error": f"Execution '{execution_id}' not found or not running"}
        task.cancel()
        exec_state = self.executions.get(execution_id)
        if exec_state:
            exec_state["status"] = "cancelled"
            exec_state["completed_at"] = datetime.now().isoformat()
        return {"success": True, "execution_id": execution_id, "status": "cancelled"}


engine = WorkflowEngine()

# =============================================================================
# App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"⚙️  Node {NODE_ID} {NODE_NAME} starting on port {PORT}")
    logger.info(f"  Max steps : {WORKFLOW_MAX_STEPS}")
    logger.info(f"  Timeout   : {WORKFLOW_TIMEOUT}s")
    yield
    logger.info(f"Node {NODE_ID} shutting down")


app = FastAPI(
    title=f"Node {NODE_ID} - {NODE_NAME}",
    description="Workflow automation engine: define, execute, monitor multi-step workflows",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Routes
# =============================================================================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - START_TIME).total_seconds()
    running_count = len(engine._running)
    return {
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "status": "running",
        "uptime_seconds": uptime,
        "configuration": {
            "max_steps": WORKFLOW_MAX_STEPS,
            "timeout_seconds": WORKFLOW_TIMEOUT,
        },
        "metrics": {
            "total_workflows": len(engine.workflows),
            "total_executions": len(engine.executions),
            "running_executions": running_count,
        },
        "step_types": STEP_TYPES,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/workflows")
async def list_workflows():
    return {"success": True, "workflows": engine.list_workflows(), "count": len(engine.workflows)}


@app.post("/workflow/create")
async def create_workflow(definition: WorkflowDefinition):
    result = engine.create_workflow(definition)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    wf = engine.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    return {"success": True, "workflow": wf}


@app.delete("/workflow/{workflow_id}")
async def delete_workflow(workflow_id: str):
    result = engine.delete_workflow(workflow_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/workflow/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, req: ExecuteRequest):
    result = await engine.execute_workflow(workflow_id, req.input)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/execution/{execution_id}")
async def get_execution(execution_id: str):
    ex = engine.get_execution(execution_id)
    if not ex:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return {"success": True, "execution": ex}


@app.get("/executions")
async def list_executions(limit: int = 50):
    execs = engine.list_executions(limit)
    return {"success": True, "executions": execs, "count": len(execs)}


@app.post("/execution/{execution_id}/cancel")
async def cancel_execution(execution_id: str):
    result = await engine.cancel_execution(execution_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    params = req.parameters

    if tool == "create_workflow":
        return engine.create_workflow(WorkflowDefinition(**params))
    elif tool == "execute_workflow":
        wf_id = params.pop("workflow_id")
        return await engine.execute_workflow(wf_id, params.get("input", {}))
    elif tool == "get_workflow":
        wf = engine.get_workflow(params.get("workflow_id", ""))
        if not wf:
            return {"success": False, "error": "Workflow not found"}
        return {"success": True, "workflow": wf}
    elif tool == "list_workflows":
        return {"success": True, "workflows": engine.list_workflows()}
    elif tool == "delete_workflow":
        return engine.delete_workflow(params.get("workflow_id", ""))
    elif tool == "get_execution":
        ex = engine.get_execution(params.get("execution_id", ""))
        if not ex:
            return {"success": False, "error": "Execution not found"}
        return {"success": True, "execution": ex}
    elif tool == "list_executions":
        return {"success": True, "executions": engine.list_executions(params.get("limit", 50))}
    elif tool == "cancel_execution":
        return await engine.cancel_execution(params.get("execution_id", ""))
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool '{tool}'. Available: create_workflow, execute_workflow, get_workflow, "
                   "list_workflows, delete_workflow, get_execution, list_executions, cancel_execution"
        )


def get_instance():
    return engine


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
