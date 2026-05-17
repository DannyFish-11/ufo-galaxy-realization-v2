"""
Galaxy - Hybrid, RAG, Code & Mesh Routes (Phases 3-5)
===========================================================

Routes:
  POST /api/v1/hybrid/execute        - 混合执行 (A2A → GUI → VLM)
  GET  /api/v1/hybrid/stats          - 混合执行统计
  GET  /api/v1/hybrid/registry       - 应用能力注册表
  POST /api/v1/rag/query             - RAG 综合检索
  GET  /api/v1/rag/stats             - RAG 记忆统计
  GET  /api/v1/rag/patterns          - 已学习 Patterns
  POST /api/v1/code/execute          - 安全代码执行
  GET  /api/v1/code/stats            - 代码执行统计
  POST /api/v1/mesh/send             - Mesh P2P 发送
  POST /api/v1/mesh/peer_announce    - Peer 上报
  POST /api/v1/mesh/peer_exchange    - Peer 交换
  GET  /api/v1/mesh/topology         - 拓扑图
  GET  /api/v1/mesh/peers            - Peer 列表
  GET  /api/v1/mesh/stats            - Mesh 统计
  POST /api/v1/mesh/probe            - 触发 TCP 探测
"""

import logging
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from core.auth import require_auth
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.routes._shared import connection_manager

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create hybrid execution, RAG, code, and mesh routes router."""
    router = APIRouter()

    # ── Phase 3: Hybrid Execution ──────────────────────────────────────────

    from core.hybrid_executor import get_hybrid_arbiter, ExecutionLevel

    hybrid_arbiter = get_hybrid_arbiter()

    class HybridExecuteRequest(BaseModel):
        """混合执行请求"""
        device_id: str
        app_id: str = ""
        action: str = ""
        params: Dict[str, Any] = {}
        instruction: str = ""
        force_level: Optional[str] = None  # a2a / gui / vlm

    @router.post("/api/v1/hybrid/execute")
    async def hybrid_execute(req: HybridExecuteRequest):
        """
        混合执行 — 三级降级: A2A → GUI → VLM
        """
        force = ExecutionLevel(req.force_level) if req.force_level else None
        result = await hybrid_arbiter.execute(
            device_id=req.device_id,
            app_id=req.app_id,
            action=req.action,
            params=req.params,
            instruction=req.instruction,
            force_level=force,
        )
        return JSONResponse(result.to_dict())

    @router.get("/api/v1/hybrid/stats")
    async def hybrid_stats():
        """混合执行统计"""
        return JSONResponse(hybrid_arbiter.get_stats())

    @router.get("/api/v1/hybrid/registry")
    async def hybrid_registry():
        """应用能力注册表"""
        return JSONResponse({"apps": hybrid_arbiter.registry.list_apps()})

    # ── Phase 4: RAG Memory + SafeExecutor ─────────────────────────────────

    from core.rag_memory import get_rag_memory
    from core.safe_executor import get_safe_executor

    rag_memory = get_rag_memory()
    safe_executor = get_safe_executor()

    class RAGQueryRequest(BaseModel):
        """RAG 检索请求"""
        query: str
        top_k: int = 5
        include_experience: bool = True
        include_knowledge: bool = True
        device_id: str = ""

    class CodeExecuteRequest(BaseModel):
        """安全代码执行请求"""
        code: str
        language: str = "python"
        timeout: int = 15
        stdin: str = ""

    @router.post("/api/v1/rag/query")
    async def rag_query(req: RAGQueryRequest):
        """RAG 综合检索 — 经验 + 知识"""
        enhanced_context = await rag_memory.enhance_agent_prompt(
            instruction=req.query,
            device_id=req.device_id,
            include_experience=req.include_experience,
            include_knowledge=req.include_knowledge,
        )
        similar_experiences = rag_memory.recall_similar(req.query, top_k=req.top_k, device_id=req.device_id)
        return JSONResponse({
            "enhanced_context": enhanced_context,
            "experiences": [e.to_dict() for e in similar_experiences],
            "patterns": rag_memory.get_learned_patterns(),
        })

    @router.get("/api/v1/rag/stats")
    async def rag_stats():
        """RAG 记忆统计"""
        return JSONResponse(rag_memory.get_stats())

    @router.get("/api/v1/rag/patterns")
    async def rag_patterns():
        """已学习的 Patterns"""
        return JSONResponse({"patterns": rag_memory.get_learned_patterns()})

    @router.post("/api/v1/code/execute")
    async def code_execute(req: CodeExecuteRequest, auth: dict = Depends(require_auth)):
        """安全代码执行 — Agent 自编码运行时"""
        result = await safe_executor.execute(
            code=req.code,
            language=req.language,
            timeout=req.timeout,
            stdin=req.stdin,
        )
        return JSONResponse(result.to_dict())

    @router.get("/api/v1/code/stats")
    async def code_stats():
        """代码执行统计"""
        return JSONResponse(safe_executor.get_stats())

    # ── Phase 5: P2P Mesh Overlay ──────────────────────────────────────────

    from core.mesh_coordinator import get_mesh_coordinator
    from core.proxy_relay import get_proxy_relay, RelayRequest as ProxyRelayRequest

    mesh_coordinator = get_mesh_coordinator()
    proxy_relay = get_proxy_relay()

    mesh_coordinator._ws_send = connection_manager.send_to_device

    async def _mesh_p2p_send(target_device: str, msg_bytes: bytes) -> bool:
        """Use device-scoped point-to-point delivery as runtime direct-send surface."""
        try:
            decoded = msg_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.warning("mesh direct p2p-equivalent send failed: payload is not valid UTF-8 (%s)", exc)
            return False

        try:
            msg = json.loads(decoded)
            if not isinstance(msg, dict):
                logger.warning("mesh direct p2p-equivalent send failed: payload is not a JSON object")
                return False
            msg.setdefault("transport", "mesh_direct_point_to_point")
            msg.setdefault("transport_via", "gateway_device_channel")
            return await connection_manager.send_to_device(target_device, msg)
        except json.JSONDecodeError as exc:
            logger.warning("mesh direct p2p-equivalent send failed: payload JSON decode failed (%s)", exc)
            return False
        except Exception as exc:
            logger.warning("mesh direct p2p-equivalent send failed: %s", exc)
            return False

    mesh_coordinator._p2p_send = _mesh_p2p_send

    async def _mesh_relay_send(source, target, payload_type, payload):
        result = await proxy_relay.relay(ProxyRelayRequest(
            source_device=source,
            target_device=target,
            payload_type=payload_type,
            payload=payload,
        ))
        return result.to_dict()

    mesh_coordinator._relay_send = _mesh_relay_send

    class MeshSendRequest(BaseModel):
        """Mesh 发送请求"""
        target_device: str
        payload: Dict[str, Any] = {}
        payload_type: str = "task"
        source_device: str = ""

    class PeerAnnounceRequest(BaseModel):
        """Peer 上报请求"""
        device_id: str
        local_ip: str = ""
        local_port: int = 0
        public_ip: str = ""
        public_port: int = 0
        metadata: Dict[str, Any] = {}

    @router.post("/api/v1/mesh/send")
    async def mesh_send(req: MeshSendRequest):
        """Mesh 发送 — P2P 直连 / Relay 自动选路

        Transport hierarchy note (PR-4):
        This endpoint is an overlay / topology-enrichment send path.
        It is subordinate to the canonical transport hierarchy:
          direct WS = primary, relay = fallback, mesh = overlay only.
        Successful delivery via this path does not imply canonical
        routability or orchestration eligibility.
        """
        result = await mesh_coordinator.send(
            target_device=req.target_device,
            payload=req.payload,
            payload_type=req.payload_type,
            source_device=req.source_device,
        )
        return JSONResponse(result.to_dict())

    @router.post("/api/v1/mesh/peer_announce")
    async def mesh_peer_announce(req: PeerAnnounceRequest):
        """设备上报 LAN 地址信息"""
        peer = mesh_coordinator.handle_peer_announce(req.device_id, req.dict())
        return JSONResponse(peer.to_dict())

    @router.post("/api/v1/mesh/peer_exchange")
    async def mesh_peer_exchange():
        """触发 peer 列表交换 — 广播给所有设备"""
        await mesh_coordinator.broadcast_peer_exchange()
        return JSONResponse({"status": "exchanged", "peers": mesh_coordinator.list_peers()})

    @router.get("/api/v1/mesh/topology")
    async def mesh_topology():
        """获取完整拓扑图 (nodes + edges)"""
        return JSONResponse(mesh_coordinator.get_topology())

    @router.get("/api/v1/mesh/peers")
    async def mesh_peers():
        """获取所有 peer 列表"""
        return JSONResponse({"peers": mesh_coordinator.list_peers()})

    @router.get("/api/v1/mesh/stats")
    async def mesh_stats():
        """Mesh 网络统计"""
        return JSONResponse(mesh_coordinator.get_stats())

    @router.post("/api/v1/mesh/probe")
    async def mesh_probe():
        """手动触发所有 peer 的 TCP 可达性探测"""
        await mesh_coordinator.probe_all_peers()
        return JSONResponse({"status": "probed", "peers": mesh_coordinator.list_peers()})

    return router
