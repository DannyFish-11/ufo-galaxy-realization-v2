"""
Galaxy - Node & Agent Routes
===================================

Routes:
  GET  /api/v1/nodes                  - 列出节点
  GET  /api/v1/nodes/{node_name}      - 节点详情
  POST /api/v1/nodes/call             - 调用节点
  POST /api/v1/agent/deploy           - 部署 Agent 到设备
  POST /api/v1/agent/autonomous       - 自主调度执行
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_auth
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.routes._shared import (
    connection_manager,
    registered_devices,
    node_status_cache,
    task_queue,
)
from core.routes._helpers import nodes_root
from core.routes._models import NodeCallRequest
from core.node_invocation import invoke_node, InvocationSource

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create node and agent routes router."""
    router = APIRouter()

    from core.scheduler import AutonomousScheduler
    from core.multi_llm_router import get_llm_router

    scheduler = AutonomousScheduler(nodes_root)
    llm_router = get_llm_router()

    class AutonomousRequest(BaseModel):
        instruction: str
        context: Dict[str, Any] = {}
        model_alias: Optional[str] = None

    class AgentDeployRequest(BaseModel):
        """Agent 部署请求"""
        target_device: str               # 目标设备 ID
        instruction: str                  # 自然语言指令
        execution_mode: str = "react"     # react / sequential / autonomous
        tools: List[Dict[str, Any]] = []  # 工具声明 (可选, 默认使用设备标准工具)
        priority: str = "normal"
        timeout_seconds: int = 300

    @router.get("/api/v1/nodes")
    async def list_nodes():
        """列出所有可用节点"""
        nodes = []
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "nodes")
        if os.path.isdir(nodes_dir):
            for name in sorted(os.listdir(nodes_dir)):
                node_dir = os.path.join(nodes_dir, name)
                if os.path.isdir(node_dir) and os.path.exists(os.path.join(node_dir, "main.py")):
                    config_file = os.path.join(node_dir, "config.json")
                    node_config = {}
                    if os.path.exists(config_file):
                        try:
                            with open(config_file, encoding="utf-8") as f:
                                node_config = json.load(f)
                        except Exception as e:
                            logger.warning(f"加载节点配置失败 {config_file}: {e}")

                    status = node_status_cache.get(name, {})
                    nodes.append({
                        "name": name,
                        "description": node_config.get("description", ""),
                        "group": node_config.get("group", ""),
                        "status": status.get("status", "stopped"),
                        "capabilities": node_config.get("capabilities", [])
                    })

        return JSONResponse({"nodes": nodes, "total": len(nodes)})

    @router.get("/api/v1/nodes/{node_name}")
    async def get_node(node_name: str):
        """获取节点详情"""
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "nodes")
        node_dir = os.path.join(nodes_dir, node_name)

        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail=f"节点 {node_name} 未找到")

        config_file = os.path.join(node_dir, "config.json")
        node_config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, encoding="utf-8") as f:
                    node_config = json.load(f)
            except Exception as e:
                logger.warning(f"加载节点配置失败 {config_file}: {e}")

        status = node_status_cache.get(node_name, {})
        return JSONResponse({
            "name": node_name,
            "config": node_config,
            "status": status,
            "has_fusion_entry": os.path.exists(os.path.join(node_dir, "fusion_entry.py")),
            "has_dockerfile": os.path.exists(os.path.join(node_dir, "Dockerfile"))
        })

    @router.post("/api/v1/agent/deploy")
    async def deploy_agent(req: AgentDeployRequest, auth: dict = Depends(require_auth)):
        """
        部署 Agent 到端侧设备

        将 AgentManifest 通过 WebSocket 推送到指定设备,
        设备端的 LocalAgentRuntime 接收后自主执行。
        """
        try:
            from core.agent_manifest import AgentManifest

            manifest = AgentManifest.create_device_control_agent(
                target_device=req.target_device,
                instruction=req.instruction,
                source_device="server",
            )
            manifest.execution_mode = req.execution_mode
            manifest.priority = req.priority
            manifest.timeout_seconds = req.timeout_seconds
            if req.tools:
                manifest.tools = req.tools

            manifest_dict = manifest.to_dict()
            checksum = manifest.checksum()

            ws_message = {
                "type": "agent_deploy",
                "manifest": manifest_dict,
                "checksum": checksum,
            }

            if req.target_device in connection_manager.active_devices:
                success = await connection_manager.send_to_device(req.target_device, ws_message)
                if success:
                    logger.info(f"Agent {manifest.manifest_id[:8]} deployed to {req.target_device}")
                    return {
                        "success": True,
                        "manifest_id": manifest.manifest_id,
                        "target_device": req.target_device,
                        "checksum": checksum,
                        "status": "deployed",
                    }
                else:
                    return {"success": False, "error": f"WebSocket send failed to {req.target_device}"}
            else:
                return {
                    "success": False,
                    "error": f"Device {req.target_device} not connected",
                    "manifest_id": manifest.manifest_id,
                    "status": "queued",
                }
        except Exception as e:
            logger.error(f"Agent deploy failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/agent/autonomous")
    async def autonomous_execute(req: AutonomousRequest, auth: dict = Depends(require_auth)):
        """自主调度接口：接收自然语言指令，自动规划并执行节点任务 (ReAct Loop)"""
        try:
            async def node_executor(node_id: str, action: str, params: dict):
                # Route through the unified executor (PR-4 / PR-5) instead of
                # calling _load_node / _execute_node directly.
                result = await invoke_node(
                    node_id,
                    action,
                    params,
                    invocation_source=InvocationSource.CAPABILITY,
                )
                if result.success:
                    return result.result if result.result is not None else {"success": True}
                return {"error": result.error or "Node execution failed"}

            execution_context = req.context.copy()
            execution_context["devices"] = registered_devices
            execution_context["executor"] = node_executor

            try:
                plan_result = await scheduler.plan_and_execute(
                    req.instruction,
                    llm_router,
                    execution_context
                )
                return plan_result
            except ValueError as ve:
                logger.warning(f"LLM not configured, falling back to rule-based: {ve}")
                executed_tasks = []
                if "唤醒" in req.instruction:
                    for did in registered_devices:
                        await connection_manager.send_to_device(
                            did,
                            {"type": "task", "task_type": "wake_up", "payload": {"msg": req.instruction}},
                        )
                        executed_tasks.append(f"Waking up device {did}")
                    return {
                        "success": True,
                        "reply": "已通过规则引擎唤醒所有设备 (请配置 LLM 以启用智能调度)",
                        "steps": [{"action": "wake_up", "result": "success"}]
                    }
                raise HTTPException(status_code=500, detail="LLM not configured and no rule matched")

        except Exception as e:
            logger.error(f"Autonomous execution failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ─────── Agent Factory Unified API ─────────

    class AgentCreateRequest(BaseModel):
        agent_type: str = "task"           # task / device / twin / fractal
        task_description: str = ""
        template_name: str = ""
        device_id: str = ""
        device_type: str = ""
        context: Dict[str, Any] = {}

    @router.get("/api/v1/agent/templates")
    async def list_agent_templates():
        """列出所有可用 Agent 模板"""
        from core.agent_factory import get_agent_factory
        factory = get_agent_factory(llm_router)
        return JSONResponse({
            "templates": factory.list_templates(),
            "agent_types": ["task", "device", "twin", "fractal"],
        })

    @router.get("/api/v1/agent/status")
    async def agent_factory_status():
        """Agent 工厂状态"""
        from core.agent_factory import get_agent_factory
        factory = get_agent_factory(llm_router)
        return JSONResponse(factory.get_status())

    @router.post("/api/v1/agent/create")
    async def create_agent_unified(req: AgentCreateRequest, auth: dict = Depends(require_auth)):
        """统一 Agent 创建接口"""
        from core.agent_factory import get_agent_factory
        factory = get_agent_factory(llm_router)
        try:
            result = factory.create_unified(
                agent_type=req.agent_type,
                task_description=req.task_description,
                template_name=req.template_name,
                device_id=req.device_id,
                device_type=req.device_type,
                context=req.context,
            )
            return JSONResponse(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/api/v1/nodes/call")
    async def call_node(req: NodeCallRequest):
        """调用节点执行操作"""
        task_id = str(uuid.uuid4())

        task_queue[task_id] = {
            "task_id": task_id,
            "node_id": req.node_id,
            "action": req.action,
            "params": req.params,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }

        task_queue[task_id]["status"] = "running"
        invocation_result = await invoke_node(
            req.node_id,
            req.action,
            req.params or {},
            invocation_source=InvocationSource.REST,
            task_id=task_id,
        )

        if invocation_result.success:
            task_queue[task_id]["status"] = "completed"
            task_queue[task_id]["result"] = invocation_result.result
            return JSONResponse({
                "success": True,
                "task_id": task_id,
                "request_id": invocation_result.request_id,
                "trace_id": invocation_result.trace_id,
                "result": invocation_result.result,
                "duration_ms": invocation_result.duration_ms,
            })
        else:
            task_queue[task_id]["status"] = "failed"
            task_queue[task_id]["error"] = invocation_result.error
            logger.error(f"节点调用失败: {req.node_id}.{req.action}: {invocation_result.error}")
            status_code = 404 if "目录未找到" in (invocation_result.error or "") else 500
            return JSONResponse({
                "success": False,
                "task_id": task_id,
                "request_id": invocation_result.request_id,
                "trace_id": invocation_result.trace_id,
                "error": invocation_result.error,
            }, status_code=status_code)

    return router
