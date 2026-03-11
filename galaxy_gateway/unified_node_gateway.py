#!/usr/bin/env python3
"""
Galaxy Fusion - Unified Node Gateway (Standardized)

统一节点网关（标准化版）

核心职责:
1. 动态加载 102 个节点的标准化入口 (fusion_entry.py)
2. 提供统一的 HTTP API 路由 (/api/nodes/{node_id}/execute)
3. 隔离节点执行环境，提供统一的错误处理

作者: Manus AI
日期: 2026-01-26
版本: 1.1.0 (标准化版)
"""

import os
import sys
import time
import importlib
import logging
import asyncio
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from core.port_config import get_service_port
from core.schemas.node_protocol import NodeRequest, NodeResponse, NodeHealthResponse

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UnifiedGateway")

app = FastAPI(title="Galaxy Unified Node Gateway")

# 节点实例缓存
node_instances: Dict[str, Any] = {}

class ExecuteRequest(BaseModel):
    command: str
    params: Dict[str, Any] = {}

def load_nodes():
    """动态扫描并加载 nodes/ 目录下的所有标准化节点"""
    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
    if not os.path.exists(nodes_dir):
        logger.error(f"❌ Nodes directory not found: {nodes_dir}")
        return

    if nodes_dir not in sys.path:
        sys.path.append(nodes_dir)
    
    # 扫描 Node_XX 格式的目录
    for item in os.listdir(nodes_dir):
        if item.startswith("Node_") and os.path.isdir(os.path.join(nodes_dir, item)):
            node_id = "_".join(item.split('_')[:2])
            try:
                # 优先加载标准化入口 fusion_entry.py
                module_path = f"{item}.fusion_entry"
                try:
                    module = importlib.import_module(module_path)
                    if hasattr(module, "get_node_instance"):
                        node_instances[node_id] = module.get_node_instance()
                        logger.info(f"✅ Loaded standardized node: {node_id}")
                        continue
                except ImportError:
                    logger.debug(f"ℹ️  No fusion_entry found for {node_id}, trying legacy load...")

                # 备选：尝试直接加载 main.py (旧逻辑)
                module_path = f"{item}.main"
                module = importlib.import_module(module_path)
                instance = None
                if hasattr(module, "get_instance"):
                    instance = module.get_instance()
                elif hasattr(module, "Node"):
                    instance = module.Node()
                
                if instance:
                    node_instances[node_id] = instance
                    logger.info(f"✅ Loaded legacy node: {node_id}")
                else:
                    logger.warning(f"⚠️  Node {node_id} has no valid entry point")
            except Exception as e:
                logger.error(f"❌ Failed to load node {node_id}: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Unified Node Gateway...")
    load_nodes()
    logger.info(f"✨ Total nodes online: {len(node_instances)}")

@app.get("/health")
async def global_health():
    return {"status": "healthy", "online_nodes": len(node_instances)}

@app.post("/api/nodes/{node_id}/execute")
async def execute_on_node(node_id: str, request: ExecuteRequest):
    if node_id not in node_instances:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    
    instance = node_instances[node_id]
    
    try:
        # 统一调用接口
        if hasattr(instance, "execute"):
            method = instance.execute
        elif hasattr(instance, "process"):
            method = instance.process
        else:
            raise HTTPException(status_code=500, detail=f"Node {node_id} has no executable method")
            
        if asyncio.iscoroutinefunction(method):
            result = await method(request.command, **request.params)
        else:
            result = method(request.command, **request.params)
            
        # 如果返回的是字典且包含 success 键，则直接返回
        if isinstance(result, dict) and "success" in result:
            return result
        return {"success": True, "node_id": node_id, "data": result}
        
    except Exception as e:
        logger.error(f"❌ Error executing on {node_id}: {e}")
        return {"success": False, "node_id": node_id, "error": str(e)}

# ============================================================================
# 标准化节点调用适配层 (Phase 8.3)
# ============================================================================

