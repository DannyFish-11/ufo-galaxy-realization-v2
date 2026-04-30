"""
Galaxy - Node & Agent Routes
===================================

Routes:
  GET  /api/v1/nodes                  - 列出节点（canonical: NodeFabricRegistry）
  GET  /api/v1/nodes/{node_name}      - 节点详情（canonical: NodeFabricRegistry）
  POST /api/v1/nodes/call             - 调用节点
  POST /api/v1/agent/deploy           - 部署 Agent 到设备
  POST /api/v1/agent/autonomous       - 自主调度执行

  GET  /api/v1/nodes/legacy/filesystem  - LEGACY/COMPAT: filesystem-based node list

Architecture note (PR-3)
------------------------
``GET /api/v1/nodes`` and ``GET /api/v1/nodes/{node_name}`` are canonical
node-list/detail surfaces.  They derive node membership and runtime status
from :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` (the
canonical runtime registry), NOT from raw filesystem scans.

A node that exists on disk but has not been registered in NodeFabricRegistry
will NOT appear in the canonical list/detail responses.  The separate
``GET /api/v1/nodes/legacy/filesystem`` route is an explicitly-marked
legacy/compat surface for diagnostics and administrative tooling; it must
not be treated as canonical runtime authority.

``node_status_cache`` (from core.routes._shared) is a legacy in-memory
cache.  It is no longer consulted by canonical list/detail surfaces.
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
    task_queue,
)
from core.routes._helpers import nodes_root
from core.routes._models import NodeCallRequest
from core.node_invocation import invoke_node, InvocationSource

logger = logging.getLogger("Galaxy.API")

# ─── PR-3 policy sentinels (node list/detail canonical surface) ───────────────
# These are imported here so that test/audit code can verify the canonical
# node list/detail refactor has been applied to this module.
try:
    from core.nodes.node_fabric_registry import (  # noqa: F401
        CANONICAL_NODE_LIST_SURFACE_READS_FROM_REGISTRY_POLICY as _POLICY_LIST,
        FILESYSTEM_SCAN_IS_NOT_NODE_MEMBERSHIP_AUTHORITY_POLICY as _POLICY_FS,
        NODE_STATUS_CACHE_IS_NOT_CANONICAL_STATUS_SOURCE_POLICY as _POLICY_CACHE,
    )
    _CANONICAL_NODE_LIST_SURFACE_PR3_ALIGNED = True
except ImportError:  # pragma: no cover
    _CANONICAL_NODE_LIST_SURFACE_PR3_ALIGNED = False


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create node and agent routes router."""
    router = APIRouter()

    from core.scheduler import AutonomousScheduler
    from core.llm.route_authority import get_llm_route_authority

    scheduler = AutonomousScheduler(nodes_root)
    llm_router = get_llm_route_authority().execution_router

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
        """列出所有可用节点（canonical: NodeFabricRegistry）。

        Primary authority: NodeFabricRegistry.
        A node must be registered in NodeFabricRegistry to appear here.
        Filesystem metadata (config.json) is read as supplemental context only.

        Use GET /api/v1/nodes/legacy/filesystem for the legacy filesystem-based
        listing (explicit compat/diagnostics path).
        """
        nodes = []
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            fab = get_node_fabric_registry()
            for node_info in sorted(fab.list_nodes(), key=lambda n: n.node_id):
                # Supplement with static filesystem metadata (config.json) if present.
                node_config: Dict[str, Any] = {}
                node_dir = os.path.join(nodes_root, node_info.node_id)
                config_file = os.path.join(node_dir, "config.json")
                if os.path.isdir(node_dir) and os.path.exists(config_file):
                    try:
                        with open(config_file, encoding="utf-8") as f:
                            node_config = json.load(f)
                    except Exception as e:
                        logger.debug(f"加载节点配置失败 {config_file}: {e}")

                # Merge: registry metadata takes precedence; config.json fills gaps.
                reg_meta: Dict[str, Any] = (
                    node_info.metadata if isinstance(node_info.metadata, dict) else {}
                )
                nodes.append({
                    "name": node_info.node_id,
                    "description": reg_meta.get(
                        "description", node_config.get("description", "")
                    ),
                    "group": reg_meta.get("group", node_config.get("group", "")),
                    "status": (
                        node_info.status.value
                        if hasattr(node_info.status, "value")
                        else str(node_info.status)
                    ),
                    "capabilities": (
                        node_info.capability_names()
                        or node_config.get("capabilities", [])
                    ),
                    "role": (
                        node_info.role.value
                        if hasattr(node_info.role, "value")
                        else str(node_info.role)
                    ),
                    "health_score": round(node_info.health_score(), 4),
                    "registry_source": "canonical",
                })
        except Exception as e:
            logger.warning(f"list_nodes: NodeFabricRegistry unavailable: {e}")

        return JSONResponse({
            "nodes": nodes,
            "total": len(nodes),
            "registry_authority": "canonical:NodeFabricRegistry",
        })

    @router.get("/api/v1/nodes/legacy/filesystem")
    async def list_nodes_legacy_filesystem():
        """LEGACY/COMPAT: 从磁盘目录扫描列出节点。

        ⚠️  This is an explicit legacy/compat surface for diagnostics and
        administrative tooling ONLY.  It is NOT canonical runtime authority.
        A node appearing here does not mean it belongs to the active system.

        Use GET /api/v1/nodes for the canonical runtime-aligned node list.
        """
        nodes = []
        nodes_dir = nodes_root
        if os.path.isdir(nodes_dir):
            for name in sorted(os.listdir(nodes_dir)):
                node_dir = os.path.join(nodes_dir, name)
                if os.path.isdir(node_dir) and os.path.exists(
                    os.path.join(node_dir, "main.py")
                ):
                    config_file = os.path.join(node_dir, "config.json")
                    node_config: Dict[str, Any] = {}
                    if os.path.exists(config_file):
                        try:
                            with open(config_file, encoding="utf-8") as f:
                                node_config = json.load(f)
                        except Exception as e:
                            logger.warning(f"加载节点配置失败 {config_file}: {e}")
                    nodes.append({
                        "name": name,
                        "description": node_config.get("description", ""),
                        "group": node_config.get("group", ""),
                        "has_main": True,
                        "has_fusion_entry": os.path.exists(
                            os.path.join(node_dir, "fusion_entry.py")
                        ),
                        "capabilities": node_config.get("capabilities", []),
                        "registry_source": "legacy_filesystem",
                    })

        return JSONResponse({
            "nodes": nodes,
            "total": len(nodes),
            "_compat_warning": (
                "This endpoint lists nodes by filesystem presence only.  "
                "It is NOT canonical runtime authority.  "
                "Use /api/v1/nodes for canonical node list."
            ),
        })

    @router.get("/api/v1/nodes/{node_name}")
    async def get_node(node_name: str):
        """获取节点详情（canonical: NodeFabricRegistry）。

        Primary authority: NodeFabricRegistry.
        Returns 404 if the node is not registered in the canonical registry.
        Filesystem metadata (config.json) is read as supplemental context only.
        """
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            fab = get_node_fabric_registry()
            node_info = fab.get(node_name)
        except Exception as e:
            logger.warning(f"get_node: NodeFabricRegistry unavailable: {e}")
            node_info = None

        if node_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"节点 {node_name} 未在 canonical registry (NodeFabricRegistry) 中找到",
            )

        # Supplement with static filesystem metadata (config.json) if present.
        node_dir = os.path.join(nodes_root, node_name)
        node_config: Dict[str, Any] = {}
        config_file = os.path.join(node_dir, "config.json")
        if os.path.isdir(node_dir) and os.path.exists(config_file):
            try:
                with open(config_file, encoding="utf-8") as f:
                    node_config = json.load(f)
            except Exception as e:
                logger.debug(f"加载节点配置失败 {config_file}: {e}")

        return JSONResponse({
            "name": node_info.node_id,
            "status": (
                node_info.status.value
                if hasattr(node_info.status, "value")
                else str(node_info.status)
            ),
            "role": (
                node_info.role.value
                if hasattr(node_info.role, "value")
                else str(node_info.role)
            ),
            "health_score": round(node_info.health_score(), 4),
            "capabilities": node_info.capability_names(),
            "host": node_info.host,
            "port": node_info.port,
            "metadata": node_info.metadata if isinstance(node_info.metadata, dict) else {},
            "config": node_config,
            "has_fusion_entry": os.path.exists(os.path.join(node_dir, "fusion_entry.py")),
            "has_dockerfile": os.path.exists(os.path.join(node_dir, "Dockerfile")),
            "registry_source": "canonical",
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
