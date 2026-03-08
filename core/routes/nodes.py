"""
UFO Galaxy - Node & Agent Routes
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

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.routes._shared import (
    connection_manager,
    registered_devices,
    node_status_cache,
    task_queue,
)
from core.routes._helpers import nodes_root, _load_node, _execute_node
from core.routes._models import NodeCallRequest

logger = logging.getLogger("UFO-Galaxy.API")


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
                        except Exception:
                            pass

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
            except Exception:
                pass

        status = node_status_cache.get(node_name, {})
        return JSONResponse({
            "name": node_name,
            "config": node_config,
            "status": status,
            "has_fusion_entry": os.path.exists(os.path.join(node_dir, "fusion_entry.py")),
            "has_dockerfile": os.path.exists(os.path.join(node_dir, "Dockerfile"))
        })

    @router.post("/api/v1/agent/deploy")
    async def deploy_agent(req: AgentDeployRequest):
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
    async def autonomous_execute(req: AutonomousRequest):
        """自主调度接口：接收自然语言指令，自动规划并执行节点任务 (ReAct Loop)"""
        try:
            async def node_executor(node_id: str, action: str, params: dict):
                target_node_dir = os.path.join(nodes_root, node_id)
                if not os.path.isdir(target_node_dir):
                    for name in os.listdir(nodes_root):
                        if name.startswith(node_id) or node_id in name:
                            target_node_dir = os.path.join(nodes_root, name)
                            node_id = name
                            break

                if not os.path.isdir(target_node_dir):
                    return {"error": f"Node {node_id} not found"}

                fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
                if not os.path.exists(fusion_entry):
                    return {"error": f"Node {node_id} has no fusion_entry.py"}

                node_instance = _load_node(node_id, target_node_dir, fusion_entry)
                if not node_instance:
                    return {"error": f"Failed to load node {node_id}"}

                try:
                    result = await _execute_node(node_instance, action, params)
                    return result
                except Exception as e:
                    logger.error(f"Node execution error: {e}")
                    return {"error": str(e)}

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

    @router.post("/api/v1/nodes/call")
    async def call_node(req: NodeCallRequest):
        """调用节点执行操作"""
        task_id = str(uuid.uuid4())

        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "nodes")
        node_dir = os.path.join(nodes_dir, req.node_id)
        fusion_entry = os.path.join(node_dir, "fusion_entry.py")

        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail=f"节点 {req.node_id} 未找到")

        task_queue[task_id] = {
            "task_id": task_id,
            "node_id": req.node_id,
            "action": req.action,
            "params": req.params,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }

        try:
            if os.path.exists(fusion_entry):
                node_info = _load_node(req.node_id, node_dir, fusion_entry)

                if node_info:
                    task_queue[task_id]["status"] = "running"
                    result = await _execute_node(node_info, req.action, req.params or {})
                    task_queue[task_id]["status"] = "completed"
                    task_queue[task_id]["result"] = result
                    return JSONResponse({
                        "success": True,
                        "task_id": task_id,
                        "result": result
                    })
                else:
                    logger.warning(f"节点 {req.node_id} 的 fusion_entry.py 没有可调用的 execute 方法")

            return JSONResponse({
                "success": True,
                "task_id": task_id,
                "status": "queued",
                "message": f"任务已排队，节点 {req.node_id} 将异步处理"
            })

        except Exception as e:
            task_queue[task_id]["status"] = "failed"
            task_queue[task_id]["error"] = str(e)
            logger.error(f"节点调用失败: {req.node_id}.{req.action}: {e}")
            return JSONResponse({
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }, status_code=500)

    return router