async def call_node_standardized(
    node_id: str, action: str, params: Optional[Dict[str, Any]] = None,
    caller: str = "gateway", timeout: float = 30.0,
) -> NodeResponse:
    """标准化节点调用 — Agent 和 Gateway 统一入口

    将任意格式的节点调用和响应标准化为 NodeRequest/NodeResponse，
    兼容旧格式节点（裸数据、dict 等）自动包装。

    Args:
        node_id: 节点 ID，如 "Node_06" 或 "Node_06_Filesystem"
        action: 执行动作名称
        params: 动作参数
        caller: 调用者标识 (gateway/agent/scheduler)
        timeout: 超时秒数

    Returns:
        NodeResponse 标准格式
    """
    request = NodeRequest(
        action=action,
        params=params or {},
        caller=caller,
        timeout=timeout,
    )
    t0 = time.time()

    # 查找节点实例
    instance = node_instances.get(node_id)
    if instance is None:
        # 尝试短 ID 匹配（如 "Node_06" 匹配 "Node_06_Filesystem"）
        for key, inst in node_instances.items():
            if key.startswith(node_id):
                instance = inst
                node_id = key
                break

    if instance is None:
        return NodeResponse(
            success=False,
            error=f"节点 {node_id} 未加载",
            error_code="NOT_FOUND",
            request_id=request.request_id,
            node_id=node_id,
            latency_ms=(time.time() - t0) * 1000,
        )

    try:
        # 确定执行方法
        if hasattr(instance, "execute"):
            method = instance.execute
        elif hasattr(instance, "process"):
            method = instance.process
        else:
            return NodeResponse(
                success=False,
                error=f"节点 {node_id} 无可执行方法 (execute/process)",
                error_code="INTERNAL",
                request_id=request.request_id,
                node_id=node_id,
                latency_ms=(time.time() - t0) * 1000,
            )

        # 执行（带超时保护）
        if asyncio.iscoroutinefunction(method):
            raw_result = await asyncio.wait_for(
                method(request.action, **request.params),
                timeout=request.timeout,
            )
        else:
            raw_result = method(request.action, **request.params)

        elapsed_ms = (time.time() - t0) * 1000

        # 使用 NodeResponse.from_raw 自动适配旧格式
        return NodeResponse.from_raw(
            node_id=node_id,
            raw=raw_result,
            request_id=request.request_id,
            latency_ms=round(elapsed_ms, 1),
        )

    except asyncio.TimeoutError:
        return NodeResponse(
            success=False,
            error=f"节点 {node_id} 执行超时 ({request.timeout}s)",
            error_code="TIMEOUT",
            request_id=request.request_id,
            node_id=node_id,
            latency_ms=(time.time() - t0) * 1000,
        )
    except Exception as e:
        logger.error(f"标准化调用 {node_id}.{action} 失败: {e}")
        return NodeResponse(
            success=False,
            error=str(e),
            error_code="INTERNAL",
            request_id=request.request_id,
            node_id=node_id,
            latency_ms=(time.time() - t0) * 1000,
        )


async def health_check_node_standardized(node_id: str) -> NodeHealthResponse:
    """标准化节点健康检查"""
    instance = node_instances.get(node_id)
    if instance is None:
        return NodeHealthResponse(status="unhealthy", node_id=node_id)

    if hasattr(instance, "health") and callable(instance.health):
        try:
            raw = instance.health()
            if asyncio.iscoroutinefunction(instance.health):
                raw = await raw
            return NodeHealthResponse.from_raw(node_id, raw)
        except Exception:
            return NodeHealthResponse(status="degraded", node_id=node_id)

    # 节点已加载但无 health 方法 → 视为 healthy
    return NodeHealthResponse(status="healthy", node_id=node_id)


# 暴露标准化 API 端点
@app.post("/api/nodes/{node_id}/execute_standardized")
async def execute_standardized(node_id: str, request: NodeRequest):
    """标准化节点执行端点 — 返回 NodeResponse 格式"""
    response = await call_node_standardized(
        node_id=node_id,
        action=request.action,
        params=request.params,
        caller=request.caller,
        timeout=request.timeout,
    )
    return response.model_dump()


@app.get("/api/nodes/{node_id}/health_standardized")
async def health_standardized(node_id: str):
    """标准化节点健康检查端点"""
    response = await health_check_node_standardized(node_id)
    return response.model_dump()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=get_service_port("state_machine"))
